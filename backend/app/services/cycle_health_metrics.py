# 役割: Phase R-2「循環健全性指標(RC)」の純粋な指標計算ロジック。
#
# C-mini/C-full(eval_metrics.py)が「記憶検索の精度」を測るのに対し、
# ここではExperience→Memory→Temporal Evaluation→Belief→Policy→Actionと
# いう循環自体がどれだけ機能しているかを測る。**これらは別系統の指標で
# あり、C-mini/C-fullのmemory_precision等と同一の尺度・同一のsigmaris_
# eval_runsテーブルでは扱わない**(docs/sigmaris/phase_r_report.md参照)。
#
# 本タスク(R-2)ではRC-1(Cycle Completion Rate)・RC-2(Temporal
# Consistency Score)の2指標のみを扱う。以前の議論で提案された残り3指標
# (信念の安定性・方策と信念の一致度・循環破損の自動検知)はR-3で扱う。
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
