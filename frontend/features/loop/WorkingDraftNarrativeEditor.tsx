"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  useGetSessionApiLoopSessionsSessionIdGet,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
} from "@/lib/api/generated/endpoints";
import { WorkflowNode } from "@/lib/api/generated/model";

import { WORKFLOW_NODE_LABELS } from "./catalog";
import { useLoopSessionSave } from "./loop-session-save";
import { type SaveStatus } from "./mutation-queue";
import { isVersionConflict, operationalError } from "./operational-error";

const AUTOSAVE_MS = 400;

type Conflict = {
  localText: string;
  serverText: string | null;
  serverNarrative: Record<string, unknown> | null;
  serverVersion: number;
};

function asNarrative(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return { ...(value as Record<string, unknown>) };
  }
  return {};
}

function narrativeText(narrative: Record<string, unknown>): string {
  return typeof narrative.text === "string" ? narrative.text : "";
}

function withNarrativeText(narrative: Record<string, unknown>, text: string): Record<string, unknown> {
  return { ...narrative, text };
}

const STATUS_LABEL: Record<SaveStatus, string | null> = {
  idle: null,
  saving: "Saving…",
  saved: "Saved",
  failed: "Save failed",
  conflict: "Resolve conflict",
};

export function WorkingDraftNarrativeEditor({
  sessionId,
  locked = false,
  embedded = false,
}: {
  sessionId: string;
  locked?: boolean;
  embedded?: boolean;
}) {
  const queryClient = useQueryClient();
  const sessionQuery = useGetSessionApiLoopSessionsSessionIdGet(sessionId);
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const { queue, status, setStatus } = useLoopSessionSave();
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<Conflict | null>(null);

  const session = sessionQuery.data?.status === 200 ? sessionQuery.data.data : null;

  useEffect(() => {
    if (session && !dirty && !conflict) {
      setText(narrativeText(asNarrative(session.working_draft_narrative)));
    }
  }, [conflict, dirty, session]);

  useEffect(() => {
    return () => {
      void queue.flush().catch(() => undefined);
    };
  }, [queue]);

  async function persistNarrative(
    localText: string,
    expectedVersion: number,
    baseNarrative: Record<string, unknown>,
  ) {
    const response = await patchWorkingDraft.mutateAsync({
      sessionId,
      data: {
        expected_version: expectedVersion,
        narrative: withNarrativeText(baseNarrative, localText),
      },
    });
    if (response.status === 200) {
      setText(narrativeText(asNarrative(response.data.working_draft_narrative)));
      queryClient.setQueryData(
        getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        response,
      );
      setDirty(false);
    }
    return response;
  }

  async function handleSaveError(error: unknown, localText: string, expectedVersion: number) {
    if (!isVersionConflict(error)) {
      return;
    }
    const typedError = operationalError(error);
    try {
      const refreshed = await sessionQuery.refetch();
      if (refreshed.data?.status === 200) {
        const serverNarrative = asNarrative(refreshed.data.data.working_draft_narrative);
        setConflict({
          localText,
          serverText: narrativeText(serverNarrative),
          serverNarrative,
          serverVersion: refreshed.data.data.version,
        });
        return;
      }
    } catch {
      // Resolution remains suspended until the Account retries this read.
    }
    setConflict({
      localText,
      serverText: null,
      serverNarrative: null,
      serverVersion: typedError?.current_version ?? expectedVersion,
    });
  }

  function scheduleSave(nextText: string) {
    if (!session || conflict || locked) return;
    const expectedVersion = session.version;
    const baseNarrative = asNarrative(session.working_draft_narrative);
    void queue
      .schedule(async () => {
        try {
          return await persistNarrative(nextText, expectedVersion, baseNarrative);
        } catch (error) {
          await handleSaveError(error, nextText, expectedVersion);
          throw error;
        }
      }, AUTOSAVE_MS)
      .catch(() => undefined);
  }

  async function retryConflictLoad() {
    if (!conflict) return;
    try {
      const refreshed = await sessionQuery.refetch();
      if (refreshed.data?.status === 200) {
        const serverNarrative = asNarrative(refreshed.data.data.working_draft_narrative);
        setConflict({
          localText: conflict.localText,
          serverText: narrativeText(serverNarrative),
          serverNarrative,
          serverVersion: refreshed.data.data.version,
        });
      }
    } catch {
      setStatus("conflict");
    }
  }

  async function keepLocalNarrative() {
    if (!conflict || conflict.serverNarrative === null) return;
    const localText = conflict.localText;
    const serverVersion = conflict.serverVersion;
    const serverNarrative = conflict.serverNarrative;
    setConflict(null);
    queue.resumeAfterConflict();
    try {
      await queue.enqueue(() => persistNarrative(localText, serverVersion, serverNarrative));
    } catch (error) {
      await handleSaveError(error, localText, serverVersion);
    }
  }

  function useServerNarrative() {
    if (!conflict || conflict.serverNarrative === null) return;
    setText(conflict.serverText ?? "");
    setDirty(false);
    setConflict(null);
    queue.resumeAfterConflict();
    setStatus("saved");
  }

  if (sessionQuery.isLoading) {
    return <p className="text-muted-foreground">Loading Working Draft…</p>;
  }
  if (!session) {
    return (
      <div role="alert" className="rounded-md border border-destructive bg-card p-4">
        <p>We could not load this Working Draft.</p>
        <Button className="mt-3" variant="outline" onClick={() => sessionQuery.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const interpretation = session.working_draft_node === WorkflowNode.idea_interpretation;
  const editor = (
          <label className="grid gap-2 text-sm font-medium">
            Working Draft narrative
            <Textarea
              disabled={locked || status === "conflict"}
              placeholder={interpretation ? "Correct the grilling transcript" : "Working Draft narrative"}
              value={text}
              onChange={(event) => {
                const nextText = event.target.value;
                setText(nextText);
                setDirty(true);
                scheduleSave(nextText);
              }}
            />
          </label>
  );
  const statusBlock = (
    <>
          {STATUS_LABEL[status] ? (
            <p
              className={`mt-3 text-sm ${status === "failed" ? "text-destructive" : "text-muted-foreground"}`}
              role={status === "failed" ? "alert" : "status"}
            >
              {STATUS_LABEL[status]}
            </p>
          ) : null}
          {status === "failed" && patchWorkingDraft.error ? (
            <p className="mt-1 text-sm text-destructive">{getApiErrorMessage(patchWorkingDraft.error)}</p>
          ) : null}
    </>
  );

  const conflictCard = conflict ? (
        <Card className="mt-6 border-pending" role="alert">
          <CardHeader>
            <CardTitle>Working Draft conflict</CardTitle>
            <CardDescription>
              Another request changed this Loop Session. Choose which Working Draft text to keep.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-sm font-medium">Your Working Draft</dt>
                <dd className="mt-1 whitespace-pre-wrap break-words">{conflict.localText || "Empty"}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium">Current server Working Draft</dt>
                <dd className="mt-1 whitespace-pre-wrap break-words">
                  {conflict.serverText === null
                    ? "Could not load the current server Working Draft."
                    : conflict.serverText || "Empty"}
                </dd>
              </div>
            </dl>
            <div className="mt-5 flex flex-wrap gap-3">
              {conflict.serverNarrative === null ? (
                <Button variant="outline" onClick={retryConflictLoad}>
                  Retry loading server Working Draft
                </Button>
              ) : null}
              <Button disabled={conflict.serverNarrative === null} onClick={keepLocalNarrative}>
                Keep my Working Draft
              </Button>
              <Button
                disabled={conflict.serverNarrative === null}
                variant="outline"
                onClick={useServerNarrative}
              >
                Use server Working Draft
              </Button>
            </div>
          </CardContent>
        </Card>
  ) : null;

  if (embedded) {
    return (
      <div>
        {editor}
        {statusBlock}
        {conflictCard}
      </div>
    );
  }

  return (
    <div>
      <Card>
        <CardHeader>
          <CardTitle>Working Draft</CardTitle>
          <CardDescription>
            {interpretation
              ? "Correct the grilling transcript. Confirm freezes this text."
              : `Narrative for ${WORKFLOW_NODE_LABELS[session.working_draft_node]}. Unknown fields are preserved.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {editor}
          {statusBlock}
        </CardContent>
      </Card>
      {conflictCard}
    </div>
  );
}
