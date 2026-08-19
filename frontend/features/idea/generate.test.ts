import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";
import { readSseStream } from "@/lib/api/sse";

import { generateIdea } from "./generate";

vi.mock("@/lib/api/sse", () => ({
  readSseStream: vi.fn(),
}));

describe("generateIdea", () => {
  beforeEach(() => {
    vi.mocked(readSseStream).mockReset();
  });

  it("posts expected_version and message and returns the done version", async () => {
    vi.mocked(readSseStream).mockImplementation(async (_path, onEvent) => {
      onEvent({ type: "token", text: "Why?" });
      onEvent({ type: "done", version: 4 });
    });
    const tokens: string[] = [];
    const version = await generateIdea({
      sessionId: "session-1",
      expectedVersion: 3,
      message: "hello",
      onToken: (text) => tokens.push(text),
    });
    expect(version).toBe(4);
    expect(tokens).toEqual(["Why?"]);
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/idea/sessions/session-1/generate",
      expect.any(Function),
      undefined,
      { method: "POST", body: JSON.stringify({ expected_version: 3, message: "hello" }) },
    );
  });

  it("posts answers on cluster Send", async () => {
    vi.mocked(readSseStream).mockImplementation(async (_path, onEvent) => {
      onEvent({ type: "done", version: 5 });
    });
    const version = await generateIdea({
      sessionId: "session-1",
      expectedVersion: 4,
      answers: [{ option: "Training" }],
    });
    expect(version).toBe(5);
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/idea/sessions/session-1/generate",
      expect.any(Function),
      undefined,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: 4, answers: [{ option: "Training" }] }),
      },
    );
  });

  it("throws when the stream reports generate_parse_error", async () => {
    vi.mocked(readSseStream).mockImplementation(async (_path, onEvent) => {
      onEvent({ type: "error", code: "generate_parse_error", detail: "missing json trailer" });
    });
    await expect(
      generateIdea({ sessionId: "session-1", expectedVersion: 1, message: "hello" }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
