// 役割: Sigmaris Live(docs/sigmaris/sigmaris_live_report.md)。バックエンド
// の live_events.py::emit_live_event() が発行するイベントの共通形。
//
// timestampは、バックエンド(time.time())がそのまま送るepoch秒(float)
// であり、ISO文字列ではない——`new Date(event.timestamp * 1000)`で
// 変換すること。Live-1の設計メモに載っていたJSON例("2026-07-18T...")
// はあくまで設計時の説明用表記であり、実装(Live-2)は秒単位の数値である
// ことを、backend/app/services/live_events.py::_publish_live_event()で
// 直接確認した。

export type LiveEvent = {
  event: string;
  invocation_id: string;
  timestamp: number;
  [key: string]: unknown;
};

export type LiveConnectionStatus = "connecting" | "open" | "error";
