// 役割: Next.js側からPythonバックエンドAPIへリクエストする共通クライアントをまとめる。

export const getBackendBaseUrl = () =>
  process.env.BACKEND_API_BASE_URL?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

const BACKEND_TIMEOUT_MS = 8000;

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
      throw new Error(detailMessage);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}
