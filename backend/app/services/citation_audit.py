# 役割: Phase G-4(Two-Layer Citation Audit、docs/sigmaris/phase_g_report.md)
# — 二段階の引用監査のうち、2段階目(claim単位で、生成応答がその主張を
# 忠実に使っているか)を実装する。1段階目(情報源URLが実在するか)は、G-2
# が既にAPIの実引用のみをclaimの出典として使う設計(evidence_search.py::
# structure_evidence()、LLMにURLを生成させない)により、構造的に保証済み
# であり、本タスクでは一切手を加えない。
#
# 【G-3(self_critique.py)との役割分担、依頼書「G-3と重複しない範囲に
# 絞ること」への対応】
#   - G-3(critique_response): 応答"全体"が、Evidence"全体"と矛盾していない
#     かを判定する、粗い粒度のチェック。
#   - G-4(本モジュール、audit_citation_usage): Evidenceの各claim"個別"に
#     ついて、応答の中でその主張が"どう使われているか"(直接引用/要約/
#     間接的反映/未使用)を確認し、使われ方がclaim自体の内容を歪めていない
#     か(誇張・意味の取り違え・文脈からの逸脱)だけを判定する、細かい
#     粒度のチェック。応答全体の真偽判定はG-3の役割であり、本モジュールの
#     プロンプトは明示的にそれを評価対象から除外する。
#
# 新しいモデル階層は追加していない——TaskType.CITATION_AUDITもnano-tierで
# あり、G-3のTaskType.SELF_CRITIQUEと同じ枠組み(local_llm.pyのnano階層
# ルーティング)を拡張しただけである。

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_confidence import confidence_guidance_note
from app.services.self_critique import (
    _confidence_tier_for_verdict,
    critique_response,
    rewrite_response_with_guidance,
)
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

ClaimUsage = Literal["not_used", "faithful", "distorted"]

_VALID_USAGES: frozenset[str] = frozenset({"not_used", "faithful", "distorted"})

_TABLE = "sigmaris_citation_audit_log"

# claim件数が多いターンでもプロンプトサイズ・レイテンシが青天井にならない
# ようにする上限。G-2のstructure_evidence()は通常1〜数件のclaimしか生成
# しないため、実運用でこの上限に達することは稀と見込む。
_MAX_CLAIMS_FOR_AUDIT = 10

_AUDIT_SYSTEM = (
    "あなたはシグマリスの引用監査の専門家です。各claim(検索で確認された"
    "事実)が、応答の中でどう使われているか(直接引用/要約/間接的反映/未"
    "使用)を確認し、その使われ方がclaim自体の内容を正確に反映しているか"
    "(誇張・意味の取り違え・文脈からの逸脱が無いか)だけを判定してくださ"
    "い。**応答全体が正しいかどうかは評価対象外です**(それは別の検証で"
    "既に行われています)。必ず有効なJSONのみを返してください。"
)


def _build_audit_prompt(response_text: str, evidence: list[dict[str, Any]]) -> str:
    claims = evidence[:_MAX_CLAIMS_FOR_AUDIT]
    numbered = "\n".join(f"[{i}] {item['claim']}" for i, item in enumerate(claims, start=1))
    return (
        f"## Evidence(検索で確認されたclaim一覧)\n{numbered}\n\n"
        f"## 応答内容\n{response_text[:2000]}\n\n"
        "各claimについて、応答の中での使われ方を判定してください。\n"
        "- not_used: 応答内でこのclaimに触れていない\n"
        "- faithful: claimの内容を正確に反映して使っている(直接引用・"
        "要約・間接的反映のいずれでもよい)\n"
        "- distorted: claimに触れてはいるが、誇張・意味の取り違え・文脈"
        "からの逸脱がある\n\n"
        "JSON形式で返してください: "
        '{"items": [{"claim_index": 1, "usage": "not_used"|"faithful"|"distorted", "note": "簡潔な理由(1文)"}, ...]}\n'
        "全てのclaimについて1件ずつ返してください。"
    )


