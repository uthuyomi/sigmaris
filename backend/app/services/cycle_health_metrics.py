# 役割: Phase R-2「循環健全性指標(RC)」の純粋な指標計算ロジック。
#
# C-mini/C-full(eval_metrics.py)が「記憶検索の精度」を測るのに対し、
# ここではExperience→Memory→Temporal Evaluation→Belief→Policy→Actionと
# いう循環自体がどれだけ機能しているかを測る。**これらは別系統の指標で
# あり、C-mini/C-fullのmemory_precision等と同一の尺度・同一のsigmaris_
# eval_runsテーブルでは扱わない**(docs/sigmaris/phase_r_report.md参照)。
#
# R-2ではRC-1(Cycle Completion Rate)・RC-2(Temporal Consistency
# Score)を実装した。R-3ではRC-3(Belief Stability Index)・RC-4
# (Policy-Belief Alignment)・RC-5(Cycle Break Detection)を追加し、
# RC指標を完成させる。
#
# I/Oを一切持たない純粋関数のみを置く。DB呼び出しはcycle_health_runner.py
# 側の責務(eval_metrics.py/eval_runner.pyと同じ役割分担をそのまま踏襲)。

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ─── RC-1: Cycle Completion Rate ───────────────────────────────────────────
#
# 「あるExperienceが実際にMemoryまで到達したか」を、R-1のsource_
# experience_ids参照が繋がっているかで判定する。B2の設計上、Experience
# からMemoryへ到達する唯一の経路はconsolidate_episodic_memory()(週次
# バッチ)であり、これは (a) 直近_CONSOLIDATION_SCAN_WINDOW件のみを毎回
# 再走査し、(b) 全体のexperience総数が_MIN_EXPERIENCES_FOR_CONSOLIDATION
# 未満なら何もせず、(c) 単発では原則昇格させず複数件の裏付けを要求する、
# という設計になっている(phase_b2_report.md参照)。
#
# つまり「到達しなかった」ことの大部分は、この設計上当然に起こりうる
# (=意図的)ものであり、それ自体は異常ではない。一方で、(a)(b)の構造的
# 条件をクリアしているのに到達していない場合、それが本当に「裏付け不足
# で昇格しなかった」健全なケースなのか、それとも本来昇格すべきだったのに
# バグ等で見逃されたケースなのかは、LLMの再判定なしには区別できない
# (=循環破損の自動検知はR-3のスコープ)。
#
# そのため本指標は、非到達の理由を「構造的に説明できる(=タイミング・
# 母数の都合で、そもそもこのExperience個別の問題ではありえない)」もの
# と、「構造的な障害はクリアしているが、それでも昇格しなかった(=大半は
# 健全な非昇格、まれに見逃しが混ざりうるが、これ以上の自動判別はしない)」
# ものに分類するに留める。単純な到達率だけでなく、構造的に非到達が
# 説明できるものを除いた「eligible_completion_rate」も併せて算出する。

NON_REACH_NOT_YET_ELIGIBLE = "not_yet_eligible"
NON_REACH_INSUFFICIENT_VOLUME = "system_wide_insufficient_volume"
NON_REACH_AGED_OUT = "likely_aged_out_of_window"
NON_REACH_EVALUATED_NOT_PROMOTED = "evaluated_not_promoted"

# 構造的に「このExperience個別の問題ではありえない」非到達理由。
# eligible_completion_rateの算出時にこれらは母数から除外する。
# NON_REACH_AGED_OUTは意図的に含めない — これはconsolidate_episodic_
# memory()の再スキャン設計の副作用ではあるが、「本来なら昇格候補になり
# 得たのに、後続のexperience増加によって二度と評価されなくなった」可能性
# がある(phase_b2_report.md 5節が既に指摘していた懸念)ため、「異常では
# ないが、カバレッジの穴として監視すべき」という中間的な扱いとし、
# eligible_completion_rateには影響させる(母数に残す)。
NON_REACH_STRUCTURALLY_EXCLUDED = frozenset({
    NON_REACH_NOT_YET_ELIGIBLE,
    NON_REACH_INSUFFICIENT_VOLUME,
})


@dataclass
class ExperienceReachStatus:
    experience_id: str
    reached: bool
    non_reach_reason: str | None  # Noneはreached=Trueのときのみ


