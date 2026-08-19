import { API_BASE_URL, ApiError, getStoredToken } from "./config";

export type SseRequestInit = {
  method?: "GET" | "POST";
  body?: string;
};

/**
 * Fetch-based SSE reader. Native EventSource cannot send Authorization headers,
 * which we need for JWT Bearer (ADR 0005 + 0004). Orval does not generate this.
 */
export async function readSseStream(
  path: string,
  onEvent: (data: unknown) => void,
  signal?: AbortSignal,
  init?: SseRequestInit,
): Promise<void> {
  const token = getStoredToken();
  if (!token) throw new Error("Not authenticated");

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    Authorization: `Bearer ${token}`,
  };
  if (init?.body) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: init?.method ?? "GET",
    headers,
    body: init?.body,
    signal,
  });

  if (!response.ok) {
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = undefined;
    }
    const message =
      data &&
      typeof data === "object" &&
      "detail" in data &&
      typeof (data as { detail: unknown }).detail === "string"
        ? (data as { detail: string }).detail
        : `SSE failed (${response.status})`;
    throw new ApiError(response.status, message, data);
  }
  if (!response.body) {
    throw new ApiError(response.status, `SSE failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const raw = dataLine.slice(5).trim();
      try {
        onEvent(JSON.parse(raw));
      } catch {
        onEvent(raw);
      }
    }
  }
}
