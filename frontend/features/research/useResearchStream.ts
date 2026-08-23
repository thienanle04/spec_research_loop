"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readSseStream, SseHttpError } from "@/lib/api/sse";

import type { ResearchStreamEvent } from "./types";

type StartOptions = {
  sessionId: string;
  node: "research_inputs" | "related_work" | "gap";
  expectedVersion: number;
  maxResults?: number;
  onEvent?: (event: ResearchStreamEvent) => void;
};

function isStreamEvent(value: unknown): value is ResearchStreamEvent {
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
  return error instanceof Error ? error.message : "Research generation failed";
}

export function useResearchStream() {
  const controllerRef = useRef<AbortController | null>(null);
  const requestRef = useRef(0);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const abort = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    requestRef.current += 1;
    setRunning(false);
    setProgressMessage("Research generation stopped.");
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const start = useCallback(async (options: StartOptions) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++requestRef.current;
    setRunning(true);
    setProgress(0);
    setProgressMessage("Starting research generation…");
    setWarnings([]);
    setError(null);

    try {
      await readSseStream(
        `/api/research/sessions/${options.sessionId}/nodes/${options.node}/generate`,
        (raw) => {
          if (requestRef.current !== requestId || !isStreamEvent(raw)) return;
          if (raw.type === "progress") {
            setProgress(raw.pct);
            setProgressMessage(raw.message);
          } else if (raw.type === "warning") {
            setWarnings((current) => [...current, raw.message]);
          } else if (raw.type === "error") {
            setError(raw.message);
          }
          options.onEvent?.(raw);
        },
        {
          method: "POST",
          body: {
            expected_version: options.expectedVersion,
            ...(options.maxResults ? { max_results: options.maxResults } : {}),
          },
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
  }, []);

  return { running, progress, progressMessage, warnings, error, start, abort };
}
