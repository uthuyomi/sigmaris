# 役割: Phase G-3(Self-Critique検証、docs/sigmaris/phase_g_report.md)—
# G-2が生成した構造化された証拠(Evidence)と、実際に生成された応答が
# 矛盾していないかを、生成とは独立した視点(別のプロンプト、同じnano-tier
# だが「批評家」という別の役割)で検証する。矛盾が見つかった場合は、既存の
# B11(校正された放棄判定、memory_confidence.py)の確信度階層とヘッジ文言
# を再利用して、該当箇所だけをヘッジ表現へ書き換える。
#
# 【重要】Evidenceが存在しない(needs_search=falseだった)通常の会話には、
# この関数群は一切呼ばれない——呼び出し側(chat.py)がevidenceの有無で
# 完全にスキップする(要件5)。
#
# 【重要な設計判断】ストリーミング経路(stream_chat_completion_ui)では、
# この検証結果を使って既に送信済みの応答テキストを書き換えることをしない。
# BA4 追補8(docs/sigmaris/phase_ba4_report.md 8章)が、生成中の無音時間
# (deltaが出ない待ち時間)がフロントエンド側で「assistant枠だけ出て本文が
# 出ない」バグを引き起こすことを実際に確認し、"表示前にブロックする"設計
# から"即時中継+事後のadvisory検知"設計へ切り替えた、という直接の前例が
# ある。本タスクの検証(+必要ならヘッジ書き換え)は、Evidenceがある場合に
# 限っても、批評+書き換えで追加のLLM呼び出しが2回発生しうる(5章のレイ
# テンシ見積もり参照)——これをストリーミング完了後・応答送信前の同期処理
# として挟むことは、8章と同種の無音時間バグを再発させるリスクが高いと判断
# した。そのため、実際の応答書き換え(要件4)はrun_chat_completion()
# (非ストリーミング経路)にのみ適用し、stream_chat_completion_ui()側では
# response_guard.compare_response_to_tool_outputs()と同じ
# advisory-only(検知してログに残すのみ、応答は変更しない)の扱いとした。
# 判断根拠の全文はphase_g_report.mdのPhase G-3節を参照。

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_confidence import ConfidenceTier, confidence_guidance_note

logger = logging.getLogger(__name__)

CritiqueVerdict = Literal["no_contradiction", "minor_mismatch", "clear_contradiction"]

_VALID_VERDICTS: frozenset[str] = frozenset({"no_contradiction", "minor_mismatch", "clear_contradiction"})

_CRITIC_SYSTEM = (
    "あなたはシグマリスの応答を検証する、独立した批評家です。"
    "応答の内容が、与えられたEvidence(検索で確認された事実)と矛盾していないか"
    "だけを判定してください。文体・説明の質・Evidenceと無関係な内容は一切"
    "評価しないでください。必ず有効なJSONのみを返してください。"
)

# 長い応答が丸ごとプロンプトに乗ることを避けるための上限。批評は「矛盾の
# 有無」の判定であり、応答全文を精読する必要はない——依頼書「Evidenceに
# 関連する主張の部分だけを対象とすること。過剰に広い範囲を検証しない」
# への対応でもある。
_MAX_RESPONSE_CHARS_FOR_CRITIQUE = 2000


def _build_critique_prompt(response_text: str, evidence: list[dict[str, Any]]) -> str:
    evidence_lines = "\n".join(
        f"- {item['claim']}(出典: {item['source_title']})" for item in evidence
    )
    return (
        "以下のEvidence(検索で確認された事実)と、実際に生成された応答を比較してください。\n\n"
        f"## Evidence\n{evidence_lines}\n\n"
        f"## 応答内容\n{response_text[:_MAX_RESPONSE_CHARS_FOR_CRITIQUE]}\n\n"
        "応答が、Evidenceの内容と矛盾していないかだけを判定してください。"
        "Evidenceに無い話題への言及は矛盾とみなさないでください(Evidence以外の"
        "話題は検証対象外です)。\n\n"
        "JSON形式で返してください: "
        '{"verdict": "no_contradiction"|"minor_mismatch"|"clear_contradiction", '
        '"conflicting_claim": "矛盾するEvidenceのclaim(あれば、無ければnull)", '
        '"reason": "簡潔な理由(1文)"}'
    )


