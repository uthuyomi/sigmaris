from __future__ import annotations

# 役割: チャット意図分類と利用ツールの選択を行う。

import json
from typing import Any, Literal

from app.services.intent_router import route_intent_semantic
from app.services.local_llm import TaskType, get_llm_router
from app.services.search_trigger import detect_search_need, merge_llm_search_judgment

ChatIntent = Literal[
    "general_chat",
    "event_lookup",
    "mobility_plan",
    "schedule_import",
    "calendar_write",
    "sync_control",
]


VALID_INTENTS: set[str] = {
    "general_chat",
    "event_lookup",
    "mobility_plan",
    "schedule_import",
    "calendar_write",
    "sync_control",
}

def latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        texts = [
            str(part.get("text", "")).strip()
            for part in message.get("parts", [])
            if part.get("type") == "text" and str(part.get("text", "")).strip()
        ]
        return "\n".join(texts).strip()
    return ""


def has_attachment(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        return any(part.get("type") == "file" for part in message.get("parts", []))
    return False


def deterministic_intent(
    *,
    latest_text: str,
    has_file_attachment: bool,
    has_image_context: bool,
) -> tuple[ChatIntent | None, str | None]:
    """曖昧さゼロの決定的シグナルのみで intent を即断する(旧 heuristic_intent の
    ファジーなキーワード判定は INTENT_ROUTER_REDESIGN で完全撤去し、意味判定は
    セマンティックルータ→LLM フォールバックに一本化した)。

    ここで扱うのは「キーワード誤爆」の原因にならない明示信号だけ:
    - [shiftpilotai処理: ...] テンプレートタグ(フロントが付与する操作指定)
    - 添付ファイル / 画像コンテキスト → schedule_import
    該当しなければ (None, None) を返し、呼び出し元がセマンティックルータへ回す。
    """
    lowered = latest_text.lower()

    if "[shiftpilotai処理: calendar_write]" in lowered:
        return "calendar_write", "template-operation-tag"
    if "[shiftpilotai処理: mobility_plan]" in lowered:
        return "mobility_plan", "template-operation-tag"
    if "[shiftpilotai処理: event_lookup]" in lowered:
        return "event_lookup", "template-operation-tag"
    if "[shiftpilotai処理: schedule_import]" in lowered:
        return "schedule_import", "template-operation-tag"
    if "[shiftpilotai処理: sync_control]" in lowered:
        return "sync_control", "template-operation-tag"

    if has_file_attachment or has_image_context:
        return "schedule_import", "attachment-present"

    return None, None


async def classify_chat_intent(
    *,
    messages: list[dict[str, Any]],
    attachment_facts: str,
) -> dict[str, Any]:
    latest_text = latest_user_text(messages)
    has_file_attachment = has_attachment(messages)
    has_image_context = bool(attachment_facts)

    # Phase G-1(docs/sigmaris/phase_g_report.md): 「検索が必要か」のルール
    # ベース判定は、LLMを一切呼ばずに常に行える(I/Oなし、O(1)級の文字列
    # 検索のみ)。ヒューリスティックがintentを即断してLLM呼び出し自体を
    # スキップするターンでも、この判定だけは必ず得られる。
    search_signal = detect_search_need(latest_text=latest_text)

    # (1) 決定的プレチェック: テンプレートタグ・添付/画像のみ。曖昧さゼロ。
    guessed_intent, guessed_reason = deterministic_intent(
        latest_text=latest_text,
        has_file_attachment=has_file_attachment,
        has_image_context=has_image_context,
    )
    if guessed_intent:
        return {
            "intent": guessed_intent,
            "reason": guessed_reason or "deterministic",
            "source": "deterministic",
            "search": search_signal,
        }

    # (2) セマンティックルータ(主役): 代表発話との埋め込み最近傍で意味判定。
    # スコアが閾値以上なら intent 確定し、LLM 呼び出しをスキップする。
    # search_signal は現状どおりルールベースの detect_search_need を使う
    # (Phase G-1 の設計を踏襲。LLM を呼ばないターンでも検索要否は出せる)。
    try:
        routed_intent, routed_score = await route_intent_semantic(latest_text)
    except Exception:
        routed_intent, routed_score = None, 0.0
    if routed_intent in VALID_INTENTS:
        return {
            "intent": routed_intent,
            "reason": f"semantic-router score={routed_score:.3f}",
            "source": "semantic",
            "search": search_signal,
        }

    # (3) LLM フォールバック: ルータが確信を持てなかったターンのみ。
    transcript_lines: list[str] = []
    for message in messages[-6:]:
        role = str(message.get("role", "user"))
        texts = [
            str(part.get("text", "")).strip()
            for part in message.get("parts", [])
            if part.get("type") == "text" and str(part.get("text", "")).strip()
        ]
        if texts:
            transcript_lines.append(f"{role}: {' '.join(texts)}")
    transcript = "\n".join(transcript_lines)[:4000]

    prompt = "\n".join(
        [
            "Classify the user request for Sigmaris.",
            'Return JSON only like {"intent":"...","reason":"...","needs_search":true,"search_reason":"..."}.',
            "Valid intents: general_chat, event_lookup, mobility_plan, schedule_import, calendar_write, sync_control.",
            "Use mobility_plan for route, departure, public-transit questions, walking, driving, bicycle, or home-to-destination guidance. Public-transit auto planning is unavailable; answer with that limitation and offer car, walking, or bicycle route planning.",
            "Use schedule_import for images, spreadsheets, work schedules, shift tables, or extracting events from files.",
            "Use calendar_write for adding, deleting, editing, replacing, writing, or syncing calendar events, including questions like 'can you delete this?' or 'can you change the time?' that imply a write/edit action.",
            "Use event_lookup for identifying which calendar event/day the user refers to.",
            "Use sync_control for integration or sync mode settings.",
            "Use general_chat only if no specialized intent is dominant.",
            # Phase G-1(docs/sigmaris/phase_g_report.md): 検索要否も同じ
            # JSON応答へ相乗りさせる(新規LLM呼び出しを追加しない)。
            "Also decide needs_search: true if answering well requires current prices, specs, availability, versions, rankings, release dates, or other facts that change over time and might be stale in memory; also true if the request names a specific product, company, or model whose current details may not be known. False for general chat, personal schedule questions, or anything answerable from stable general knowledge or the assistant's existing memory of the user. Briefly explain in search_reason.",
            f"has_attachment={has_file_attachment}",
            f"has_image_context={has_image_context}",
            transcript,
        ]
    )

    try:
        # Phase: nano-tier migration (see docs/sigmaris/
        # incident_response_latency_investigation.md 11) — routed through
        # the same LLMRouter every other lightweight classifier in this
        # codebase uses (B7's decompose_query, B14-B16, etc.) instead of a
        # raw AsyncOpenAI Responses API call. This gets three things for
        # free, with no code here needing to implement any of them:
        # (1) TaskType.CHAT_INTENT_CLASSIFICATION is nano-tier
        # (openai_nano_model) rather than the "mini" tier this call used to
        # share with BA4's own unified generation; (2) if LOCAL_LLM_ENABLED
        # and Ollama actually has a chat model installed, this can run
        # locally instead of over the network at all; (3) if not,
        # LLMRouter._get_backend() caches that verdict once per process
        # lifetime (local_llm.py's is_available() checks the model list,
        # not just bare reachability) and falls straight to OpenAI on every
        # subsequent call — no per-call 404-and-retry.
        #
        # 800 (unchanged from the prior task) is passed straight through as
        # max_tokens: LocalLLMClient maps it to Ollama's num_predict,
        # _OpenAIAdapter maps it to max_completion_tokens on the Chat
        # Completions API. The Responses-API-specific "reasoning tokens
        # might eat the whole budget" risk that motivated picking a
        # generous 800 in the first place is a much smaller concern here —
        # every other nano-tier TaskType in this codebase (B7's
        # QUERY_DECOMPOSITION included) already runs successfully on the
        # Chat Completions API with budgets as low as 100-300 — but 800 is
        # kept as-is per this task's requirement 4 rather than re-tuned.
        router = get_llm_router()
        raw = await router.chat(
            TaskType.CHAT_INTENT_CLASSIFICATION,
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
            json_mode=True,
        )
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(payload, dict):
            payload = {}
        intent = payload.get("intent")
        if intent not in VALID_INTENTS:
            intent = "general_chat"
        llm_needs_search = payload.get("needs_search")
        if not isinstance(llm_needs_search, bool):
            llm_needs_search = None
        return {
            "intent": intent,
            "reason": str(payload.get("reason") or "llm-router"),
            "source": "llm",
            "search": merge_llm_search_judgment(
                search_signal,
                llm_needs_search=llm_needs_search,
                llm_search_reason=payload.get("search_reason"),
            ),
        }
    except Exception:
        return {
            "intent": "general_chat",
            "reason": "llm-router-fallback",
            "source": "fallback",
            "search": search_signal,
        }


def build_specialized_router_instruction(
    *,
    intent: ChatIntent,
    route_reason: str,
    route_source: str,
) -> str:
    common = [
        f"Routed intent: {intent}.",
        f"Routing source: {route_source}.",
        f"Routing reason: {route_reason}.",
    ]
    details: dict[ChatIntent, list[str]] = {
        "general_chat": [
            "Handle this as general planning chat.",
            "Use tools only when they materially improve the answer.",
            "If the user asks to add, register, confirm, save, or put an event into the calendar, use the available calendar write tools instead of saying write tools are unavailable.",
        ],
        "event_lookup": [
            "This request likely refers to an existing event.",
            "Google Calendar (list_google_calendar_events) is the single source of truth for the user's schedule.",
            "Calendar reads are non-destructive, so perform them without asking for confirmation.",
            "If the user asks to add, register, confirm, save, or put an event into the calendar after a lookup, use the calendar write tools instead of saying write tools are unavailable.",
            "If the user gives a relative date such as today, tomorrow, or the day after tomorrow, use list_google_calendar_events for that whole day before asking the user to restate dates or start times.",
            "Search the likely day or a narrow adjacent-day window and try practical query variants from the title, location, and address fragments before saying the event was not found.",
            "If Google Calendar returns GOOGLE_AUTH_EXPIRED, say reconnection is needed, but still use known user-provided details before asking for the missing field.",
        ],
        "mobility_plan": [
            "This request is primarily about travel planning.",
            "Use read_home_context if the user says home or does not specify the travel mode.",
            "Google Calendar (list_google_calendar_events) is the single source of truth for the user's schedule.",
            "Calendar reads are non-destructive, so perform them without asking for confirmation.",
            "Use list_google_calendar_events when the date is known or relative, then inspect the day's events for the destination or site name.",
            "Ask for the start time only after available Google Calendar reads fail to provide it.",
            "Public-transit auto planning is unavailable in this app. Do not attempt bus or train route lookup.",
            "Use plan_google_route only for car, walk, or bicycle if it helps provide a useful comparison without asking another question.",
            "When the user explicitly wants to add the route into the schedule, save it with save_travel_plan_for_event after confirmation.",
            "If the event location is only a site name but an exact destination address is known from the conversation, pass it as destinationAddress when saving.",
        ],
        "schedule_import": [
            "This request is primarily about importing schedules.",
            "Use attachment facts and read_google_sheet when relevant.",
        ],
        "calendar_write": [
            "This request is primarily about writing or replacing calendar events.",
            "Google Calendar is the single source of truth. For ordinary phrases like 'add to calendar', 'register in calendar', or 'save this schedule', use create_google_calendar_events.",
            "Confirm destructive actions before deletion or replacement.",
        ],
        "sync_control": [
            "This request is about sync or integration control.",
            "Answer operationally and clearly.",
        ],
    }
    return "\n".join([*common, *details[intent]])


def tool_names_for_intent(intent: ChatIntent) -> list[str]:
    # Google Calendar 一本化(GOOGLE_CALENDAR_ONLY_SPEC): 各 intent の返却
    # リストから、アプリ内カレンダー系ツール(search_app_events /
    # list_app_events / create_app_events)を除外し、Google 系だけを AI に
    # 渡す。app系のツール定義・実装・DBテーブルは温存しており(可逆)、この
    # リストへ戻すだけで従来動作に復帰できる。
    # 誤爆の保険(INTENT_ROUTER_REDESIGN, defense in depth): カレンダーの
    # 読み書き中核ツール(list/create/update/delete_google_calendar_events)は、
    # 意味判定が稀に外しても操作不能事故にならないよう、general_chat と
    # event_lookup にも含める。専門ツール(経路計画・シート取込)は intent 出し
    # 分けのまま。
    if intent == "general_chat":
        return [
            "read_home_context",
            "list_google_calendar_events",
            "create_google_calendar_events",
            "update_google_calendar_events",
            "delete_google_calendar_events",
        ]
    if intent == "event_lookup":
        return [
            "list_google_calendar_events",
            "create_google_calendar_events",
            "update_google_calendar_events",
            "delete_google_calendar_events",
            "read_home_context",
        ]
    if intent == "mobility_plan":
        return [
            "read_home_context",
            "list_google_calendar_events",
            "plan_google_route",
            "save_travel_plan_for_event",
        ]
    if intent == "schedule_import":
        return [
            "read_google_sheet",
            "create_google_calendar_events",
            "list_google_calendar_events",
            "read_home_context",
        ]
    if intent == "calendar_write":
        return [
            "read_home_context",
            "list_google_calendar_events",
            "create_google_calendar_events",
            "update_google_calendar_events",
            "delete_google_calendar_events",
            "delete_google_calendar_events_in_range",
            "read_google_sheet",
            "plan_google_route",
            "save_travel_plan_for_event",
        ]
    return ["read_home_context", "list_google_calendar_events"]
