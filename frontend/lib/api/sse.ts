import { API_BASE_URL, ApiError, getStoredToken } from "./config";

export type SseRequestInit = {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
};

export class SseHttpError extends ApiError {
  constructor(
    public readonly status: number,
    public readonly payload: unknown,
  ) {
    const detail =
      payload &&
      typeof payload === "object" &&
      "detail" in payload &&
      typeof (payload as { detail: unknown }).detail === "string"
        ? (payload as { detail: string }).detail
        : `SSE failed (${status})`;
    super(status, detail, payload);
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
  signalOrInit?: AbortSignal | SseRequestInit,
  init?: SseRequestInit,
): Promise<void> {
  const token = getStoredToken();
  if (!token) throw new Error("Not authenticated");

  const requestInit = init ?? (signalOrInit as SseRequestInit | undefined) ?? {};
  const signal = init ? (signalOrInit as AbortSignal | undefined) : requestInit.signal;
  const body =
    requestInit.body === undefined
      ? undefined
      : typeof requestInit.body === "string"
        ? requestInit.body
        : JSON.stringify(requestInit.body);

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    Authorization: `Bearer ${token}`,
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: requestInit.method ?? "GET",
    headers,
    body,
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    let data: unknown = text;
    try {
      data = JSON.parse(text);
    } catch {
      // Keep non-JSON provider/proxy errors readable.
    }
    throw new SseHttpError(response.status, data);
  }
  if (!response.body) {
    throw new SseHttpError(response.status, "SSE response had no body");
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
