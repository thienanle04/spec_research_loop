import { API_BASE_URL, getStoredToken } from "./config";

export class SseHttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly payload: unknown,
  ) {
    super(`SSE failed (${status})`);
    this.name = "SseHttpError";
  }
}

/**
 * Fetch-based SSE reader. Native EventSource cannot send Authorization headers,
 * which we need for JWT Bearer (ADR 0005 + 0004). Orval does not generate this.
 */
export async function readSseStream(
  path: string,
  onEvent: (data: unknown) => void,
  options: {
    method?: "GET" | "POST";
    body?: unknown;
    signal?: AbortSignal;
  } = {},
): Promise<void> {
  const token = getStoredToken();
  if (!token) throw new Error("Not authenticated");

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (!response.ok) {
    const text = await response.text();
    let payload: unknown = text;
    try {
      payload = JSON.parse(text);
    } catch {
      // Keep non-JSON provider/proxy errors readable.
    }
    throw new SseHttpError(response.status, payload);
  }
  if (!response.body) {
    throw new Error("SSE response had no body");
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

  buffer += decoder.decode();
  if (buffer.trim()) {
    const dataLine = buffer.split("\n").find((line) => line.startsWith("data:"));
    if (dataLine) {
      const raw = dataLine.slice(5).trim();
      try {
        onEvent(JSON.parse(raw));
      } catch {
        onEvent(raw);
      }
    }
  }
}
