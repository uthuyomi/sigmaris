// 役割: Next.js側からPythonバックエンドAPIへリクエストする共通クライアントをまとめる。

export const getBackendBaseUrl = () =>
  (
    process.env.NEXT_PUBLIC_API_URL ??
    process.env.BACKEND_API_BASE_URL ??
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");

const BACKEND_TIMEOUT_MS = 8000;

// Carries the HTTP status alongside the message so callers can distinguish
// e.g. a 409 conflict (Phase A4's ThreadVersionConflictError) from other
// failures, without every caller having to re-parse the response body.
// Still a plain Error otherwise, so existing `error.message` callers are
// unaffected.
export class BackendApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "BackendApiError";
    this.status = status;
  }
}

export async function fetchBackendJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);

  try {
    const response = await fetch(`${getBackendBaseUrl()}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
      signal: controller.signal,
    });

    if (!response.ok) {
      let detailMessage = `Backend API request failed: ${response.status}`;
      try {
        const errorBody = (await response.json()) as {
          detail?: { error?: string } | string;
        };
        if (typeof errorBody.detail === "string") {
          detailMessage = errorBody.detail;
        } else if (errorBody.detail?.error) {
          detailMessage = errorBody.detail.error;
        }
      } catch {
        // ignore parse failures and keep the generic status error
      }
      throw new BackendApiError(detailMessage, response.status);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}