async def audit_citation_usage(
    response_text: str, evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """claim単位の使われ方監査。nano-tier(TaskType.CITATION_AUDIT)の
    1回のLLM呼び出しで、evidence内の全claimをまとめて判定する
    (claim件数ぶんの個別呼び出しをしない——レイテンシへの配慮)。

    戻り値は、evidenceの各要素へ"usage"/"note"を追加したリスト
    (claim・source_url・source_title・retrieved_atは元のevidenceの値を
    そのまま保持する——source_url/source_titleをLLMに再生成させない、
    という evidence_search.py::structure_evidence() のグラウンディング
    安全設計を、ここでも踏襲する)。

    Evidenceが空、または応答が空文字の場合は、LLMを呼ばず即座に空リスト
    を返す(要件6)。判定失敗時も、個々のclaimを安全側(not_used)へ
    縮退させたリストを返す——G-3と同じfail-open方針。
    """
    if not evidence or not response_text.strip():
        return []

    claims = evidence[:_MAX_CLAIMS_FOR_AUDIT]
    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.CITATION_AUDIT,
            [
                {"role": "system", "content": _AUDIT_SYSTEM},
                {"role": "user", "content": _build_audit_prompt(response_text, claims)},
            ],
            temperature=0.1,
            max_tokens=600,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
    except Exception:
        logger.exception("citation_audit: audit_citation_usage failed")
        items = []

    usage_by_index: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("claim_index")
        if not isinstance(index, int) or not (1 <= index <= len(claims)):
            continue
        usage = item.get("usage")
        if usage not in _VALID_USAGES:
            usage = "not_used"
        usage_by_index[index] = {"usage": usage, "note": str(item.get("note") or "")}

    results: list[dict[str, Any]] = []
    for i, claim in enumerate(claims, start=1):
        verdict = usage_by_index.get(i, {"usage": "not_used", "note": "audit-unavailable"})
        results.append({**claim, "usage": verdict["usage"], "note": verdict["note"]})
    return results


# Phase G-4の「Abstention連携の仕上げ」: 情報源は実在する(G-2で確認済み)
# が、応答がその内容を歪めて使っている場合の専用ノート。B11
# (memory_confidence.py)の既存ノートは「記憶が無い/薄い」という前提の
# 文言であり、「情報源はあるが使い方が不正確」という本ケースにはそのまま
# 当てはまらないため、B11と同じ短い指示文というパターンを踏襲しつつ、
# 依頼書が例示した言い回し(「情報源はありますが、断定はできません」)に
# 沿った専用の文言を新設した。memory_confidence.py自体は変更していない。
_CITATION_MISMATCH_NOTE = (
    "[引用の確認結果に関する注意]\n"
    "検索で確認した情報源は実在しますが、その内容を十分に裏付けているとは"
    "言えない使い方をしている箇所があります。「情報源はありますが、断定は"
    "できません」「確認できた範囲では、というのが正直なところです」のよう"
    "に、断定を避け、正直に伝えてください。"
)


def select_guidance_note(
    critique: dict[str, Any], audit_results: list[dict[str, Any]]
) -> str | None:
    """G-3の検証結果(critique)とG-4の監査結果(audit_results)を統合し、
    書き換えに使うガイダンス文言を1つ選ぶ。

    判断根拠(優先順位): G-3が既に矛盾(no_contradiction以外)を検出して
    いる場合は、そちらのB11階層マッピングを優先する——応答全体の矛盾の
    方が、個別claimの使い方の粗さより深刻な問題である可能性が高いと判断
    した。G-3が「矛盾なし」と判定していても、G-4がclaim単位で"distorted"
    を1件でも検出していれば、本モジュール専用のノートを使う——これが
    まさに依頼書が想定する「claim自体は実在する情報だが、生成応答が、
    そのclaimを文脈から外れた形で使っている」ケースであり、G-3の粗い
    チェックでは見逃されうる、G-4固有の検出対象である。
    """
    verdict = critique.get("verdict")
    if verdict and verdict != "no_contradiction":
        tier = _confidence_tier_for_verdict(verdict)
        note = confidence_guidance_note(tier)
        if note:
            return note

    if any(item.get("usage") == "distorted" for item in audit_results):
        return _CITATION_MISMATCH_NOTE

    return None


async def finalize_response_with_citation_audit(
    response_text: str,
    evidence: list[dict[str, Any]],
    critique: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], bool]:
    """G-4の非ストリーミング経路向けの入口。claim単位監査を実行し、G-3の
    critiqueと統合したうえで、必要なら(最大1回の)書き換えを行う。

    戻り値は(最終的な応答テキスト, 監査結果のリスト, 書き換えが行われたか)。
    G-3とG-4のどちらか一方、または両方が問題を検出した場合でも、書き換え
    LLM呼び出しは合計1回のみに抑えている(select_guidance_note()が1つの
    ガイダンスへ統合するため)——依頼書「G-3と重複する範囲を二重に実装
    しないこと」を、書き換え呼び出しの回数という観点でも徹底した。
    """
    audit_results = await audit_citation_usage(response_text, evidence)
    guidance = select_guidance_note(critique, audit_results)
    if not guidance:
        return response_text, audit_results, False

    rewritten, was_rewritten = await rewrite_response_with_guidance(
        response_text,
        guidance,
        reason=str(critique.get("reason") or ""),
        conflicting_claim=critique.get("conflicting_claim"),
    )
    return rewritten, audit_results, was_rewritten