@dataclass
class CycleCompletionResult:
    total_experiences: int
    reached_count: int
    raw_completion_rate: float
    eligible_count: int
    eligible_completion_rate: float | None  # eligible_count=0ならNone(算出不能、0.0と混同しない)
    reason_counts: dict[str, int]
    statuses: list[ExperienceReachStatus] = field(default_factory=list)


def classify_experience_reach(
    experiences: list[dict[str, Any]],
    *,
    reached_experience_ids: set[str],
    last_scheduled_consolidation_at: datetime | None,
    total_experience_pool_size: int,
    min_experiences_for_consolidation: int,
    consolidation_scan_window: int,
) -> CycleCompletionResult:
    """RC-1本体。

    experiences: 対象期間内に作られたsigmaris_experience行のリスト
    ({"id", "created_at"}を含む)。順不同でよい(内部でcreated_at昇順に
    並べ替える)。

    reached_experience_ids: user_fact_items.source_experience_idsの和集合
    (cycle_health_runner.pyが全アクティブfactから構築する)。この集合に
    含まれるexperience idは「到達」とみなす。

    last_scheduled_consolidation_at: 直近の(実行時刻から見て過去の)
    consolidate_episodic_memory()の予定実行時刻。まだ一度もこの時刻を
    過ぎていないexperience(created_atがこれより後)は、そもそもまだ
    バッチに評価される機会が一度もなかったとみなす。

    total_experience_pool_size: 現在のシステム全体(期間に限らない)の
    アクティブexperience総数。consolidate_episodic_memory()自体がこの
    総数でinsufficient_dataゲートするため、期間内のサブセットではなく
    全体数で判定する必要がある。

    consolidation_scan_window: consolidate_episodic_memory()が1回のバッチ
    実行で走査する直近N件(experience_layer._CONSOLIDATION_SCAN_WINDOW)。
    「aged out」判定の近似に使う(下記の限界の通り、過去の走査時点の
    正確な母数は分からないため、現在時点の順位で近似する)。

    既知の近似の限界: aged_out判定は「現在の時点で、このexperienceより
    新しいexperienceが何件あるか」を数えることで、過去のバッチ実行時点
    で既にwindowの外にあった可能性を推定している。実際に過去のどの時点
    でwindow外だったかの履歴は保持されていないため、これは正確な判定
    ではなく近似であることを明記する。
    """
    reason_counts: dict[str, int] = {}
    statuses: list[ExperienceReachStatus] = []

    # 母数ゲートは一律に適用する: *現在の*総数が閾値未満であれば、この
    # バッチに含まれる全experienceは、作られた時期に関わらず現時点では
    # 一律にconsolidate_episodic_memory()からinsufficient_dataとしてまと
    # めてスキップされる対象である。
    pool_insufficient = total_experience_pool_size < min_experiences_for_consolidation

    ordered = sorted(
        (e for e in experiences if isinstance(e.get("id"), str)),
        key=lambda e: _parse_ts(e.get("created_at")) or datetime.min,
    )
    # 「現時点でこのexperienceより新しいexperienceが何件あるか」
    # (このバッチ内で数える — 期間内のexperienceより新しいものは、
    # created_atの定義上、必ず同じ期間内に含まれるため、この範囲で数えて
    # も母数として不足しない)。
    newer_count_by_id = {
        e["id"]: len(ordered) - 1 - idx for idx, e in enumerate(ordered)
    }

    for exp in experiences:
        exp_id = exp.get("id")
        if not isinstance(exp_id, str):
            continue
        if exp_id in reached_experience_ids:
            statuses.append(ExperienceReachStatus(exp_id, True, None))
            continue

        created_at = _parse_ts(exp.get("created_at"))
        if pool_insufficient:
            reason = NON_REACH_INSUFFICIENT_VOLUME
        elif (
            last_scheduled_consolidation_at is not None
            and created_at is not None
            and created_at > last_scheduled_consolidation_at
        ):
            reason = NON_REACH_NOT_YET_ELIGIBLE
        elif newer_count_by_id.get(exp_id, 0) >= consolidation_scan_window:
            reason = NON_REACH_AGED_OUT
        else:
            reason = NON_REACH_EVALUATED_NOT_PROMOTED

        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        statuses.append(ExperienceReachStatus(exp_id, False, reason))

    total = len(statuses)
    reached = sum(1 for s in statuses if s.reached)
    raw_rate = reached / total if total else 0.0

    excluded = sum(
        count for reason, count in reason_counts.items()
        if reason in NON_REACH_STRUCTURALLY_EXCLUDED
    )
    eligible_count = total - excluded
    eligible_rate = reached / eligible_count if eligible_count else None

    return CycleCompletionResult(
        total_experiences=total,
        reached_count=reached,
        raw_completion_rate=raw_rate,
        eligible_count=eligible_count,
        eligible_completion_rate=eligible_rate,
        reason_counts=reason_counts,
        statuses=statuses,
    )


