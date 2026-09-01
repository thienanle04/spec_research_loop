"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
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
import type { LoopSessionResponse } from "@/lib/api/generated/model";

type TitleSaveStatus = "idle" | "saving" | "saved" | "failed";

const TITLE_SAVED_MS = 2000;

const STATUS_LABEL: Record<TitleSaveStatus, string | null> = {
  idle: null,
  saving: "Saving…",
  saved: "Saved",
  failed: "Save failed",
};

function displayTitle(title: string | null | undefined): string {
  return title?.trim() ? title : "Untitled Loop Session";
}

export function LoopSessionTitleEditor({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const sessionQuery = useGetSessionApiLoopSessionsSessionIdGet(sessionId);
  const patchTitle = usePatchSessionApiLoopSessionsSessionIdPatch();
  const inputRef = useRef<HTMLInputElement>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [title, setTitle] = useState("");
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<TitleSaveStatus>("idle");

  const session = sessionQuery.data?.status === 200 ? sessionQuery.data.data : null;

  useEffect(() => {
    if (session && !dirty) {
      setTitle(session.title ?? "");
    }
  }, [dirty, session]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  useEffect(() => {
    return () => {
      if (savedTimer.current) {
        clearTimeout(savedTimer.current);
      }
    };
  }, []);

  function markSaved() {
    setStatus("saved");
    if (savedTimer.current) {
      clearTimeout(savedTimer.current);
    }
    savedTimer.current = setTimeout(() => setStatus("idle"), TITLE_SAVED_MS);
  }

  function enterEdit() {
    setEditing(true);
  }

  function cancelEdit() {
    if (status === "saving") return;
    setTitle(session?.title ?? "");
    setDirty(false);
    setEditing(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || status === "saving") return;
    const localTitle = title;
    setStatus("saving");
    try {
      const response = await patchTitle.mutateAsync({
        sessionId,
        data: { title: localTitle.trim() ? localTitle : null },
      });
      if (response.status === 200) {
        setTitle(response.data.title ?? "");
        queryClient.setQueryData(
          getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
          (
            current:
              | { status: number; data: LoopSessionResponse }
              | undefined,
          ) => {
            if (current?.status === 200) {
              return {
                ...current,
                data: {
                  ...current.data,
                  title: response.data.title,
                  updated_at: response.data.updated_at,
                },
              };
            }
            return response;
          },
        );
        await queryClient.invalidateQueries({
          queryKey: getListSessionsApiLoopSessionsGetQueryKey(),
        });
        setDirty(false);
        setEditing(false);
        markSaved();
        return;
      }
      setStatus("failed");
    } catch {
      setStatus("failed");
    }
  }

  function statusMessage() {
    if (!STATUS_LABEL[status]) return null;
    return (
      <p
        className={`text-sm ${status === "failed" ? "text-destructive" : "text-muted-foreground"}`}
        role={status === "failed" ? "alert" : "status"}
      >
        {STATUS_LABEL[status]}
      </p>
    );
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
      {editing ? (
        <form className="flex min-w-0 flex-wrap items-center gap-2" onSubmit={submit}>
          <label className="grid min-w-0 flex-1 gap-1 text-sm font-medium">
            <span className="sr-only">Loop Session title</span>
            <Input
              ref={inputRef}
              aria-label="Loop Session title"
              className="h-9 font-serif text-base"
              disabled={status === "saving"}
              maxLength={200}
              placeholder="Untitled Loop Session"
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                setDirty(true);
              }}
            />
          </label>
          <Button type="submit" size="sm" disabled={!dirty || status === "saving"}>
            Save
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={status === "saving"}
            onClick={cancelEdit}
          >
            Cancel
          </Button>
          {status === "saving" || status === "failed" ? statusMessage() : null}
        </form>
      ) : (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <button
            type="button"
            className="min-w-0 flex-1 text-center font-serif text-xl leading-snug text-foreground underline-offset-4 hover:underline"
            onClick={enterEdit}
          >
            {displayTitle(session.title)}
          </button>
          {statusMessage()}
          <Button type="button" size="sm" variant="outline" onClick={enterEdit}>
            Edit
          </Button>
        </div>
      )}
      {status === "failed" && patchTitle.error ? (
        <p className="mt-1 text-sm text-destructive">{getApiErrorMessage(patchTitle.error)}</p>
      ) : null}
    </div>
  );
}
