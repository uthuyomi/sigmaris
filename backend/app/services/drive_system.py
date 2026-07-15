# 役割: Phase S-0「Drive System」— 既存の測定・検証系データを、監視用の
# 数字としてではなく、シグマリス自身が内的に気にかける動機(Drive)として
# 読み替える、薄い読み取り専用の集約層。
#
# 【最重要】本モジュールは新しいデータを一切生成しない。既存の3系統の
# 資産を「読み取るだけ」で、書き込み・新規テーブルは持たない
# (docs/sigmaris/phase_s_report.md参照)。
#   - Knowledge-Gap Drive(旧称 Curiosity Drive): B3(active_inquiry.py/
#     memory_validator.py)が既に持っている、未知のプロフィール項目・
#     確信度の低い/古い事実
#   - Mastery Drive: Phase R(cycle_health_runs_store.py)に既に記録されて
#     いる、直近のRC-1(循環完了率)・RC-2(時間的一貫性)・RC-5(循環破損
#     検知)の結果
#   - Coherence Drive: B16(goal_alignment.py)の目標整合性フラグ、および
#     Phase RのRC-4(方策と信念の一致度)
#
# Phase S-1追記: 当初「Curiosity Drive」という名称だったが、既存の
# sigmaris_internal_state.curiosity(会話ターンごとに単調増加するムード
# 値、internal_state.py)、およびcuriosity_engine.py(sigmaris_curiosity_
# queue、研究クエリのキュー)という、無関係な2つの既存概念と名前が衝突
# することがS-0完了報告で発覚した。Phase S-1でKnowledgeGapDrive/
# knowledge_gapへ改称した——判断根拠はdocs/sigmaris/phase_s_report.md
# のS-1セクションを参照。sigmaris_internal_state.curiosity列・
# curiosity_engine.pyの命名はいずれも変更していない(前者は依頼書の
# 明示的な指示、後者は本タスクのスコープ外と判断)。3つの概念全体の
# 詳細な用語整理はdocs/sigmaris/glossary_curiosity.md参照(別タスクで
# 作成、curiosity_engine.pyとの統合可能性の検討結果を含む)。
#
# 3つのDriveは意図的に1つの数値へ統合しない(要件の通り)。それぞれの
# levelは0.0〜1.0で「現在どれだけ高まっているか」を表す独立した値であり、
# 直接比較可能な同一スケールの指標ではないことに注意——例えば
# knowledge_gap.level=0.5とmastery.level=0.5が「同じ強さの動機」である
# ことを意味しない。S-1(Executive Gate)がどう重み付け・比較するかは
# S-1セクション参照。

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.services.cycle_health_runs_store import get_recent_cycle_health_runs
from app.services.goal_alignment import _get_all_flags_for_context
from app.services.memory_validator import get_confirmation_candidates
from app.services.user_fact_data import get_null_fields

# Knowledge-Gap: B3自身の1ターン1問・フィールド単位48時間クールダウンと
# いう運用ペースを踏まえた、経験的な飽和点(判断根拠: この件数を超えても
# 「もっと気になる」が際限なく伸び続けるのは直感に反するため、8件で
# level=1.0に達するようキャップする——未検証の暫定値であることを明記する。
# 他の多くのB群暫定チューニング定数(B1のmatch_threshold等)と同じ性質)。
_KNOWLEDGE_GAP_SATURATION_COUNT = 8

# Coherence: B16の乖離フラグは最低2件以上の裏付け証拠を経て初めて1件
# 生成される(_MIN_SUPPORTING_EVIDENCE、goal_alignment.py)ため、B3の
# 「知らないことリスト」ほど気軽には増えない。少数の存在でも十分な
# シグナルとみなし、knowledge_gapより低い飽和点を設定した(同じく未検証の
# 暫定値)。
_COHERENCE_SATURATION_COUNT = 5