async def critique_response(
    response_text: str, evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """応答とEvidenceを比較し、{"verdict", "conflicting_claim", "reason"}を
    返す。nano-tier(TaskType.SELF_CRITIQUE)の1回のLLM呼び出しのみ。

    Evidenceが空、または応答が空文字の場合は、LLMを呼ばず即座に
    "no_contradiction"を返す(呼び出し側は既にevidenceの有無でこの関数
    自体をスキップする設計だが、この関数単体で呼ばれても安全なように
    防御的に同じ判定をここでも行う)。

    判断根拠(失敗時にno_contradiction側へ縮退する設計、fail-open):
    このコードベース全体で一貫した「補助処理の失敗が主応答を壊さない」
    という設計方針(chat.py::_persist_chat_messages_safely()等)を踏襲した。
    批評自体が失敗した場合、安全側に倒すなら本来"clear_contradiction"扱い
    にして強制的にヘッジすべきという考え方もありうるが、批評の失敗
    (ネットワークエラー等)は応答内容の信頼性そのものとは無関係であり、
    毎回の一時的なAPI障害で正常な応答まで不必要にヘッジしてしまう方が、
    ユーザー体験として悪化すると判断した。
    """
    if not evidence or not response_text.strip():
        return {"verdict": "no_contradiction", "conflicting_claim": None, "reason": "no-evidence-or-empty-response"}

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_CRITIQUE,
            [
                {"role": "system", "content": _CRITIC_SYSTEM},
                {"role": "user", "content": _build_critique_prompt(response_text, evidence)},
            ],
            temperature=0.1,
            max_tokens=300,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception:
        logger.exception("self_critique: critique_response failed")
        return {"verdict": "no_contradiction", "conflicting_claim": None, "reason": "critique-call-failed"}

    verdict = parsed.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "no_contradiction"
    return {
        "verdict": verdict,
        "conflicting_claim": parsed.get("conflicting_claim"),
        "reason": str(parsed.get("reason") or ""),
    }


def _confidence_tier_for_verdict(verdict: str) -> ConfidenceTier:
    """G-3の3区分を、B11(memory_confidence.py)の確信度階層へ写像する。

    判断根拠: "clear_contradiction"(明確な矛盾)は、実際に検索で確認した
    事実と食い違っているという意味で、B11の"no_evidence"(根拠となる記憶が
    無い、断定を避けるべき)より踏み込んだ、より強い注意が必要な状態だが、
    B11には3階層(confident/low_confidence/no_evidence)しか無く、
    "no_evidence"が最も慎重な既存の階層であるため、それをそのまま流用した。
    "minor_mismatch"(軽微な不一致)は、B11の"low_confidence"(ヘッジは
    必要だが断定を避けるだけでよい)に対応させた。
    """
    if verdict == "clear_contradiction":
        return "no_evidence"
    if verdict == "minor_mismatch":
        return "low_confidence"
    return "confident"


_REWRITE_SYSTEM = (
    "あなたはシグマリスの応答を修正するアシスタントです。"
    "指示された確信度の伝え方にだけ従い、必要最小限の修正を加えてください。"
    "矛盾が指摘された箇所だけをヘッジ表現に書き換え、それ以外の文章・"
    "話題・言い回しは変更しないでください。修正後の応答全文をそのまま"
    "出力してください(前置き・説明は不要です)。"
)


def _build_rewrite_prompt(response_text: str, critique: dict[str, Any], guidance: str) -> str:
    conflicting = critique.get("conflicting_claim") or "(特定の主張は指摘されていません)"
    return (
        f"## 元の応答\n{response_text}\n\n"
        f"## 矛盾の指摘\n{critique.get('reason') or ''}\n"
        f"該当するEvidence: {conflicting}\n\n"
        f"## 確信度の伝え方の指示\n{guidance}\n\n"
        "上記の指示に従い、矛盾が指摘された箇所だけをヘッジ表現に書き換えた、"
        "応答全文を出力してください。"
    )


async def apply_hedge_if_needed(
    response_text: str, critique: dict[str, Any]
) -> tuple[str, bool]:
    """critique_response()の結果に応じて、必要ならB11のヘッジ文言指示を
    使った書き換えを行う。戻り値は(最終的なテキスト, 書き換えが行われたか)。

    "no_contradiction"の場合は、LLMを呼ばず即座に元のテキストをそのまま
    返す(要件1: Evidenceが無い/矛盾が無いターンには一切のオーバーヘッド
    を加えない、という原則をここでも徹底する)。

    判断根拠(全文再生成ではなく、既存応答の"最小限の書き換え"にした理由):
    依頼書「全文の再生成は最終手段とすること。まずB11のヘッジ表現への
    切り替えを優先すること」に対応。generate_curiosity_queries()的な
    ゼロからの再生成ではなく、既存の応答テキストを入力として与え、
    「矛盾箇所だけ直す」という制約付きの書き換えにすることで、(a) 出力
    トークン数を元の応答とほぼ同程度に抑えられる(ゼロから考え直すより
    速い)、(b) 応答の他の部分(Evidenceと無関係な話題)を保持できる、
    という2点を狙った設計である。
    """
    verdict = critique.get("verdict")
    if verdict == "no_contradiction" or not verdict:
        return response_text, False

    tier = _confidence_tier_for_verdict(verdict)
    guidance = confidence_guidance_note(tier)
    if not guidance:
        return response_text, False

    try:
        router = get_llm_router()
        rewritten = await router.chat(
            TaskType.SELF_CRITIQUE,
            [
                {"role": "system", "content": _REWRITE_SYSTEM},
                {"role": "user", "content": _build_rewrite_prompt(response_text, critique, guidance)},
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        rewritten = (rewritten or "").strip()
    except Exception:
        logger.exception("self_critique: apply_hedge_if_needed rewrite failed")
        return response_text, False

    # 書き換え後のテキストが極端に短い(壊れた・切り詰められた出力の疑い)
    # 場合は、元の応答を保持する——「ヘッジに失敗して沈黙するより、断定的
    # だが完全な応答を保つ方が安全」という判断ではなく、単純に、書き換え
    # 自体が失敗した(空・大幅欠落)兆候を検知した場合は、失敗として扱う
    # という防御。
    if not rewritten or len(rewritten) < max(20, len(response_text) // 5):
        logger.warning("self_critique: rewrite output looked truncated/empty, keeping original response")
        return response_text, False

    return rewritten, True
