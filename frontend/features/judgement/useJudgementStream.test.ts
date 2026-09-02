import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readSseStream } from "@/lib/api/sse";

import { useJudgementStream } from "./useJudgementStream";

vi.mock("@/lib/api/sse", () => ({
  readSseStream: vi.fn(),
  SseHttpError: class SseHttpError extends Error {
    status: number;
    payload: unknown;
    constructor(status: number, payload: unknown) {
      super("sse");
      this.status = status;
      this.payload = payload;
    }
  },
}));

describe("useJudgementStream", () => {
  beforeEach(() => {
    vi.mocked(readSseStream).mockReset();
    vi.mocked(readSseStream).mockResolvedValue(undefined);
  });

  it("starts a single Judge generate with per-request Stale re-accept", async () => {
    const { result } = renderHook(() => useJudgementStream());
    await act(async () => {
      await result.current.start({
        sessionId: "session-1",
        node: "gap_judge",
        expectedVersion: 4,
        staleReaccept: true,
      });
    });
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/judgement/sessions/session-1/nodes/gap_judge/generate",
      expect.any(Function),
      {
        method: "POST",
        body: { expected_version: 4, stale_reaccept: true },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("starts run-pending namespaced by Workflow Node without starting Aggregator", async () => {
    const { result } = renderHook(() => useJudgementStream());
    await act(async () => {
      await result.current.startPending({
        sessionId: "session-1",
        expectedVersion: 8,
        staleReaccept: true,
      });
    });
    expect(readSseStream).toHaveBeenCalledWith(
      "/api/judgement/sessions/session-1/generate-pending",
      expect.any(Function),
      {
        method: "POST",
        body: { expected_version: 8, stale_reaccept: true },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("aborts the in-flight Judge stream", async () => {
    let abortSignal: AbortSignal | undefined;
    vi.mocked(readSseStream).mockImplementation(async (_path, _onEvent, init) => {
      abortSignal = (init as { signal?: AbortSignal }).signal;
      await new Promise(() => undefined);
    });
    const { result } = renderHook(() => useJudgementStream());
    act(() => {
      void result.current.startPending({
        sessionId: "session-1",
        expectedVersion: 2,
      });
    });
    await act(async () => {
      result.current.abort();
    });
    expect(abortSignal?.aborted).toBe(true);
  });
});
