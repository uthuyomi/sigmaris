# 役割: Phase G-2(Grounding, docs/sigmaris/phase_g_report.md)— G-1が
# needs_search=trueと判定した質問に対して、実際にWeb検索を実行し、結果を
# "claim(主張)・source_url・source_title・retrieved_at"という構造化された
# 証拠(Evidence)に変換する。
#
# 【重要】既存のcuriosity_engine.py/research_agent.pyの検索の仕組みは、
# 本タスクでは再利用していない——理由はdocs/sigmaris/phase_g_report.mdの
# 「既存資産の再利用検討」節に詳しいが、要点は以下の通り:
#   - research_agent.run_research_for_query()は、HackerNews(トップ
#     ストーリー)とarXiv(cs.AI/cs.LG/cs.RO/cs.NC論文)という、AI/ML技術
#     ニュース・論文に特化した2つの固定ソースだけを取得し、クエリの単語が
#     タイトル・要約に含まれるかをフィルタするだけで、任意のキーワードで
#     実際にWeb検索するわけではない
#   - 「iPhoneの価格」のような一般的な製品・価格の質問は、この2ソースの
#     いずれにも実質的に存在しないため、検索してもほぼ確実に0件になる
#   - 上記の設計は「シグマリス自身の関心軸に沿った探索」という
#     curiosity research queue(用語集参照)の目的には適しているが、
#     「ユーザーの質問に答えるための汎用グラウンディング」という本タスク
#     の目的とは根本的に別物であり、拡張よりも別実装が適切と判断した
#
# 代わりに、OpenAI Responses APIが標準で提供するweb_searchツールを使う。
# 新しい外部API・APIキーを追加する必要がない(既存のOPENAI_API_KEYのみで
# 動作する)、かつ引用(annotations、url_citation)がAPIレスポンスに含まれる
# ため、claimの出典(URL・タイトル)をLLMに再生成させず、APIが返した値を
# そのまま使える——ハルシネーションのリスクを構造的に減らせる設計である。

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router

logger = logging.getLogger(__name__)

# 同一プロセス内でAsyncOpenAIクライアントを使い回す(chat.py::_require_
# openai_client()・memory_search.pyの既存パターンと同じ理由: ターンごとに
# 新規クライアントを作るとTCP/TLSの再接続コストがかかる。ただしこのモジュール
# は検索が必要と判定された時のみ呼ばれる低頻度経路のため、影響は軽微)。
_openai_client: AsyncOpenAI | None = None


def _require_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for backend.")
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _build_search_prompt(user_question: str, search_signal: dict[str, Any]) -> str:
    """G-1が返した判定根拠(reasons)を踏まえてクエリ用プロンプトを整形する
    (依頼書「元の質問文をそのまま使うのではなく」への対応)。web_search
    ツールは自由記述のプロンプトに対して動作するため、検索エンジン向けの
    キーワード列ではなく、何を優先して調べるべきかを明示する指示文として
    整形する。"""
    reasons: list[str] = search_signal.get("reasons") or []
    hints: list[str] = []
    if any(r.startswith("freshness_keyword:") for r in reasons):
        hints.append("この質問は情報の鮮度が重要です。最新の情報源を優先してください。")
    if any(r.startswith("volatile_fact_keyword:") for r in reasons):
        hints.append("価格・スペック・在庫等、変動しうる具体的な事実を確認してください。")
    if any(r == "proper_noun_or_model_number" for r in reasons):
        hints.append("特定の製品・型番について、公式または信頼できる情報源を優先してください。")
    hint_block = "\n".join(hints)

    return (
        "次の質問について、Web検索を使って最新かつ正確な情報を調べてください。\n\n"
        f"質問: {user_question}\n\n"
        + (f"{hint_block}\n\n" if hint_block else "")
        + "調べた内容を、日本語で簡潔にまとめてください。"
    )


async def run_web_search(query_prompt: str) -> tuple[str, list[dict[str, Any]]] | None:
    """OpenAI Responses APIをweb_searchツール付きで1回呼び出し、
    (output_text, citations)を返す。citationsは
    [{"title", "url", "start_index", "end_index"}, ...]。

    失敗時はNoneを返す(例外を伝播させない) —— 検索はあくまで補助的な
    グラウンディング手段であり、失敗しても既存の応答生成自体を止めては
    ならない(chat.py::_persist_chat_messages_safely()等、このコード
    ベース全体で一貫した「補助処理の失敗でメイン応答を壊さない」設計)。

    判断根拠(nano-tierではなくsettings.openai_modelを使う理由):
    web_searchツールはResponses API専用の機能であり、このコードベースの
    nano階層ルーティング(local_llm.pyのTaskType/LLMRouter)は
    Chat Completions APIのみを経由する(_OpenAIAdapter.chat()参照)ため、
    nano階層へ安全に委譲できない。BA4のメイン応答生成(chat.py)が既に
    settings.openai_modelでResponses APIのtool呼び出しを行っている実績が
    あるため、同じモデル階層を踏襲した——依頼書は構造化(structure_
    evidence())についてのみnano-tierを明示的に要求しており、検索実行
    そのものの階層までは指定していない。
    """
    try:
        client = _require_openai_client()
        response = await client.responses.create(
            model=settings.openai_model,
            input=query_prompt,
            tools=[{"type": "web_search", "search_context_size": "low"}],
        )
    except Exception:
        logger.exception("evidence_search: web search call failed")
        return None

    output_text = getattr(response, "output_text", "") or ""
    citations: list[dict[str, Any]] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) != "output_text":
                continue
            for annotation in getattr(part, "annotations", None) or []:
                if getattr(annotation, "type", None) != "url_citation":
                    continue
                citations.append(
                    {
                        "title": getattr(annotation, "title", "") or "",
                        "url": getattr(annotation, "url", "") or "",
                        "start_index": getattr(annotation, "start_index", None),
                        "end_index": getattr(annotation, "end_index", None),
                    }
                )
    return output_text, citations


