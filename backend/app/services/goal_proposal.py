# 役割: Phase S-2「Goal Proposal & Autotelic Loop」— S-1のExecutive Gate
# が「話しかけてよい」と判定した際に、"具体的に何をするか"を決定・実行
# する層。
#
# 【最重要】既存資産の再利用を最優先する(依頼書の制約)。新しい検索・
# 生成ロジックは追加していない——3つのDriveそれぞれの行動は、いずれも
# 既存の関数をそのまま呼び出すだけで構成されている:
#   - Knowledge-Gap Drive: curiosity_engine.generate_curiosity_queries()
#     (既存、glossary_curiosity.mdが発見したデッドコード)をB2/B3の
#     既存データで呼び出す
#   - Mastery Drive: 言語化のみ(RC-1/RC-2/RC-5の生値からテキストを
#     組み立てるだけ、新規LLM呼び出し・Phase D相当の実装は行わない)
#   - Coherence Drive: B16(goal_alignment.get_active_goal_alignment_flags)
#     の既存の提示ロジックが、次の会話ターンで自動的に機能することを
#     確認するのみ——B16のDB状態(last_surfaced_at等)には一切書き込まない
#     (判断根拠、docs/sigmaris/phase_s_report.md参照)
#
# 生成された行動は、experience_layer.record_experience()(B2、既存)を
# 通じてsigmaris_experienceへ新規Experienceとして記録される。これにより
# Phase Rの循環(Experience→Memory→...)へ自動的に合流する——
# consolidate_episodic_memory()(週次バッチ)・RC-1(循環完了率)は、
# record_experience()が書き込んだ行が「どの経路で生まれたか」を区別せず
# 扱うため、新しい配線を追加する必要はない。

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.curiosity_engine import generate_curiosity_queries
from app.services.drive_system import DriveState
from app.services.executive_gate import ExecutiveGateResult
from app.services.experience_layer import get_recent_experiences, record_experience
from app.services.goal_alignment import get_active_goal_alignment_flags
from app.services.user_fact_data import build_facts_context, get_fact_items

logger = logging.getLogger(__name__)

# Autotelic Loopの優先順位(判断根拠、レポート参照): 依頼書が例示した
# 「Coherence > Mastery > Curiosity(目標との矛盾解消を最優先)」をそのまま
# 採用した。海星さん本人が明言した長期目標との矛盾(Coherence)は、循環
# 自体の健全性(Mastery)より当事者への影響が直接的であり、さらに探索的な
# 知識収集(Knowledge-Gap)は3つの中で最も緊急性が低い、という優先度判断。
_DRIVE_PRIORITY: tuple[str, ...] = ("coherence", "mastery", "knowledge_gap")

# generate_curiosity_queries()の"stale_facts"入力に含める、KnowledgeGap
# Driveの確認候補の件数上限。drive_system.pyのKnowledgeGapDrive.
# confirm_candidatesは無制限に保持しているため、プロンプトへの注入量は
# ここで制限する(他のB群プロンプト構築関数と同じ「上位数件のみ」という
# 慣習)。
_STALE_FACTS_LIMIT = 5
_UNRESOLVED_EXPERIENCES_LIMIT = 5


@dataclass
class GoalProposalResult:
    drive: str  # "coherence" | "mastery" | "knowledge_gap"
    title: str
    description: str
    experience_id: str | None
    details: dict[str, Any]


@dataclass
class _ActionOutcome:
    title: str
    description: str
    category: str  # sigmaris_experience.category
    experience_type: str  # sigmaris_experience.experience_type
    context: dict[str, Any]


async def _act_on_coherence(jwt: str, drive_state: DriveState) -> _ActionOutcome | None:
    """B16(goal_alignment.py)が既に持つ「今まさに会話で言及してよい」
    フラグ(提示クールダウンを考慮済み)を確認するのみ。

    判断根拠(B16のDB状態を書き換えない理由): B16の`last_surfaced_at`
    は、そのフラグの内容が実際にユーザーへの応答へ注入された時点で
    初めて更新されるべきものである(orchestrator/service.pyの応答経路、
    `_build_goal_alignment_context()`→`mark_pending_surfaced()`→
    `flush_pending_surfaced_flags()`という既存の流れ)。Goal Proposalは
    会話の外側で実行される(Executive Gateは会話ターンとは独立に呼ばれる
    想定)ため、ここで`last_surfaced_at`を更新してしまうと、実際にはまだ
    一言も話していないのに「もう提示済み」という誤った状態になり、
    本来ユーザーに届くはずだった次の自然な会話でのB16の言及がクール
    ダウンによって抑制されてしまう。そのため本関数は**読み取りのみ**を
    行い、「次の会話で自然に触れられる状態が既に整っている」ことを
    確認・記録するに留める——依頼書の「B16の既存の提示ロジックをトリガ
    ーする役割にとどめてよい」を、新しい書き込みを追加しない形で解釈
    した(判断根拠、レポート参照)。
    """
    flags = await get_active_goal_alignment_flags(limit=1)
    if not flags:
        return None
    flag = flags[0]
    goal_reference = flag.get("goal_reference") or "(不明な目標)"
    flag_statement = flag.get("flag_statement") or ""

    title = f"目標整合性への気づき: {goal_reference}"
    description = (
        f"目標『{goal_reference}』について気になる兆候がある({flag_statement})。"
        "次の自然な会話の流れの中で、控えめに触れる機会を待つ。"
    )
    context = {
        "flag_id": flag.get("id"),
        "goal_reference": goal_reference,
        "flag_statement": flag_statement,
        "evidence_count": flag.get("evidence_count"),
    }
    return _ActionOutcome(
        title=title, description=description, category="reflection", experience_type="unresolved", context=context
    )


