from __future__ import annotations

# 役割: チャット意図分類のセマンティックルーティング(埋め込みベースの
# 最近傍マッチ)。INTENT_ROUTER_REDESIGN_SPEC の主役。
#
# 【方式】semantic-router ライブラリは導入せず、既存の埋め込み基盤
# (memory_search.generate_embedding — OpenAI text-embedding-3-small を主に
# Ollama をフォールバックとする 768 次元・多言語対応・キャッシュ付き)を
# そのまま再利用する自前ルータ。仕様書が許容する代替案であり、依存ツリーを
# 増やさず、埋め込みクライアント/キャッシュ/フォールバックを共有できる。
#
# 【流れ】intent ごとの代表発話(utterances)をプロセス内で一度だけ埋め込み、
# 入力発話の埋め込みとのコサイン類似度で最近傍 intent を選ぶ。最良スコアが
# 閾値以上なら intent 確定、未満/該当なしなら None を返し、呼び出し元
# (chat_routing.classify_chat_intent)が LLM フォールバックへ回す。
#
# 【安全側の設計】埋め込みが得られない場合(OPENAI_API_KEY 未設定でオフライン
# など、generate_embedding が [] を返すケース)は例外にせず None を返し、
# 必ず LLM フォールバックに委ねる。ルータが「意見を持てない」ことは事故では
# なく想定内の縮退動作。

import asyncio
import logging
import math
from typing import Awaitable, Callable, Literal

from app.services.memory_search import generate_embedding

logger = logging.getLogger(__name__)

# chat_routing.ChatIntent と同一の値。循環 import を避けるためここでは str の
# エイリアスとして持つ(実体は chat_routing 側の Literal と一致)。
Intent = Literal[
    "general_chat",
    "event_lookup",
    "mobility_plan",
    "schedule_import",
    "calendar_write",
    "sync_control",
]

# 閾値: これ未満のスコア(最良の最近傍でも弱い)は intent 未確定として LLM
# フォールバックへ回す。仕様書の初期レンジ 0.3〜0.5 の中央付近から開始。
# text-embedding-3-small のコサイン類似は、無関係な文でも 0.1〜0.3 程度は
# 出るため、明確に上回る 0.40 を初期値にした(在宅サーバーの実測で調整)。
INTENT_ROUTER_SCORE_THRESHOLD = 0.40

# intent → 代表発話(utterances)。育てる前提の定数。後から発話を足すだけで
# ルーティング品質を改善できる。特に calendar_write には、今回の誤爆
# (「この予定削除できる？」が event_lookup に流れた)を潰すため、疑問形・
# 命令形・編集系を厚めに入れている。
INTENT_UTTERANCES: dict[Intent, list[str]] = {
    "calendar_write": [
        "この予定削除できる？",
        "この予定を削除して",
        "予定を消して",
        "この予定を編集して",
        "予定の時間を変更して",
        "場所を変えて",
        "タイトル直して",
        "この予定の内容を修正したい",
        "カレンダーに入れて",
        "予定を登録して",
        "明日10時に会議を追加して",
        "予定を入れ替えて",
        "この予定をずらして",
        "Googleカレンダーと同期して",
    ],
    "event_lookup": [
        "今日の予定教えて",
        "明日って何か入ってる？",
        "金曜の予定は？",
        "次の仕事いつ？",
        "今週の予定を確認したい",
        "この日空いてる？",
    ],
    "mobility_plan": [
        "何時に出れば間に合う？",
        "現地までどう行く？",
        "車での経路教えて",
        "徒歩だと何分？",
        "自転車で行ける？",
        "家から会場までの移動時間は？",
    ],
    "schedule_import": [
        "この勤務表読み取って",
        "シフト表から予定作って",
        "スプレッドシート取り込んで",
        "この画像の予定を登録して",
        "シートのURLから予定を抽出して",
    ],
    "sync_control": [
        "Google連携オンにして",
        "同期の設定を変えたい",
        "カレンダー連携を切って",
    ],
    "general_chat": [
        "おはよう",
        "元気？",
        "今日の気分どう？",
        "ちょっと相談したいことがある",
        "ありがとう",
    ],
}


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


# utterance 埋め込みのプロセス内キャッシュ。intent ごとに (utterance, vector)
# の一覧を保持する。初回の route 呼び出し時に一度だけ構築し、以降は再利用
# する(各ターンは入力 1 件の埋め込み + 内積のみ)。asyncio.Lock で、起動直後の
# 並行リクエストが同じ埋め込みを二重計算しないようにする。
_utterance_cache: dict[Intent, list[tuple[str, list[float]]]] | None = None
_cache_lock = asyncio.Lock()

# テスト時に本物の埋め込み(ネットワーク)を避けるための注入ポイント。既定は
# memory_search.generate_embedding。回帰テストはここへ決め打ちのダミー
# エンコーダを差し込み、オフラインでルーティングを検証する。
EmbedFn = Callable[[str], Awaitable[list[float]]]


async def _build_utterance_cache(embed: EmbedFn) -> dict[Intent, list[tuple[str, list[float]]]]:
    cache: dict[Intent, list[tuple[str, list[float]]]] = {}
    for intent, utterances in INTENT_UTTERANCES.items():
        pairs: list[tuple[str, list[float]]] = []
        for utterance in utterances:
            vector = await embed(utterance)
            if vector:
                pairs.append((utterance, vector))
        cache[intent] = pairs
    return cache


async def _get_utterance_cache(embed: EmbedFn) -> dict[Intent, list[tuple[str, list[float]]]]:
    global _utterance_cache
    if _utterance_cache is not None:
        return _utterance_cache
    async with _cache_lock:
        if _utterance_cache is None:
            _utterance_cache = await _build_utterance_cache(embed)
    return _utterance_cache


async def route_intent_semantic(
    text: str,
    *,
    embed: EmbedFn | None = None,
    threshold: float = INTENT_ROUTER_SCORE_THRESHOLD,
) -> tuple[Intent | None, float]:
    """入力発話の意図を、代表発話との埋め込み最近傍でセマンティックに判定する。

    戻り値は (intent | None, best_score)。best_score が threshold 以上のときのみ
    intent を返し、それ以外は (None, best_score) を返して呼び出し元に LLM
    フォールバックを促す。埋め込みが得られない(空)ときは (None, 0.0)。

    embed: テスト用の埋め込み関数注入ポイント(既定は generate_embedding)。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None, 0.0

    embed_fn: EmbedFn = embed or generate_embedding
    query_vector = await embed_fn(cleaned)
    if not query_vector:
        # 埋め込み基盤が使えない(APIキー無し等)。安全に LLM フォールバックへ。
        return None, 0.0

    cache = await _get_utterance_cache(embed_fn)

    best_intent: Intent | None = None
    best_score = 0.0
    for intent, pairs in cache.items():
        for _utterance, vector in pairs:
            score = _cosine_similarity(query_vector, vector)
            if score > best_score:
                best_score = score
                best_intent = intent

    if best_intent is not None and best_score >= threshold:
        return best_intent, best_score
    return None, best_score


def reset_utterance_cache() -> None:
    """テスト用: utterance 埋め込みキャッシュを破棄する(別エンコーダで再構築
    させたいとき)。本番コードからは呼ばれない。"""
    global _utterance_cache
    _utterance_cache = None
