# 役割: Sigmaris Live(docs/sigmaris/sigmaris_live_report.md、Live-1で設計、
# 本タスクLive-2で最初の実装)のイベント発行・配信基盤。
#
# 【Live-2時点のスコープ】classify_chat_intent()の開始・終了イベントの
# みが、この仕組みを使う(依頼書「本タスクの範囲はclassify_chat_intent()
# のみ」)。他の処理(記憶検索・応答生成等)への拡大は、次タスク以降。
#
# 【絶対原則、Live-1から継続、本モジュールで実装する】
# - イベント発行が失敗しても、本来の処理(意図分類等)には一切影響しない
#   (fire-and-forgetパターン、asyncio.create_task経由)
# - イベント発行タスク自身が、内部で例外を処理する(外へ伝播させると
#   「Task exception was never retrieved」という警告がログに残るため
#   ——Live-1、3.2節の実測で確認済みの懸念への対応)
# - イベントのペイロードは、要約データ(件数・真偽値・カテゴリラベル)の
#   みとし、生のユーザー発言・記憶内容・応答本文等は一切含めない
#   (呼び出し元の責務——本モジュール自体はペイロードの中身を検査しない)
# - publish/subscribeを分離し、観察者の接続と、実際にチャットしている
#   ユーザー自身の接続を独立させる(Live-1、3.4節)
#
# 【単一プロセス前提】LiveEventBusは、プロセス内メモリの単純なpub/subで
# あり、複数uvicornワーカー構成には対応しない(Live-1、3.4節で明記済みの
# 制約——docs/infrastructure.mdで確認した現行の単一プロセス構成が前提)。

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 1接続あたりの、未配信イベントの上限。観察者が受信を止めた(切断済み
# だが後片付け前、等)場合に、キューが無限に伸びてメモリを圧迫しないための
# 保護——本来の処理には一切影響しない(publish()はドロップするだけ)。
_QUEUE_MAXSIZE = 100


@dataclass
class LiveEventBus:
    _subscribers: set[asyncio.Queue] = field(default_factory=set)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        """同期・非I/O(インメモリのキュー操作のみ)。接続中の観察者
        全員のキューへ配置する。キューが満杯の観察者にはこのイベントを
        スキップする(古いイベントが溜まり続けることを防ぐ、観察者側の
        保護であり、発行側の処理には影響しない)。"""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("live_events: subscriber queue full, dropping event")


_bus = LiveEventBus()


def get_live_event_bus() -> LiveEventBus:
    return _bus


def emit_live_event(event_type: str, invocation_id: str, **fields: Any) -> None:
    """fire-and-forgetのイベント発行。呼び出し元は、これをawaitしない
    (同期関数として、通常の処理の合間に1行で呼べる)。失敗しても、
    呼び出し元の処理(意図分類等)には一切伝播しない。

    判断根拠(asyncio.create_taskを使う理由): LiveEventBus.publish()自体は
    インメモリのキュー操作のみでI/Oを伴わないため、理論上はこの関数を
    同期のまま`_bus.publish(...)`を直接呼んでも安全ではある。しかし
    依頼書が「Live-1で確立されたfire-and-forgetパターンを必ず実装する
    こと」を明示的に要求しており、また将来的に配信層がI/Oを伴う実装
    (Live-1、3.4節で言及した複数ワーカー構成時のRedis pub/sub等)に
    置き換わった場合でも、呼び出し元(classify_chat_intent()の呼び出し
    箇所)のコードを変更せずに済むよう、最初から統一されたパターンを
    採用した。"""
    asyncio.create_task(
        _publish_live_event(event_type, invocation_id, fields),
        name=f"live_event:{event_type}:{invocation_id}",
    )


async def _publish_live_event(event_type: str, invocation_id: str, fields: dict[str, Any]) -> None:
    """このタスク自身の中で例外を処理する(自己完結)。呼び出し元
    (classify_chat_intent()の呼び出し箇所)には、成功・失敗のいずれも
    一切伝わらない。"""
    try:
        event = {
            "event": event_type,
            "invocation_id": invocation_id,
            "timestamp": time.time(),
            **fields,
        }
        _bus.publish(event)
    except Exception:
        logger.exception("live_events: emit_live_event failed type=%s", event_type)