def _format_mastery_lines(drive_state: DriveState) -> list[str]:
    mastery = drive_state.mastery
    lines: list[str] = []
    if mastery.rc1_eligible_completion_rate is not None and mastery.rc1_eligible_completion_rate < 0.8:
        lines.append(
            f"循環完了率(RC-1)が{mastery.rc1_eligible_completion_rate:.0%}に留まっている。"
            "ExperienceからMemoryへの到達を妨げている要因がないか確認したい。"
        )
    if mastery.rc2_score is not None and mastery.rc2_score < 0.8:
        lines.append(
            f"時間的一貫性(RC-2)が{mastery.rc2_score:.0%}まで低下している。"
            "chat_messagesの順序やevent記憶の整合性に問題が生じていないか調べたい。"
        )
    if mastery.rc5_status == "break_detected":
        broke = "、".join(mastery.rc5_broke_metrics) or "不明な指標"
        lines.append(f"循環の急激な悪化(RC-5)を検知している(対象: {broke})。優先的に原因を調べたい。")
    return lines


async def _act_on_mastery(jwt: str, drive_state: DriveState) -> _ActionOutcome | None:
    """Phase RのRC-1/RC-2/RC-5の生値から、改善したい点を言語化するのみ。

    判断根拠(LLM呼び出しをしない理由): 依頼書が「何を改善すべきかを
    言語化するところまで」と明示的にスコープを絞っており、Phase D
    (自己改良システム本体、未実装)への接続はまだ存在しない。既存の
    RC値を機械的に文章へ組み立てるだけの決定的なロジックであれば、
    新しいLLM呼び出し・プロンプト設計を追加せずに要件を満たせると判断
    した(要件「新しい検索ロジックを追加しない」の精神をLLM呼び出しにも
    適用した拡大解釈)。将来Phase Dへ接続する際、より自然な文章化が
    必要になった場合はLLM呼び出しへの置き換えを検討する余地がある。
    """
    mastery = drive_state.mastery
    if not mastery.has_data:
        return None
    lines = _format_mastery_lines(drive_state)
    if not lines:
        return None

    title = "循環健全性の改善提案"
    description = " ".join(lines)
    context = {
        "rc1_eligible_completion_rate": mastery.rc1_eligible_completion_rate,
        "rc2_score": mastery.rc2_score,
        "rc5_status": mastery.rc5_status,
        "rc5_broke_metrics": mastery.rc5_broke_metrics,
        "last_measured_at": mastery.last_measured_at,
    }
    return _ActionOutcome(
        title=title, description=description, category="proposal", experience_type="unresolved", context=context
    )


def _format_stale_facts(candidates: list[dict[str, Any]]) -> str:
    lines = [
        f"- {c.get('category')}/{c.get('key')}: {c.get('value')}(理由: {c.get('confirm_reason')})"
        for c in candidates[:_STALE_FACTS_LIMIT]
        if isinstance(c.get("category"), str) and isinstance(c.get("key"), str)
    ]
    return "\n".join(lines) if lines else "特になし"


def _format_unresolved_experiences(experiences: list[dict[str, Any]]) -> str:
    lines = [
        f"- {e.get('title')}: {(e.get('description') or '')[:150]}"
        for e in experiences
        if isinstance(e.get("title"), str)
    ]
    return "\n".join(lines) if lines else "特になし"