# ─── RC-2: Temporal Consistency Score ──────────────────────────────────────
#
# 2種類の「時間的にありえない矛盾」を検出する。いずれも「発生しないのが
# 正常」なチェックであり、C-mini系の指標とは異なり0.0〜1.0の"精度"ではな
# く"整合性"を表す — 1.0は「検出した矛盾がゼロ」を意味し、それ自体は
# 「たくさん検査して見つからなかった」のか「検査対象がそもそも少なかっ
# た」のかを区別できるよう、checked件数を必ず併記する。

@dataclass
class ChatOrderViolation:
    thread_id: str
    index_in_thread: int  # list_chat_messages()が返す順序中の位置(0始まり)
    prev_created_at: str
    created_at: str


@dataclass
class ChatOrderResult:
    threads_checked: int
    pairs_checked: int
    violations: list[ChatOrderViolation]
    collapsed_timestamp_ratio: float  # 参考値。下記docstring参照


def check_chat_message_order(
    threads: dict[str, list[dict[str, Any]]],
) -> ChatOrderResult:
    """スレッドごとのchat_messages(list_chat_messages()の戻り値、
    message_order昇順で既に並んでいる)を渡すと、「message_orderの並び順
    に対してcreated_atが後退している(=実際の会話順序と矛盾する)」箇所
    を検出する(docs/sigmaris/phase_ba4_report.md 17章の"タイムスタンプ
    崩壊"バグが動機)。

    collapsed_timestamp_ratio: 同一スレッド内で3件以上のメッセージが全く
    同一のcreated_atを持つ("崩壊"クラスタ)に属するメッセージの割合。
    直近1ターン分(新規ユーザー発言+新規アシスタント応答)がDBの
    `now()`デフォルトで同一トランザクション時刻を共有するのは正常な挙動
    のため(2件までは崩壊とみなさない)、3件以上の共有だけを崩壊として
    数える。これは並び順そのものへの違反ではない(created_atが後退して
    いるわけではないため)ため、下記violationsには含めず、別軸の参考値
    として返す — 過去の汚染データがどの程度残っているかを可視化する
    目的であり、この値自体がスコアに直接ペナルティを与えるわけではない
    (レポート参照)。
    """
    violations: list[ChatOrderViolation] = []
    collapsed_count = 0
    total_messages = 0
    pairs_checked = 0

    for thread_id, messages in threads.items():
        total_messages += len(messages)

        timestamp_counts: dict[str, int] = {}
        for msg in messages:
            ts = msg.get("created_at")
            if isinstance(ts, str) and ts:
                timestamp_counts[ts] = timestamp_counts.get(ts, 0) + 1
        collapsed_count += sum(count for count in timestamp_counts.values() if count >= 3)

        prev_ts_str: str | None = None
        prev_ts: datetime | None = None
        for index, msg in enumerate(messages):
            ts_str = msg.get("created_at")
            ts = _parse_ts(ts_str)
            if prev_ts is not None and ts is not None:
                pairs_checked += 1
                if ts < prev_ts:
                    violations.append(
                        ChatOrderViolation(
                            thread_id=thread_id,
                            index_in_thread=index,
                            prev_created_at=prev_ts_str or "",
                            created_at=ts_str or "",
                        )
                    )
            if ts is not None:
                prev_ts, prev_ts_str = ts, ts_str

    collapsed_ratio = collapsed_count / total_messages if total_messages else 0.0

    return ChatOrderResult(
        threads_checked=len(threads),
        pairs_checked=pairs_checked,
        violations=violations,
        collapsed_timestamp_ratio=collapsed_ratio,
    )


@dataclass
class EventExperienceViolation:
    fact_id: str
    fact_created_at: str
    experience_id: str
    experience_created_at: str