async def run_verification_checks(
    response_text: str, evidence: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """G-3のcritique_response()とG-4のaudit_citation_usage()は互いの結果
    に依存しない独立した判定であるため、順にawaitするのではなく
    asyncio.gather()で並行実行する——依頼書のレイテンシへの配慮に対応
    した、本タスクで追加した最適化である(5章のレイテンシ見積もり参照)。

    戻り値は(critique, audit_results)のみで、書き換えは行わない。
    書き換え判断まで必要な呼び出し元はverify_response()を使うこと——
    ストリーミング経路のadvisory-onlyロギング(書き換え結果を一切使わ
    ない)のような、検証結果だけが欲しい呼び出し元は、無駄な書き換え
    LLM呼び出しを避けるため、こちらを直接使う。
    """
    critique, audit_results = await asyncio.gather(
        critique_response(response_text, evidence),
        audit_citation_usage(response_text, evidence),
    )
    return critique, audit_results


async def verify_response(
    response_text: str, evidence: list[dict[str, Any]]
) -> tuple[str, dict[str, Any], list[dict[str, Any]], bool]:
    """Phase G-3+G-4の統合入口(書き換えまで行う、非ストリーミング経路
    向け)。戻り値は(最終的な応答テキスト, G-3のcritique, G-4の
    audit_results, 書き換えが行われたか)。"""
    critique, audit_results = await run_verification_checks(response_text, evidence)

    guidance = select_guidance_note(critique, audit_results)
    if not guidance:
        return response_text, critique, audit_results, False

    rewritten, was_rewritten = await rewrite_response_with_guidance(
        response_text,
        guidance,
        reason=str(critique.get("reason") or ""),
        conflicting_claim=critique.get("conflicting_claim"),
    )
    return rewritten, critique, audit_results, was_rewritten


def _svc_headers(*, prefer: str | None = None) -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    h: dict[str, str] = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


async def persist_citation_audit(
    *,
    thread_id: str | None,
    audit_results: list[dict[str, Any]],
    critique_verdict: str | None,
) -> None:
    """G-5(継続的な精度測定、本タスクでは未実装)が後から集計できるよう、
    claim単位の監査結果をsigmaris_citation_audit_logへ書き込む
    (要件4)。curiosity_engine.py::enqueue_curiosity()と同じサービス
    ロールキー経由の書き込みパターン(このテーブルはSigmaris自身の内部
    検証データであり、ユーザー所有のコンテンツではないため、chat_messages
    のようなJWTスコープのRLSではなく、既存のsigmaris_decision_log等と同じ
    service_role_onlyパターンを踏襲した)。

    書き込み失敗は例外を伝播させない(観測用データの欠落は許容できるが、
    その失敗で応答生成自体を壊してはならない、というこのコードベース
    一貫の方針)。監査結果が空の場合は何もしない(呼び出し不要)。
    """
    if not audit_results:
        return
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        payload = [
            {
                "thread_id": thread_id,
                "claim": item.get("claim", ""),
                "source_url": item.get("source_url", ""),
                "source_title": item.get("source_title"),
                "usage": item.get("usage", "not_used"),
                "note": item.get("note"),
                "critique_verdict": critique_verdict,
            }
            for item in audit_results
        ]
        r = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=minimal"),
            json=payload,
        )
        r.raise_for_status()
    except Exception:
        logger.exception("citation_audit: persist_citation_audit failed")
