import { ApiError } from "@/lib/api/config";
import { readSseStream } from "@/lib/api/sse";

export type IdeaGenerateError = {
  code: string;
  detail: string;
  current_version?: number;
};

export async function generateIdea(options: {
  sessionId: string;
  expectedVersion: number;
  message?: string;
  answers?: Array<{ option?: string; other?: string }>;
  signal?: AbortSignal;
  onToken?: (text: string) => void;
  onProgress?: (message: string) => void;
}): Promise<number> {
  const body: {
    expected_version: number;
    message?: string;
    answers?: Array<{ option?: string; other?: string }>;
  } = {
    expected_version: options.expectedVersion,
  };
  if (options.message !== undefined && options.message !== "") {
    body.message = options.message;
  }
  if (options.answers !== undefined) {
    body.answers = options.answers;
  }

  let version: number | undefined;
  let streamError: IdeaGenerateError | undefined;

  await readSseStream(
    `/api/idea/sessions/${options.sessionId}/generate`,
    (data) => {
      if (!data || typeof data !== "object") return;
      const event = data as Record<string, unknown>;
      if (event.type === "token" && typeof event.text === "string") {
        options.onToken?.(event.text);
      }
      if (event.type === "progress" && typeof event.message === "string") {
        options.onProgress?.(event.message);
      }
      if (event.type === "done" && typeof event.version === "number") {
        version = event.version;
      }
      if (event.type === "error" && typeof event.code === "string") {
        streamError = {
          code: event.code,
          detail: typeof event.detail === "string" ? event.detail : event.code,
          current_version:
            typeof event.current_version === "number" ? event.current_version : undefined,
        };
      }
    },
    options.signal,
    { method: "POST", body: JSON.stringify(body) },
  );

  if (streamError) {
    throw new ApiError(409, streamError.detail, streamError);
  }
  if (version === undefined) {
    throw new Error("Generate ended without a version");
  }
  return version;
}
