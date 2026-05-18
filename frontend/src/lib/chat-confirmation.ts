export type ChatConfirmationAction = {
  tool: string;
  title: string;
  description: string;
};

const CONFIRMATION_RE =
  /<!--\s*shiftpilot-confirmation\s+([\s\S]*?)\s*-->/g;

export const removeConfirmationMarkers = (text: string) =>
  text.replace(CONFIRMATION_RE, "").trimEnd();

export const parseLatestConfirmationAction = (
  text: string,
): ChatConfirmationAction | null => {
  let latest: RegExpExecArray | null = null;
  CONFIRMATION_RE.lastIndex = 0;

  for (;;) {
    const match = CONFIRMATION_RE.exec(text);
    if (!match) break;
    latest = match;
  }

  CONFIRMATION_RE.lastIndex = 0;
  if (!latest) return null;

  try {
    const parsed = JSON.parse(latest[1]) as Partial<ChatConfirmationAction>;
    if (
      typeof parsed.tool !== "string" ||
      typeof parsed.title !== "string" ||
      typeof parsed.description !== "string"
    ) {
      return null;
    }

    return {
      tool: parsed.tool,
      title: parsed.title,
      description: parsed.description,
    };
  } catch {
    return null;
  }
};
