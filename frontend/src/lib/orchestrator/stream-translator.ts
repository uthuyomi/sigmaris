// 役割: バックエンドのオーケストレーターSSEストリーム(delta/tool_event/done/error)を
// AI SDKのUI Message Streamプロトコル(start/text-start/text-delta/tool-*/text-end/finish)
// に変換する。/chat がPhase A1-bでオーケストレーター経由に切り替わったことに伴う変換層。

const encoder = new TextEncoder();
const decoder = new TextDecoder();

type OrchestratorEvent = {
  tool_event?: Record<string, unknown>;
  delta?: string;
  done?: boolean;
  thread_id?: string;
  invocation_id?: string;
  error?: string;
};

const sseLine = (payload: unknown) =>
  encoder.encode(`data: ${JSON.stringify(payload)}\n\n`);

/**
 * Consumes the raw `data: {...}\n\n` SSE body from
 * POST /api/orchestrator/chat/stream and re-emits it as an AI SDK UI message
 * stream. tool_event payloads are already AI-SDK-shaped (relayed verbatim by
 * the backend from chat.py's own stream) and are passed through unchanged.
 */
export const translateOrchestratorStream = (
  upstream: ReadableStream<Uint8Array>,
  responseMessageId?: string,
): ReadableStream<Uint8Array> => {
  const messageId = responseMessageId || crypto.randomUUID();
  const textPartId = crypto.randomUUID();
  let buffer = "";
  let textStarted = false;
  let finished = false;

  const ensureTextStarted = (controller: ReadableStreamDefaultController<Uint8Array>) => {
    if (textStarted) return;
    textStarted = true;
    controller.enqueue(sseLine({ type: "text-start", id: textPartId }));
  };

  const finish = (
    controller: ReadableStreamDefaultController<Uint8Array>,
    finishReason: "stop" | "error",
  ) => {
    if (finished) return;
    finished = true;
    ensureTextStarted(controller);
    controller.enqueue(sseLine({ type: "text-end", id: textPartId }));
    controller.enqueue(sseLine({ type: "finish", finishReason }));
  };

  return new ReadableStream<Uint8Array>({
    async start(controller) {
      // メッセージ日時表示機能: このターンの応答が実際に届き始めた時点の
      // 時刻を、AI SDKのUI Message Streamプロトコルが標準でサポートする
      // messageMetadataとして付与する(docs/sigmaris/phase_ba4_report.md)。
      // 表示専用の値であり、永続化される真のcreated_at(バックエンドの
      // turn_started_at、chat.pyでの並び替えに使われる値)とは別物 —
      // このNext.jsルートのクロックで捕捉した近似値に過ぎない。custom配下
      // に置く理由はthread.tsx::readCreatedAt()のコメントを参照
      // (assistant-uiのメッセージ合流処理がmetadataのトップレベルキーを
      // ホワイトリスト式にしか通さないため)。
      controller.enqueue(
        sseLine({
          type: "start",
          messageId,
          messageMetadata: { custom: { createdAt: new Date().toISOString() } },
        }),
      );
      const reader = upstream.getReader();
      try {
        for (;;) {
          const { value, done: readerDone } = await reader.read();
          if (readerDone) break;
          buffer += decoder.decode(value, { stream: true });

          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const chunk = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");

            const line = chunk.split("\n").find((l) => l.startsWith("data:"));
            if (!line) continue;
            const raw = line.slice("data:".length).trim();
            if (!raw) continue;

            let event: OrchestratorEvent;
            try {
              event = JSON.parse(raw) as OrchestratorEvent;
            } catch {
              continue;
            }

            if (event.tool_event) {
              controller.enqueue(sseLine(event.tool_event));
            }
            if (typeof event.delta === "string" && event.delta) {
              ensureTextStarted(controller);
              controller.enqueue(
                sseLine({ type: "text-delta", id: textPartId, delta: event.delta }),
              );
            }
            if (event.error) {
              ensureTextStarted(controller);
              controller.enqueue(
                sseLine({
                  type: "text-delta",
                  id: textPartId,
                  delta: `処理中に接続が落ちたよ。backend側でエラーが出ているから、直前のログを見れば原因が分かるはずだね。詳細: ${event.error}`,
                }),
              );
              finish(controller, "error");
              controller.close();
              return;
            }
            if (event.done) {
              finish(controller, "stop");
              controller.close();
              return;
            }
          }
        }
        // Upstream closed without an explicit done/error event.
        finish(controller, "stop");
        controller.close();
      } catch (error) {
        ensureTextStarted(controller);
        const message = error instanceof Error ? error.message : "unknown stream error";
        controller.enqueue(
          sseLine({
            type: "text-delta",
            id: textPartId,
            delta: `処理中に接続が落ちたよ。詳細: ${message}`,
          }),
        );
        finish(controller, "error");
        controller.close();
      } finally {
        reader.releaseLock();
      }
    },
  });
};
