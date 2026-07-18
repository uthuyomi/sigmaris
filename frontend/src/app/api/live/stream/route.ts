// 役割: Sigmaris Live-2(docs/sigmaris/sigmaris_live_report.md)。バックエンド
// の GET /api/agent/live/stream(SSE)を、サーバーサイドでエージェント認証
// ヘッダ付きで呼び出し、そのままブラウザへ中継するNext.js API Route。
//
// エージェント認証情報(AGENT_SECRETS等)は、agent-client.tsのreadAgentHeaders()
// と同様、サーバーサイドの環境変数からのみ読み、ブラウザには一切渡さない
// (growth/timelineページのfetchAgentJson()と同じ設計方針)。EventSourceは
// ブラウザからカスタムヘッダを付与できないため、この中継が必須になる。

import { readAgentHeaders } from "@/lib/backend/agent-client";
import { getBackendBaseUrl } from "@/lib/backend/client";

export const dynamic = "force-dynamic";

export async function GET() {
  const agentHeaders = readAgentHeaders();
  if (!agentHeaders) {
    return new Response("AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。", {
      status: 503,
    });
  }

  const upstream = await fetch(`${getBackendBaseUrl()}/api/agent/live/stream`, {
    headers: { ...agentHeaders },
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "");
    return new Response(`Sigmaris Live配信への接続に失敗しました (${upstream.status})${detail ? `: ${detail.slice(0, 180)}` : ""}`, {
      status: upstream.status || 502,
    });
  }

  // バックエンドのSSEレスポンスボディを、そのままバイト単位で中継する
  // (テキスト変換・イベントの加工は一切行わない — バックエンドが既に
  // Live-1の設計通り要約データのみを配信しているため、この中継層で
  // 追加のフィルタリングは不要)。
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
