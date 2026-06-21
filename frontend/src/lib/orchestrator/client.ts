import type {
  OrchestratorChatResponse,
  OrchestratorMessage,
} from "@/lib/orchestrator/types";

export async function sendOrchestratorMessage(input: {
  messages: OrchestratorMessage[];
  threadId?: string;
}): Promise<OrchestratorChatResponse> {
  const response = await fetch("/api/orchestrator/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: input.messages,
      threadId: input.threadId,
    }),
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      data && typeof data.error === "string"
        ? data.error
        : "Sigmaris orchestrator request failed.";
    throw new Error(message);
  }
  return data as OrchestratorChatResponse;
}