def check_event_facts_against_experiences(
    event_facts_with_experiences: list[tuple[dict[str, Any], list[dict[str, Any]]]],
) -> list[EventExperienceViolation]:
    """memory_kind='event'かつsource_experience_idsを持つuser_fact_items
    行それぞれについて、それが依拠したsigmaris_experience行より古い
    created_atを持っていないかを確認する。

    consolidate_episodic_memory()は既存のexperienceを読み取ってから新規
    factをINSERTするため、factのcreated_atは参照している全experienceの
    created_at以上でなければならない(そうでなければ、まだ存在していない
    experienceを参照したfactが作られたことになり、時系列的にありえない)。

    直接会話由来(memory_extractor.py、thread_id/invocation_id経由)の
    factは対象外 — こちらはfact抽出とepisode検出が同一ターンの2つの
    独立したfire-and-forgetタスクとして並行実行されるため(_cognitive_
    layer_bgとは別の_extract_facts_bg)、数百ミリ秒単位の前後関係の逆転
    が正常運用でも起こりうる、レースコンディション由来の順序であり、
    "矛盾"の検出対象にすべきではないと判断した(判断根拠、レポート参照)。

    event_facts_with_experiences: 各要素は
    (fact_item_dict, [そのfactが参照するsigmaris_experience行, ...])。
    cycle_trace.trace_memory_to_experience()の"source_experiences"を
    そのまま使える形。
    """
    violations: list[EventExperienceViolation] = []
    for fact, experiences in event_facts_with_experiences:
        fact_id = fact.get("id")
        fact_created_raw = fact.get("created_at")
        fact_created = _parse_ts(fact_created_raw)
        if not isinstance(fact_id, str) or fact_created is None or not experiences:
            continue

        newest_experience = max(
            experiences,
            key=lambda e: _parse_ts(e.get("created_at")) or datetime.min,
        )
        exp_created = _parse_ts(newest_experience.get("created_at"))
        if exp_created is not None and fact_created < exp_created:
            violations.append(
                EventExperienceViolation(
                    fact_id=fact_id,
                    fact_created_at=str(fact_created_raw),
                    experience_id=str(newest_experience.get("id")),
                    experience_created_at=str(newest_experience.get("created_at")),
                )
            )
    return violations


@dataclass
class TemporalConsistencyResult:
    score: float | None  # 検査対象が一件もなければNone(0.0/1.0と混同しない)
    period_from: str | None
    period_to: str | None
    chat_order: ChatOrderResult
    event_experience_checked: int
    event_experience_violations: list[EventExperienceViolation]


def compute_temporal_consistency_score(
    *,
    chat_order: ChatOrderResult,
    event_experience_checked: int,
    event_experience_violations: list[EventExperienceViolation],
    period_from: str | None,
    period_to: str | None,
) -> TemporalConsistencyResult:
    """2種類のチェックを、それぞれ検査件数で重み付けした単一スコアに
    合成する。どちらか一方の検査件数が0の場合はもう一方のみで算出し、
    両方0ならスコア自体をNoneにする(「矛盾ゼロ=満点」と「そもそも何も
    検査していない」を混同しないため — eval_metrics.pyのresponse_error_
    rateがsample_size=0を明示するのと同じ設計判断)。
    """
    chat_score = (
        1.0 - (len(chat_order.violations) / chat_order.pairs_checked)
        if chat_order.pairs_checked > 0
        else None
    )
    event_score = (
        1.0 - (len(event_experience_violations) / event_experience_checked)
        if event_experience_checked > 0
        else None
    )

    weights = []
    if chat_score is not None:
        weights.append((chat_score, chat_order.pairs_checked))
    if event_score is not None:
        weights.append((event_score, event_experience_checked))

    if not weights:
        score = None
    else:
        total_weight = sum(w for _, w in weights)
        score = sum(s * w for s, w in weights) / total_weight

    return TemporalConsistencyResult(
        score=score,
        period_from=period_from,
        period_to=period_to,
        chat_order=chat_order,
        event_experience_checked=event_experience_checked,
        event_experience_violations=event_experience_violations,
    )


