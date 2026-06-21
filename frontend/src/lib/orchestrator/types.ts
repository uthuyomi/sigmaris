export type OrchestratorMessage = {
  role: "user" | "assistant";
  content: string;
};

export type OrchestratorChatResponse = {
  ok: true;
  text: string;
  thread_id: string;
  invocation_id: string;
  agent_id: string;
  used_fallback: boolean;
};