# Mastery: RC-5がbreak_detected(循環の急激な悪化)を検知している場合、
# RC-1/RC-2の生の値がどうであれ、masteryの高まりに最低限のフロアを
# 設ける判断根拠——「悪化の程度」自体は軽微でも、「悪化が検知された」
# という事実そのものが強い動機になるべきという解釈。0.7は
# cycle_health_metrics._CYCLE_BREAK_DROP_THRESHOLD(0.2)同様、未検証の
# 暫定値。
_MASTERY_BREAK_FLOOR = 0.7


@dataclass
class KnowledgeGapDrive:
    """B3(active_inquiry.py)が既に持つ「まだ知らない/確認が必要な」情報
    の量から算出する。新規データは一切生成しない——get_null_fields()・
    get_confirmation_candidates()をそのまま呼び出すのみ。

    Phase S-1で"CuriosityDrive"から改称した(sigmaris_internal_state.
    curiosity・curiosity_engine.pyとの名前衝突を避けるため、判断根拠は
    docs/sigmaris/phase_s_report.md参照)。"""

    level: float
    candidate_count: int
    null_field_count: int
    confirmation_candidate_count: int
    average_confidence_of_confirmation_candidates: float | None
    reason_counts: dict[str, int]  # confirm_reason別内訳(low_confidence/flagged_stale/long_unupdated)


@dataclass
class MasteryDrive:
    """Phase R(sigmaris_cycle_health_runs)に既に記録されているRC-1・
    RC-2・RC-5の最新実行結果から算出する。ライブでrun_cycle_health()を
    再計測することはしない——「既存データを読み取る」という要件に厳密に
    従い、かつrun_cycle_health()自体が複数のDB往復を要する重い処理である
    ため(docs/sigmaris/phase_r_report.md参照)。

    has_data=Falseは「循環は健全」ではなく「まだ一度もRC計測が実行されて
    いない」ことを意味する——levelもNoneになる(0.0と混同しないための
    R-2/R-3から一貫する設計判断)。
    """

    level: float | None
    has_data: bool
    rc1_eligible_completion_rate: float | None
    rc2_score: float | None
    rc5_status: str | None
    rc5_broke_metrics: list[str]
    last_measured_at: str | None


@dataclass
class CoherenceDrive:
    """B16(sigmaris_goal_alignment_flags、cooldown等を考慮しない全件)の
    未解決フラグ数と、Phase RのRC-4(方策と信念の一致度)の最新値から
    算出する。

    goal_alignment.get_active_goal_alignment_flags()は「今まさに会話で
    言及してよいか」という提示クールダウンを持つ応答生成向けの関数
    であり、Drive算出の目的(内的な緊張度の把握、会話への提示可否とは
    無関係)には合わない。R-1・R-3が既に採用した
    _get_all_flags_for_context()(クールダウンを見ない全件取得)を
    そのまま再利用する——新しい「全件取得」関数を追加で作らないための
    判断(判断根拠、レポート参照)。
    """

    level: float
    active_flag_count: int
    total_evidence_count: int
    rc4_score: float | None


@dataclass
class DriveState:
    knowledge_gap: KnowledgeGapDrive
    mastery: MasteryDrive
    coherence: CoherenceDrive


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


async def _compute_knowledge_gap_drive(jwt: str) -> KnowledgeGapDrive:
    try:
        null_fields = await get_null_fields(jwt)
    except Exception:
        null_fields = []
    try:
        confirm_candidates = await get_confirmation_candidates(jwt)
    except Exception:
        confirm_candidates = []

    candidate_count = len(null_fields) + len(confirm_candidates)
    confidences = [
        float(c["confidence"])
        for c in confirm_candidates
        if isinstance(c.get("confidence"), (int, float))
    ]
    reason_counts = dict(Counter(
        c["confirm_reason"] for c in confirm_candidates if isinstance(c.get("confirm_reason"), str)
    ))

    level = min(1.0, candidate_count / _KNOWLEDGE_GAP_SATURATION_COUNT)

    return KnowledgeGapDrive(
        level=level,
        candidate_count=candidate_count,
        null_field_count=len(null_fields),
        confirmation_candidate_count=len(confirm_candidates),
        average_confidence_of_confirmation_candidates=_mean(confidences),
        reason_counts=reason_counts,
    )


