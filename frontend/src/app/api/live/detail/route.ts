// 役割: Sigmaris Live「詳細表示、+機密情報のマスキング」タスク。バックエンドの
// GET /api/agent/live/detail を、サーバーサイドで中継するNext.js API Route。
//
// live/stream/route.ts(要約データのみの配信)とは異なり、本エンドポイントは
// マスキング済みとはいえ、より個人的な内容(記憶検索・ツール呼び出しの詳細)を
// 扱うため、エージェント認証ヘッダに加え、閲覧している海星さん本人の
// Supabaseセッション(access_token)も、バックエンドへ転送する——Live-1、
// 4.3節が示した「詳細情報は本人のJWTによる確認も必須にすべき」という設計
// 方針を、そのまま実装した(sigmaris_live_report.md、Live-5章参照)。

import { readAgentHeaders } from "@/lib/backend/agent-client";
import { getBackendBaseUrl } from "@/lib/backend/client";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const eventType = url.searchParams.get("eventType");
  const key = url.searchParams.get("key");
  if (!eventType || !key) {
    return Response.json({ error: "eventType and key query parameters are required." }, { status: 400 });
  }

  const agentHeaders = readAgentHeaders();
  if (!agentHeaders) {
    return Response.json(
      { error: "AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。" },
      { status: 503 },
    );
  }

  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) {
    return Response.json({ error: "ログインが必要です。" }, { status: 401 });
  }

  const backendUrl = new URL(`${getBackendBaseUrl()}/api/agent/live/detail`);
  backendUrl.searchParams.set("event_type", eventType);
  backendUrl.searchParams.set("key", key);

  const upstream = await fetch(backendUrl, {
    headers: {
      ...agentHeaders,
      Authorization: `Bearer ${session.access_token}`,
    },
    cache: "no-store",
  });

  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