# ─── RC-3: Belief Stability Index ──────────────────────────────────────────
#
# sigmaris_user_preference_patterns(B14)は、既存のpattern_keyへの2回目
# 以降の書き込みが「その場でUPDATE」(decision_log._upsert_preference_
# pattern())であり、過去のpattern_statementの履歴は一切保持されない
# (upsert前の値はDBから失われる)。そのため「信念が覆ったか」を判定する
# には、cycle_health_runs_store.pyに保存した**前回のRC計測実行時点の
# スナップショット**(pattern_key -> {pattern_statement, evidence_count}、
# `details.belief_snapshot`)とのdiffに頼るしかない。これは既存のB14の
# 書き込み経路には一切手を加えない設計判断であり(既存機能への影響を
# 避けるため)、副作用として「初回のRC実行時は比較対象がなく算出不能」
# という制約を持つ(下記score=Noneのケース)。
#
# 「単発のノイズ」と「正当な信念の変化」の区別: pattern_statementが前回
# 実行時から変化していた場合、その変化がevidence_count(裏付けとなる
# distinctな決定の件数、B14自身の`_MIN_SUPPORTING_DECISIONS`ゲートと同じ
# 概念)の十分な増加を伴っていたかを見る。文言だけが変わって裏付けの件数
# がほとんど増えていない(=前回とほぼ同じ決定群を元に、LLMが単に違う
# 言い回しで再生成しただけ、あるいは僅かな新情報で結論が反転した)場合を
# "unsupported"(ノイズの疑いが強い)、十分な新規裏付けを伴う場合を
# "evidenced"(正当な信念の更新の可能性が高い)として区別する。

_MIN_EVIDENCE_GROWTH_FOR_EVIDENCED_CHANGE = 2  # decision_log._MIN_SUPPORTING_DECISIONSと同じ値で揃えた


@dataclass
class BeliefFlip:
    pattern_key: str
    previous_statement: str | None
    current_statement: str | None
    evidence_growth: int
    evidenced: bool


@dataclass
class BeliefStabilityResult:
    score: float | None  # 比較可能なpattern_keyが1件もなければNone
    comparable_pattern_count: int
    flips: list[BeliefFlip]
    unsupported_flip_count: int


def compute_belief_stability(
    *,
    current_patterns: list[dict[str, Any]],
    previous_snapshot: dict[str, dict[str, Any]] | None,
    min_evidence_growth_for_evidenced_change: int = _MIN_EVIDENCE_GROWTH_FOR_EVIDENCED_CHANGE,
) -> BeliefStabilityResult:
    """current_patterns: decision_log.get_active_preference_patterns()の
    戻り値(pattern_key/pattern_statement/evidence_countを含む)。

    previous_snapshot: 前回のRC計測実行が保存したbelief_snapshot
    ({pattern_key: {"pattern_statement": str, "evidence_count": int}})。
    Noneの場合(初回実行、またはstore読み込み失敗)は score=Noneで返す
    ——「信念は安定している(1.0)」ではなく「まだ判定できない」ことを
    明示するため(R-2から一貫する設計判断)。

    score = 1 - (unsupported_flip_count / comparable_pattern_count)。
    分母をflip_countではなくcomparable_pattern_count(比較可能な全
    pattern_key数)にしている判断根拠: 「変化しなかった信念」も安定性の
    証拠として母数に含めるべきであり、flip_countのみを分母にすると
    「1件だけ裏付けありで反転、他は全部安定」というケースと「1件だけ
    裏付けなしで反転、他は全部安定」というケースが、flip_countベースでは
    それぞれ1.0/0.0という極端な差になり、大多数が安定していたという
    事実を反映できない。
    """
    if previous_snapshot is None:
        return BeliefStabilityResult(score=None, comparable_pattern_count=0, flips=[], unsupported_flip_count=0)

    flips: list[BeliefFlip] = []
    comparable = 0
    for pattern in current_patterns:
        key = pattern.get("pattern_key")
        if not isinstance(key, str) or key not in previous_snapshot:
            continue  # 新規pattern_key、または前回スナップショットに含まれない -> 比較不能
        comparable += 1

        prev = previous_snapshot[key]
        prev_statement = prev.get("pattern_statement")
        cur_statement = pattern.get("pattern_statement")
        if prev_statement == cur_statement:
            continue  # 変化なし(=安定)

        prev_evidence = prev.get("evidence_count")
        prev_evidence = prev_evidence if isinstance(prev_evidence, int) else 0
        cur_evidence = pattern.get("evidence_count")
        cur_evidence = cur_evidence if isinstance(cur_evidence, int) else 0
        growth = cur_evidence - prev_evidence
        evidenced = growth >= min_evidence_growth_for_evidenced_change

        flips.append(BeliefFlip(
            pattern_key=key,
            previous_statement=prev_statement,
            current_statement=cur_statement,
            evidence_growth=growth,
            evidenced=evidenced,
        ))

    unsupported = sum(1 for f in flips if not f.evidenced)
    score = 1.0 - (unsupported / comparable) if comparable else None

    return BeliefStabilityResult(
        score=score,
        comparable_pattern_count=comparable,
        flips=flips,
        unsupported_flip_count=unsupported,
    )