async def _act_on_knowledge_gap(jwt: str, drive_state: DriveState) -> _ActionOutcome | None:
    """既存のcuriosity_engine.generate_curiosity_queries()を、B3(stale
    facts)・B2(unresolved experiences)・B1関連(facts summary)の既存
    データで呼び出す。generate_curiosity_queries()自体が内部で
    enqueue_curiosity()を呼び、sigmaris_curiosity_queueへの追加まで
    完結させる(既存の日次6:15ジョブが後で実際の検索を実行する)。

    判断根拠(ここで検索を同期実行しない理由): 依頼書「curiosity_
    engine.pyの外部Web検索の仕組みは、そのまま活用してよい。新しい
    検索ロジックを追加しないこと」に従い、"行動"の内容を「意味のある
    調査クエリをキューへ追加すること」までとし、実際のHackerNews/arXiv
    検索(research_agent.run_research_for_query())は、既存の日次バッチが
    引き続き担当する形にした——Executive Gateがトリガーする経路に、
    重い同期的な外部HTTP呼び出しを新規に持ち込まないための判断。

    facts_summary/unresolved/stale_factsの対応関係(glossary_curiosity.
    md 11.2節の設計方針をそのまま実装):
      - stale_facts ← KnowledgeGapDrive.confirm_candidates(B3、本タスクで
        drive_system.pyに追加したフィールド)
      - unresolved ← experience_layer.get_recent_experiences(B2、
        experience_type="unresolved")
      - facts_summary ← user_fact_data.build_facts_context(B1、既存の
        プロンプト注入用フォーマッタをそのまま再利用)
    """
    knowledge_gap = drive_state.knowledge_gap
    if knowledge_gap.candidate_count == 0:
        return None

    stale_facts = _format_stale_facts(knowledge_gap.confirm_candidates)

    try:
        unresolved_experiences = await get_recent_experiences(
            limit=_UNRESOLVED_EXPERIENCES_LIMIT, experience_type="unresolved"
        )
    except Exception:
        unresolved_experiences = []
    unresolved = _format_unresolved_experiences(unresolved_experiences)

    try:
        active_facts = await get_fact_items(jwt, active_only=True)
    except Exception:
        active_facts = []
    facts_summary = build_facts_context(active_facts) or "特になし"

    queries = await generate_curiosity_queries(
        facts_summary=facts_summary, unresolved=unresolved, stale_facts=stale_facts
    )
    if not queries:
        return None

    query_texts = [q.get("query", "") for q in queries if isinstance(q, dict) and q.get("query")]
    title = "好奇心駆動の調査クエリを生成"
    description = f"未解決の知識ギャップから{len(query_texts)}件の調査クエリを生成しキューへ追加した: {'; '.join(query_texts)}"
    context = {
        "queries": queries,
        "stale_facts_considered": min(knowledge_gap.confirmation_candidate_count, _STALE_FACTS_LIMIT),
        "unresolved_experiences_considered": len(unresolved_experiences),
    }
    return _ActionOutcome(
        title=title, description=description, category="research", experience_type="unresolved", context=context
    )


_ACTIONS = {
    "coherence": _act_on_coherence,
    "mastery": _act_on_mastery,
    "knowledge_gap": _act_on_knowledge_gap,
}


async def propose_and_act(jwt: str, gate_result: ExecutiveGateResult) -> GoalProposalResult | None:
    """S-1のExecutive Gateの判定結果を受け取り、1つの行動を選んで実行する。

    Autotelic Loop(複数Driveの優先順位付け): `_DRIVE_PRIORITY`の順に
    `gate_result.triggering_drives`を確認し、**最初に実際の行動が生成
    できたDrive**を採用する(依頼書「1回のGoal Proposalでは1つの行動に
    絞ること」への対応)。優先度が高いDriveが閾値を超えていても、その場に
    具体的に提案できる内容が無い場合(例: Coherenceが閾値を超えていても
    現在提示可能なフラグが無い)は、次点のDriveへフォールバックする——
    「優先度が高いのに何も提案できない」ことを、そのまま「今回は何も
    しない」に短絡させないための設計判断。全てのtriggering_drivesで
    行動が生成できなければNoneを返す(これ自体は異常ではない、レポート
    参照)。

    gate_result.may_speak=Falseの場合、またはdrive_stateが未取得(絶対
    制約で却下された場合)は、呼び出し側の誤用を防ぐため即座にNoneを返す。
    """
    if not gate_result.may_speak or gate_result.drive_state is None:
        return None

    ordered_drives = [d for d in _DRIVE_PRIORITY if d in gate_result.triggering_drives]
    for drive_name in ordered_drives:
        action_fn = _ACTIONS[drive_name]
        try:
            outcome = await action_fn(jwt, gate_result.drive_state)
        except Exception:
            logger.exception("goal_proposal: action failed for drive=%s", drive_name)
            continue
        if outcome is None:
            continue

        experience_id = await record_experience(
            experience_type=outcome.experience_type,
            category=outcome.category,
            title=outcome.title,
            description=outcome.description,
            context=outcome.context,
        )
        return GoalProposalResult(
            drive=drive_name,
            title=outcome.title,
            description=outcome.description,
            experience_id=experience_id,
            details=outcome.context,
        )

    return None
