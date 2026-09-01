"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readSseStream, SseHttpError } from "@/lib/api/sse";

import type { JudgeNode, JudgementStreamEvent } from "./types";

type StartOptions = {
  sessionId: string;
  node: JudgeNode;
  expectedVersion: number;
  staleReaccept?: boolean;
  onEvent?: (event: JudgementStreamEvent) => void;
};

type PendingStartOptions = {
  sessionId: string;
  expectedVersion: number;
  staleReaccept?: boolean;
  onEvent?: (event: JudgementStreamEvent) => void;
};

function isStreamEvent(value: unknown): value is JudgementStreamEvent {
  return Boolean(value && typeof value === "object" && "type" in value);
}

function streamErrorMessage(error: unknown): string {
  if (error instanceof SseHttpError) {
    const payload = error.payload;
    if (payload && typeof payload === "object" && "detail" in payload) {
      const detail = (payload as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    if (error.status === 401) return "Your sign-in expired. Sign in again and retry.";
    if (error.status === 409) return "The Loop Session changed. Reload current data and retry.";
  }
  return error instanceof Error ? error.message : "Judge generation failed";
}

export function useJudgementStream() {
  const controllerRef = useRef<AbortController | null>(null);
  const requestRef = useRef(0);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const abort = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    requestRef.current += 1;
    setRunning(false);
    setProgressMessage("Judge generation stopped.");
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const runStream = useCallback(
    async (
      path: string,
      body: { expected_version: number; stale_reaccept?: boolean },
      onEvent?: (event: JudgementStreamEvent) => void,
    ) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const requestId = ++requestRef.current;
      setRunning(true);
      setProgress(0);
      setProgressMessage("Starting Judge…");
      setError(null);

      try {
        await readSseStream(
          path,
          (raw) => {
            if (requestRef.current !== requestId || !isStreamEvent(raw)) return;
            if (raw.type === "progress") {
              setProgress(raw.pct);
              setProgressMessage(raw.message);
            } else if (raw.type === "error") {
              setError(raw.message);
            }
            onEvent?.(raw);
          },
          {
            method: "POST",
            body,
            signal: controller.signal,
          },
        );
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === "AbortError") && requestRef.current === requestId) {
          setError(streamErrorMessage(caught));
        }
      } finally {
        if (requestRef.current === requestId) {
          controllerRef.current = null;
          setRunning(false);
        }
      }
    },
    [],
  );

  const start = useCallback(async (options: StartOptions) => {
    await runStream(
      `/api/judgement/sessions/${options.sessionId}/nodes/${options.node}/generate`,
      {
        expected_version: options.expectedVersion,
        ...(options.staleReaccept ? { stale_reaccept: true } : {}),
      },
      options.onEvent,
    );
  }, [runStream]);

  const startPending = useCallback(async (options: PendingStartOptions) => {
    await runStream(
      `/api/judgement/sessions/${options.sessionId}/generate-pending`,
      {
        expected_version: options.expectedVersion,
        ...(options.staleReaccept ? { stale_reaccept: true } : {}),
      },
      options.onEvent,
    );
  }, [runStream]);

  return { running, progress, progressMessage, error, start, startPending, abort };
}