async def _compute_mastery_drive() -> MasteryDrive:
    recent_runs = await get_recent_cycle_health_runs(limit=1)
    if not recent_runs:
        return MasteryDrive(
            level=None,
            has_data=False,
            rc1_eligible_completion_rate=None,
            rc2_score=None,
            rc5_status=None,
            rc5_broke_metrics=[],
            last_measured_at=None,
        )

    latest = recent_runs[0]
    rc1_rate = latest.get("rc1_eligible_completion_rate")
    rc1_rate = float(rc1_rate) if isinstance(rc1_rate, (int, float)) else None
    rc2_score = latest.get("rc2_score")
    rc2_score = float(rc2_score) if isinstance(rc2_score, (int, float)) else None
    rc5_status = latest.get("rc5_status") if isinstance(latest.get("rc5_status"), str) else None
    rc5_broke_metrics = latest.get("rc5_broke_metrics")
    rc5_broke_metrics = rc5_broke_metrics if isinstance(rc5_broke_metrics, list) else []

    gaps = [1.0 - v for v in (rc1_rate, rc2_score) if v is not None]
    level = _mean(gaps)
    if rc5_status == "break_detected":
        level = max(level or 0.0, _MASTERY_BREAK_FLOOR)

    return MasteryDrive(
        level=level,
        has_data=True,
        rc1_eligible_completion_rate=rc1_rate,
        rc2_score=rc2_score,
        rc5_status=rc5_status,
        rc5_broke_metrics=rc5_broke_metrics,
        last_measured_at=latest.get("run_at") if isinstance(latest.get("run_at"), str) else None,
    )


async def _compute_coherence_drive() -> CoherenceDrive:
    flags = await _get_all_flags_for_context()
    active_flag_count = len(flags)
    total_evidence_count = sum(
        int(f["evidence_count"]) for f in flags if isinstance(f.get("evidence_count"), (int, float))
    )

    recent_runs = await get_recent_cycle_health_runs(limit=1)
    rc4_score = None
    if recent_runs:
        candidate = recent_runs[0].get("rc4_score")
        rc4_score = float(candidate) if isinstance(candidate, (int, float)) else None

    flag_component = min(1.0, active_flag_count / _COHERENCE_SATURATION_COUNT)
    components = [flag_component]
    if rc4_score is not None:
        components.append(1.0 - rc4_score)
    level = _mean(components)
    assert level is not None  # flag_component is always present

    return CoherenceDrive(
        level=level,
        active_flag_count=active_flag_count,
        total_evidence_count=total_evidence_count,
        rc4_score=rc4_score,
    )


async def get_current_drive_state(jwt: str) -> DriveState:
    """S-1(Executive Gate)・S-2(Goal Proposal)向けの参照インターフェース。

    jwt引数にした判断根拠: 依頼書の例示シグネチャは
    `get_current_drive_state(user_id)` だったが、Knowledge-Gap Driveの
    材料(get_null_fields/get_confirmation_candidates)はいずれもJWT
    スコープのRLS経由でしかuser_fact_items/user_fact_profileを読めない
    (このコードベースの既存関数のシグネチャそのもの)。run_eval.py/
    run_cycle_health.pyが一貫してjwtを主引数にしているのと同じ理由で、
    user_idではなくjwtを受け取る形にした。

    3回のI/O(Knowledge-Gap・Mastery・Coherence)は互いに独立しているが、
    Mastery/Coherenceの両方がget_recent_cycle_health_runs(limit=1)を
    個別に呼んでいる点はやや冗長——ただし1回あたりのコストは単一行の
    SELECTのみで無視できる規模のため、共有・キャッシュ機構を導入するほど
    ではないと判断した(要件2「新規ロジックの追加は必要最小限に」に
    対応する判断)。永続化・TTLキャッシュは導入していない(2章参照)。
    """
    knowledge_gap = await _compute_knowledge_gap_drive(jwt)
    mastery = await _compute_mastery_drive()
    coherence = await _compute_coherence_drive()
    return DriveState(knowledge_gap=knowledge_gap, mastery=mastery, coherence=coherence)