def build_belief_snapshot(patterns: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """今回の実行のpattern_key別スナップショットを構築する
    (cycle_health_runs_store.pyがdetails.belief_snapshotとして保存し、
    次回実行のcompute_belief_stability()のprevious_snapshotになる)。"""
    snapshot: dict[str, dict[str, Any]] = {}
    for pattern in patterns:
        key = pattern.get("pattern_key")
        if not isinstance(key, str):
            continue
        snapshot[key] = {
            "pattern_statement": pattern.get("pattern_statement"),
            "evidence_count": pattern.get("evidence_count"),
        }
    return snapshot


# ─── RC-4: Policy-Belief Alignment ─────────────────────────────────────────
#
# B16(sigmaris_goal_alignment_flags)の乖離フラグが、B14(sigmaris_user_
# preference_patterns)が既に確立した判断傾向と同じ決定群を根拠にしている
# かを測る。R-1のcycle_trace.trace_policy_to_evidence()が返す
# evidence_decisions(フラグのevidence_refsのうちdecision_log由来のもの)
# と、B14各patternのsupporting_decision_idsの重なりを見る。

@dataclass
class PolicyBeliefAlignment:
    flag_id: str
    goal_reference: str
    evidence_decision_count: int
    overlapping_decision_count: int
    best_matching_pattern_key: str | None
    alignment_ratio: float | None  # evidence_decision_count=0ならNone


@dataclass
class PolicyBeliefAlignmentResult:
    score: float | None  # 評価可能なフラグが1件もなければNone
    flags_evaluated: int
    alignments: list[PolicyBeliefAlignment]


def compute_policy_belief_alignment(
    *,
    flags_with_evidence_decision_ids: list[tuple[dict[str, Any], list[str]]],
    patterns: list[dict[str, Any]],
) -> PolicyBeliefAlignmentResult:
    """flags_with_evidence_decision_ids: 各要素は
    (sigmaris_goal_alignment_flags行, そのフラグのevidence_refsのうち
    decision_log由来のid一覧) — cycle_trace.trace_policy_to_evidence()の
    "evidence_decisions"からidを取り出したもの。

    patterns: decision_log.get_active_preference_patterns()の戻り値。

    alignment_ratio: フラグの根拠決定のうち、いずれかのBelief pattern
    からも根拠として参照されているものの割合。1.0に近いほど、B16の判定が
    B14の既存の判断傾向と同じ材料に基づいていることを意味する。低い値は
    「B16がB14未反映の新しい材料から乖離を検出した」可能性と「B16の判定
    が実際の判断傾向とずれている」可能性の両方がありうる — このスコア
    単体ではどちらか判別できない(判断根拠、レポート参照)。
    """
    decision_to_pattern_keys: dict[str, set[str]] = {}
    for pattern in patterns:
        key = pattern.get("pattern_key")
        supporting_ids = pattern.get("supporting_decision_ids")
        if not isinstance(key, str) or not isinstance(supporting_ids, list):
            continue
        for decision_id in supporting_ids:
            if isinstance(decision_id, str):
                decision_to_pattern_keys.setdefault(decision_id, set()).add(key)

    alignments: list[PolicyBeliefAlignment] = []
    for flag, decision_ids in flags_with_evidence_decision_ids:
        flag_id = flag.get("id")
        if not isinstance(flag_id, str):
            continue
        decision_ids = [d for d in decision_ids if isinstance(d, str)]

        pattern_hit_counts: dict[str, int] = {}
        overlapping: set[str] = set()
        for decision_id in decision_ids:
            hit_keys = decision_to_pattern_keys.get(decision_id)
            if not hit_keys:
                continue
            overlapping.add(decision_id)
            for pattern_key in hit_keys:
                pattern_hit_counts[pattern_key] = pattern_hit_counts.get(pattern_key, 0) + 1

        best_key = max(pattern_hit_counts, key=lambda k: pattern_hit_counts[k]) if pattern_hit_counts else None
        ratio = len(overlapping) / len(decision_ids) if decision_ids else None

        alignments.append(PolicyBeliefAlignment(
            flag_id=flag_id,
            goal_reference=str(flag.get("goal_reference") or ""),
            evidence_decision_count=len(decision_ids),
            overlapping_decision_count=len(overlapping),
            best_matching_pattern_key=best_key,
            alignment_ratio=ratio,
        ))

    scoreable_ratios = [a.alignment_ratio for a in alignments if a.alignment_ratio is not None]
    score = sum(scoreable_ratios) / len(scoreable_ratios) if scoreable_ratios else None

    return PolicyBeliefAlignmentResult(score=score, flags_evaluated=len(alignments), alignments=alignments)


# ─── RC-5: Cycle Break Detection ───────────────────────────────────────────
#
# RC-1(eligible_completion_rate)・RC-2(score)が、過去の実行群の平均から
# 大きく落ち込んでいないかを確認する、単純な閾値ベースの検知。方針(要件
# 3)通り「循環破損の自動検知」の第一歩として、複雑な統計的異常検知
# (変化点検出等)ではなく、直近の平均との単純な絶対差分比較に留める
# ——実データが蓄積されLLM再判定などによる高度化が必要になった時点で
# 拡張すればよい、という判断(判断根拠、レポート参照)。

_CYCLE_BREAK_MIN_HISTORY = 3  # B2/B14と同じ「recurring patternとして信頼するための最低サンプル数」の考え方を踏襲
_CYCLE_BREAK_DROP_THRESHOLD = 0.2  # 絶対値で20ポイントの低下。未検証の暫定値(レポート参照)


@dataclass
class MetricBreakCheck:
    metric: str
    checkable: bool
    current: float | None
    baseline: float | None
    drop: float | None
    broke_threshold: bool


@dataclass
class CycleBreakResult:
    status: str  # "insufficient_history" | "healthy" | "break_detected"
    checks: list[MetricBreakCheck]


def _check_metric_drop(
    *, metric: str, current: float | None, historical: list[float], min_history: int, drop_threshold: float
) -> MetricBreakCheck:
    if current is None or len(historical) < min_history:
        return MetricBreakCheck(
            metric=metric, checkable=False, current=current, baseline=None, drop=None, broke_threshold=False
        )
    baseline = sum(historical) / len(historical)
    drop = baseline - current
    return MetricBreakCheck(
        metric=metric, checkable=True, current=current, baseline=baseline,
        drop=drop, broke_threshold=drop > drop_threshold,
    )


def detect_cycle_break(
    *,
    current_rc1_eligible_rate: float | None,
    current_rc2_score: float | None,
    historical_rc1_eligible_rates: list[float],
    historical_rc2_scores: list[float],
    min_history: int = _CYCLE_BREAK_MIN_HISTORY,
    drop_threshold: float = _CYCLE_BREAK_DROP_THRESHOLD,
) -> CycleBreakResult:
    """current_*: 今回の実行のRC-1 eligible_completion_rate / RC-2 score
    (raw_completion_rateではなくeligible_completion_rateを使う —
    RC-1自身の設計方針(タイミング・母数由来の非到達を除いた方がより
    "健全性"の実態に近い)をそのまま踏襲)。

    historical_*: cycle_health_runs_store.pyから取得した過去の実行群の
    同じ指標の値のリスト(Noneを含まない、新しい順・古い順は問わない)。

    各指標は独立に判定する。片方が判定不能(履歴不足 or 今回の値が
    None)でも、もう片方が判定可能なら判定を続行する。**両方とも判定
    不能な場合のみ"insufficient_history"とする**(「これまで一度も
    測定していないので何も言えない」であり、"healthy"と等しく扱っては
    ならない)。
    """
    checks = [
        _check_metric_drop(
            metric="rc1_eligible_completion_rate",
            current=current_rc1_eligible_rate,
            historical=historical_rc1_eligible_rates,
            min_history=min_history,
            drop_threshold=drop_threshold,
        ),
        _check_metric_drop(
            metric="rc2_score",
            current=current_rc2_score,
            historical=historical_rc2_scores,
            min_history=min_history,
            drop_threshold=drop_threshold,
        ),
    ]

    checkable = [c for c in checks if c.checkable]
    if not checkable:
        status = "insufficient_history"
    elif any(c.broke_threshold for c in checkable):
        status = "break_detected"
    else:
        status = "healthy"

    return CycleBreakResult(status=status, checks=checks)
