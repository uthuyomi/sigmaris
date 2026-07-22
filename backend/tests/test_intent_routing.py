from __future__ import annotations

# INTENT_ROUTER_REDESIGN の回帰テスト。
#
# 【ネットワーク非依存】本物の埋め込み(OpenAI/Ollama)には触れない。
# route_intent_semantic の embed 引数へ、決め打ちベクトルを返すダミー
# エンコーダを注入し、セマンティック分類をオフラインで検証する。実埋め込み
# での精度は在宅サーバー(APIキーあり)での実地確認に委ねる。

import asyncio

import pytest

from app.services.chat_routing import (
    VALID_INTENTS,
    deterministic_intent,
    tool_names_for_intent,
)
from app.services.intent_router import (
    INTENT_UTTERANCES,
    route_intent_semantic,
)

# 除外されたはずのアプリ内カレンダー系(GOOGLE_CALENDAR_ONLY_SPEC)。
APP_TOOLS = {"search_app_events", "list_app_events", "create_app_events"}
CORE_CRUD = {
    "list_google_calendar_events",
    "create_google_calendar_events",
    "update_google_calendar_events",
    "delete_google_calendar_events",
}


# ─── ダミーエンコーダ ────────────────────────────────────────────────
# 各シード utterance と、テスト対象の入力発話に、決め打ちの単位ベクトルを
# 割り当てる。「同じ意図の発話は同じ向き」にして、コサイン類似=1.0 で
# 最近傍が引けるようにする。utterance に無い入力は、その入力が属するべき
# intent の代表方向に寄せて登録する。
_INTENT_LIST = list(INTENT_UTTERANCES.keys())
_DIM = len(_INTENT_LIST)


def _one_hot(intent: str) -> list[float]:
    return [1.0 if _INTENT_LIST[i] == intent else 0.0 for i in range(_DIM)]


# 入力発話 → それが属する正解 intent(この向きのベクトルを返す)。
_PHRASE_TO_INTENT = {
    "この予定削除できる？": "calendar_write",
    "この予定編集して": "calendar_write",
    "時間変更して": "calendar_write",
    "今日の予定教えて": "event_lookup",
    "何時に出れば間に合う？": "mobility_plan",
    "勤務表読み取って": "schedule_import",
    "おはよう": "general_chat",
}


async def _dummy_embed(text: str) -> list[float]:
    # シード utterance は、その intent の one-hot 方向。
    for intent, utterances in INTENT_UTTERANCES.items():
        if text in utterances:
            return _one_hot(intent)
    # テスト入力は、正解 intent の方向へ。未知語は零ベクトル(=該当なし)。
    if text in _PHRASE_TO_INTENT:
        return _one_hot(_PHRASE_TO_INTENT[text])
    return [0.0] * _DIM


def _route(text: str):
    # 各テストで utterance キャッシュを作り直したいので、毎回ダミーを注入。
    from app.services.intent_router import reset_utterance_cache

    reset_utterance_cache()
    return asyncio.run(route_intent_semantic(text, embed=_dummy_embed, threshold=0.4))


# ─── セマンティックルーティング回帰(既知の誤爆を含む) ──────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("この予定削除できる？", "calendar_write"),  # 今回のバグ。必ず通す。
        ("この予定編集して", "calendar_write"),
        ("時間変更して", "calendar_write"),
        ("今日の予定教えて", "event_lookup"),
        ("何時に出れば間に合う？", "mobility_plan"),
        ("勤務表読み取って", "schedule_import"),
        ("おはよう", "general_chat"),
    ],
)
def test_semantic_routing_expected_intent(text, expected):
    intent, score = _route(text)
    assert intent == expected, f"{text!r} -> {intent} (score={score:.3f}), expected {expected}"


def test_low_confidence_falls_back_to_llm():
    # 零ベクトルになる未知入力は intent 未確定(None)＝LLM フォールバックへ。
    intent, score = _route("量子コンピュータの原理を教えて")
    assert intent is None


# ─── 決定的プレチェック ──────────────────────────────────────────────
def test_deterministic_template_tag():
    intent, reason = deterministic_intent(
        latest_text="[shiftpilotai処理: calendar_write] 予定",
        has_file_attachment=False,
        has_image_context=False,
    )
    assert intent == "calendar_write"


def test_deterministic_attachment_is_schedule_import():
    intent, reason = deterministic_intent(
        latest_text="これ読み取って",
        has_file_attachment=True,
        has_image_context=False,
    )
    assert intent == "schedule_import"


def test_deterministic_returns_none_for_plain_text():
    intent, reason = deterministic_intent(
        latest_text="この予定削除できる？",
        has_file_attachment=False,
        has_image_context=False,
    )
    assert intent is None  # ファジー判定は撤去済み。意味判定はルータに委ねる。


# ─── tool_names_for_intent の構造アサート ────────────────────────────
def test_calendar_write_has_full_crud():
    tools = set(tool_names_for_intent("calendar_write"))
    assert {"create_google_calendar_events", "update_google_calendar_events", "delete_google_calendar_events"} <= tools


def test_core_crud_in_event_lookup_and_general_chat():
    # 誤爆保険(defense in depth): 中核CRUDが両 intent にも渡ること。
    for intent in ("event_lookup", "general_chat"):
        tools = set(tool_names_for_intent(intent))
        assert CORE_CRUD <= tools, f"{intent} missing core CRUD: {CORE_CRUD - tools}"


def test_no_app_tools_in_any_intent():
    for intent in list(VALID_INTENTS) + ["__fallback__"]:
        tools = set(tool_names_for_intent(intent))
        assert not (APP_TOOLS & tools), f"{intent} leaked app tools: {APP_TOOLS & tools}"
