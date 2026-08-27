"use client";

import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getApiErrorMessage } from "@/lib/api/config";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  getListSessionsApiLoopSessionsGetQueryKey,
  useGetSessionApiLoopSessionsSessionIdGet,
  usePatchSessionApiLoopSessionsSessionIdPatch,
} from "@/lib/api/generated/endpoints";

import { useLoopSessionSave } from "./loop-session-save";
import { type SaveStatus } from "./mutation-queue";
import { isVersionConflict, operationalError } from "./operational-error";

type Conflict = {
  localTitle: string;
  serverTitle: string | null;
  serverVersion: number;
};

const STATUS_LABEL: Record<SaveStatus, string | null> = {
  idle: null,
  saving: "Saving…",
  saved: "Saved",
  failed: "Save failed",
  conflict: "Resolve conflict",
};

export function LoopSessionTitleEditor({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const sessionQuery = useGetSessionApiLoopSessionsSessionIdGet(sessionId);
  const patchTitle = usePatchSessionApiLoopSessionsSessionIdPatch();
  const { queue, status, setStatus } = useLoopSessionSave();
  const [title, setTitle] = useState("");
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<Conflict | null>(null);

  const session = sessionQuery.data?.status === 200 ? sessionQuery.data.data : null;

  useEffect(() => {
    if (session && !dirty && !conflict) {
      setTitle(session.title ?? "");
    }
  }, [conflict, dirty, session]);

  async function saveTitle(localTitle: string, expectedVersion: number) {
    try {
      const response = await queue.enqueue(() =>
        patchTitle.mutateAsync({
          sessionId,
          data: {
            title: localTitle.trim() ? localTitle : null,
            expected_version: expectedVersion,
          },
        }),
      );
      if (response.status === 200) {
        setTitle(response.data.title ?? "");
        queryClient.setQueryData(
          getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
          response,
        );
        await queryClient.invalidateQueries({
          queryKey: getListSessionsApiLoopSessionsGetQueryKey(),
        });
        setDirty(false);
      }
    } catch (error) {
      if (!isVersionConflict(error)) {
        return;
      }
      const typedError = operationalError(error);
      try {
        const refreshed = await sessionQuery.refetch();
        if (refreshed.data?.status === 200) {
          setConflict({
            localTitle,
            serverTitle: refreshed.data.data.title ?? "",
            serverVersion: refreshed.data.data.version,
          });
          return;
        }
      } catch {
        // Resolution remains suspended until the Account retries this read.
      }
      setConflict({
        localTitle,
        serverTitle: null,
        serverVersion: typedError?.current_version ?? expectedVersion,
      });
    }
  }

  async function retryConflictLoad() {
    if (!conflict) return;
    try {
      const refreshed = await sessionQuery.refetch();
      if (refreshed.data?.status === 200) {
        setConflict({
          localTitle: conflict.localTitle,
          serverTitle: refreshed.data.data.title ?? "",
          serverVersion: refreshed.data.data.version,
        });
      }
    } catch {
      setStatus("conflict");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || conflict) return;
    await saveTitle(title, session.version);
  }

  async function keepLocalTitle() {
    if (!conflict || conflict.serverTitle === null) return;
    const resolution = conflict;
    setConflict(null);
    queue.resumeAfterConflict();
    await saveTitle(resolution.localTitle, resolution.serverVersion);
  }

  function useServerTitle() {
    if (!conflict || conflict.serverTitle === null) return;
    setTitle(conflict.serverTitle);
    setDirty(false);
    setConflict(null);
    queue.resumeAfterConflict();
    setStatus("saved");
  }

  if (sessionQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading Loop Session…</p>;
  }
  if (!session) {
    return (
      <div role="alert" className="rounded-md border border-destructive bg-card p-3">
        <p>We could not load this Loop Session.</p>
        <Button className="mt-3" variant="outline" size="sm" onClick={() => sessionQuery.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="min-w-0">
      <form className="flex min-w-0 flex-wrap items-center gap-2" onSubmit={submit}>
        <label className="grid min-w-0 flex-1 gap-1 text-sm font-medium">
          <span className="sr-only">Loop Session title</span>
          <Input
            aria-label="Loop Session title"
            className="h-9 font-serif text-base"
            disabled={status === "saving" || status === "conflict"}
            maxLength={200}
            placeholder="Untitled Loop Session"
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              setDirty(true);
            }}
          />
        </label>
        <Button
          type="submit"
          size="sm"
          disabled={!dirty || status === "saving" || status === "conflict"}
        >
          Save title
        </Button>
        {STATUS_LABEL[status] ? (
          <p
            className={`text-sm ${status === "failed" ? "text-destructive" : "text-muted-foreground"}`}
            role={status === "failed" ? "alert" : "status"}
          >
            {STATUS_LABEL[status]}
          </p>
        ) : null}
      </form>
      {status === "failed" && patchTitle.error ? (
        <p className="mt-1 text-sm text-destructive">{getApiErrorMessage(patchTitle.error)}</p>
      ) : null}

      {conflict ? (
        <div className="mt-3 rounded-md border border-pending bg-card p-3" role="alert">
          <p className="text-sm font-medium">Title conflict</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Another request changed this Loop Session. Choose which title to keep.
          </p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-sm font-medium">Your title</dt>
              <dd className="mt-1 break-words">{conflict.localTitle || "Untitled Loop Session"}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium">Current server title</dt>
              <dd className="mt-1 break-words">
                {conflict.serverTitle === null
                  ? "Could not load the current server title."
                  : conflict.serverTitle || "Untitled Loop Session"}
              </dd>
            </div>
          </dl>
          <div className="mt-3 flex flex-wrap gap-2">
            {conflict.serverTitle === null ? (
              <Button variant="outline" size="sm" onClick={retryConflictLoad}>
                Retry loading server title
              </Button>
            ) : null}
            <Button disabled={conflict.serverTitle === null} size="sm" onClick={keepLocalTitle}>
              Keep my title
            </Button>
            <Button
              disabled={conflict.serverTitle === null}
              variant="outline"
              size="sm"
              onClick={useServerTitle}
            >
              Use server title
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