def _extract_cited_spans(output_text: str, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """引用(citation)のインデックス範囲だけをoutput_textから切り出す。
    citationを一切持たない応答(web_searchが実際には検索しなかった、
    または出典を明示しなかった場合)からは、根拠のない文をEvidenceに
    混入させないため、何も抽出しない(空リストを返す)。"""
    spans: list[dict[str, Any]] = []
    length = len(output_text)
    for citation in citations:
        start, end = citation.get("start_index"), citation.get("end_index")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < 0 or end > length or start >= end:
            continue
        text = output_text[start:end].strip()
        if not text:
            continue
        spans.append({"title": citation.get("title") or "", "url": citation.get("url") or "", "text": text})
    return spans


_STRUCTURE_SYSTEM = (
    "あなたはシグマリスの検索結果構造化システムです。"
    "与えられた引用済みテキストから、簡潔な主張(claim)のみを抽出します。"
    "必ず有効なJSONのみを返してください。"
)


def _build_structure_prompt(spans: list[dict[str, Any]]) -> str:
    blocks = [
        f"[{i}] 出典: {span['title']}\n{span['text'][:800]}" for i, span in enumerate(spans, start=1)
    ]
    joined = "\n\n".join(blocks)
    return (
        "以下は実際のWeb検索から得られた、出典付きの引用済みテキストです。\n"
        "各項目について、そこから読み取れる具体的な主張(claim)を1件以上、"
        "簡潔な日本語の文で抽出してください。原文の長い引用や転記は避け、"
        "要点を抽出・要約した文にしてください。読み取れる主張が無い項目は、"
        "claimsを空配列にしてください。\n\n"
        f"{joined}\n\n"
        'JSON形式で返してください: {"items": [{"source_index": 1, "claims": ["...", "..."]}, ...]}'
    )


async def structure_evidence(
    spans: list[dict[str, Any]], *, retrieved_at: str
) -> list[dict[str, Any]]:
    """nano-tier(TaskType.EVIDENCE_STRUCTURING)のLLM呼び出しで、引用済み
    テキストから簡潔なclaimを抽出する。

    判断根拠(source_url/source_titleをLLMに生成させない設計): claimの
    テキストのみをLLMに生成させ、source_index経由でspans(APIが実際に
    返したurl_citationそのもの)からsource_url/source_titleを機械的に
    引き当てる。LLMにURL文字列を自由に出力させると、実在しないURLや
    誤字を生成するリスクがある——出典情報は常にOpenAI APIが実際に返した
    値のみを使うことで、この経路を構造的に排除している。
    """
    if not spans:
        return []
    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.EVIDENCE_STRUCTURING,
            [
                {"role": "system", "content": _STRUCTURE_SYSTEM},
                {"role": "user", "content": _build_structure_prompt(spans)},
            ],
            temperature=0.1,
            max_tokens=600,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        items = parsed.get("items", []) if isinstance(parsed, dict) else []
    except Exception:
        logger.exception("evidence_search: structuring failed")
        return []

    evidence: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("source_index")
        if not isinstance(index, int) or not (1 <= index <= len(spans)):
            continue
        span = spans[index - 1]
        claims = item.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            claim_text = str(claim).strip()
            if not claim_text:
                continue
            evidence.append(
                {
                    "claim": claim_text,
                    "source_url": span["url"],
                    "source_title": span["title"],
                    "retrieved_at": retrieved_at,
                }
            )
    return evidence


def build_evidence_context(evidence: list[dict[str, Any]]) -> str | None:
    """構造化された証拠を、応答生成プロンプトへ注入するテキストブロックへ
    整形する。Noneを返した場合は呼び出し側が何も追加しない(既存のプロン
    プト構造を変えない)。"""
    if not evidence:
        return None
    lines = ["[検索で確認した情報(参考情報、出典付き)]"]
    for item in evidence:
        lines.append(f"- {item['claim']}(出典: {item['source_title']} {item['source_url']})")
    lines.append(
        "上記は実際にWeb検索で確認した、出典付きの情報です。関連する場合は活用し、"
        "出典に基づかない推測とは明確に区別してください。"
    )
    return "\n".join(lines)


async def gather_search_evidence(
    *, user_question: str, search_signal: dict[str, Any]
) -> list[dict[str, Any]]:
    """G-2のトップレベルの入口。needs_search=falseの場合は何もしない
    (I/O・LLM呼び出しなしで即座に空リストを返す)。例外は一切伝播させず、
    失敗時は空リストへ縮退する——検索の失敗が既存の応答生成を止めては
    ならないという、このモジュール全体の設計方針を、この関数自身でも
    最終防波堤として保証する。"""
    if not search_signal.get("needs_search"):
        return []
    question = user_question.strip()
    if not question:
        return []
    try:
        prompt = _build_search_prompt(question, search_signal)
        result = await run_web_search(prompt)
        if result is None:
            return []
        output_text, citations = result
        retrieved_at = datetime.now(UTC).isoformat()
        spans = _extract_cited_spans(output_text, citations)
        return await structure_evidence(spans, retrieved_at=retrieved_at)
    except Exception:
        logger.exception("evidence_search: gather_search_evidence failed")
        return []
