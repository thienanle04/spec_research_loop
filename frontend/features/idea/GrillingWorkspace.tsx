"use client";

import { useEffect, useState, type ReactNode } from "react";
import { LoaderCircle, MessageSquare, Send } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { WorkingDraftCardCanvas } from "@/features/loop/WorkingDraftCardCanvas";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
} from "@/lib/api/generated/endpoints";
import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { GenerateError, IdeaGeneratePanel } from "./IdeaGeneratePanel";
import {
  GrillingQuestionFields,
  answersComplete,
  initialOthers,
  initialPicks,
  toAnswers,
} from "./GrillingClusterForm";
import { GrillingTurns } from "./GrillingTurns";
import {
  hasIdea,
  isExhaustedHint,
  lastIsAccount,
  parseFrame,
  parseTurns,
  unansweredCluster,
  withEditedTurn,
  type GrillingAnswer,
  type GrillingQuestion,
  type GrillingTurn,
} from "./turns";

export { interpretationConfirmable } from "./turns";

function isPatchTurn(value: unknown): value is GrillingTurn {
  return Boolean(value && typeof value === "object" && "role" in value);
}

export function GrillingWorkspace({
  session,
  sessionId,
  locked,
  generating,
  preview,
  error,
  saveBlocked,
  showGenerateCards,
  onGenerate,
  onEditState,
  frameActions,
}: {
  session: LoopSessionResponse;
  sessionId: string;
  locked: boolean;
  generating: boolean;
  preview: string;
  error: string | null;
  saveBlocked: boolean;
  showGenerateCards: boolean;
  onGenerate: (payload: { message?: string; answers?: GrillingAnswer[]; note?: string }) => void;
  onEditState: (state: { editing: boolean; dirty: boolean }) => void;
  frameActions?: ReactNode;
}) {
  const queryClient = useQueryClient();
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const narrative = session.working_draft_narrative as Record<string, unknown>;
  const turns = parseTurns(narrative);
  const frame = parseFrame(narrative);
  const interpretation = session.working_draft_node === WorkflowNode.idea_interpretation;
  const cluster = unansweredCluster(turns);
  const ideaReady = hasIdea(turns);
  const continueWithoutCluster = interpretation && ideaReady && !cluster;
  const noteRequired = continueWithoutCluster && !lastIsAccount(turns);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draftTurn, setDraftTurn] = useState<GrillingTurn | null>(null);

  const editing = editingIndex !== null;
  const dirty =
    editingIndex !== null &&
    draftTurn !== null &&
    JSON.stringify(draftTurn) !== JSON.stringify(turns[editingIndex]);

  useEffect(() => {
    onEditState({ editing, dirty });
  }, [dirty, editing, onEditState]);

  useEffect(() => {
    setEditingIndex(null);
    setDraftTurn(null);
  }, [session.version]);

  async function saveTurn(nextTurn?: GrillingTurn) {
    if (editingIndex === null) return;
    const edited = isPatchTurn(nextTurn) ? nextTurn : draftTurn;
    if (!edited) return;
    const nextTurns = withEditedTurn(turns, editingIndex, edited);
    const response = await patchWorkingDraft.mutateAsync({
      sessionId,
      data: {
        expected_version: session.version,
        narrative: { turns: nextTurns, exhausted: false },
      },
    });
    if (response.status === 200) {
      queryClient.setQueryData(
        getGetSessionApiLoopSessionsSessionIdGetQueryKey(sessionId),
        response,
      );
      setEditingIndex(null);
      setDraftTurn(null);
    }
  }

  const showTurns = ideaReady || generating;
  const editLocked = locked || generating;
  const showComposer = interpretation && ideaReady && !generating;

  return (
    <div className="grid gap-4">
      {interpretation && ideaReady ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="font-serif text-navy">Idea Frame</CardTitle>
              <CardDescription>
                Model restatement of the research idea. Confirm freezes this with the transcript.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="grid gap-1">
                <p className="text-sm font-medium">Intent</p>
                <p className="whitespace-pre-wrap break-words text-sm">
                  {frame.intent.trim() ? frame.intent : "Waiting for generate."}
                </p>
              </div>
              <div className="grid gap-1">
                <p className="text-sm font-medium">Problem</p>
                <p className="whitespace-pre-wrap break-words text-sm">
                  {frame.problem.trim() ? frame.problem : "Waiting for generate."}
                </p>
              </div>
              <div className="grid gap-1">
                <p className="text-sm font-medium">Research question</p>
                <p className="whitespace-pre-wrap break-words text-sm">
                  {frame.research_question.trim()
                    ? frame.research_question
                    : "Waiting for generate."}
                </p>
              </div>
            </CardContent>
          </Card>
          {frameActions}
        </>
      ) : null}
      {showTurns ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 font-serif text-navy">
              <MessageSquare aria-hidden="true" className="size-4" />
              Transcript
            </CardTitle>
            <CardDescription>
              Account replies, Account notes, and Grilling Questions. Confirm freezes this turn list.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <GrillingTurns
              dirty={dirty}
              draftTurn={draftTurn}
              editingIndex={editingIndex}
              generating={generating}
              locked={editLocked}
              preview={preview}
              turns={turns}
              onCancel={() => {
                setEditingIndex(null);
                setDraftTurn(null);
              }}
              onDraftChange={setDraftTurn}
              onEdit={(index) => {
                setEditingIndex(index);
                setDraftTurn(turns[index] ?? null);
              }}
              onSave={(turn) => void saveTurn(turn)}
            />
          </CardContent>
        </Card>
      ) : null}
      {interpretation && !ideaReady ? (
        <IdeaGeneratePanel
          error={error}
          generating={generating}
          mode="idea"
          saveBlocked={saveBlocked || editing}
          onGenerate={(message) => onGenerate({ message })}
        />
      ) : null}
      {showComposer ? (
        <>
          <GrillingExhaustedHint interpretation={interpretation} narrative={narrative} />
          <GrillingComposer
            cluster={cluster}
            disabled={saveBlocked || editing}
            error={error}
            noteRequired={noteRequired}
            onGenerate={onGenerate}
          />
        </>
      ) : null}
      {!interpretation && generating ? (
        <p role="status" aria-busy="true" className="flex items-center gap-2 text-sm text-in-progress">
          <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
          Generating Cards…
        </p>
      ) : null}
      {!interpretation && showGenerateCards && !generating ? (
        <IdeaGeneratePanel
          error={error}
          generating={generating}
          mode="cards"
          saveBlocked={saveBlocked}
          onGenerate={() => onGenerate({})}
        />
      ) : null}
      {!interpretation && !generating ? (
        <WorkingDraftCardCanvas layout="grilling" locked={locked} sessionId={sessionId} />
      ) : null}
    </div>
  );
}

function GrillingComposer({
  cluster,
  disabled,
  error,
  noteRequired,
  onGenerate,
}: {
  cluster: GrillingQuestion[] | null;
  disabled: boolean;
  error: string | null;
  noteRequired: boolean;
  onGenerate: (payload: { answers?: GrillingAnswer[]; note?: string }) => void;
}) {
  const [picks, setPicks] = useState(() => initialPicks(cluster ?? []));
  const [others, setOthers] = useState(() => initialOthers(cluster ?? []));
  const [note, setNote] = useState("");
  const clusterKey = cluster?.map((question) => question.text).join("|") ?? "";
  useEffect(() => {
    setPicks(initialPicks(cluster ?? []));
    setOthers(initialOthers(cluster ?? []));
  }, [clusterKey]);
  const questions = cluster ?? [];
  const complete = cluster ? answersComplete(questions, picks, others) : true;
  const trimmedNote = note.trim();
  const canSend =
    !disabled && (cluster ? complete || Boolean(trimmedNote) : noteRequired ? Boolean(trimmedNote) : true);

  function send() {
    if (!canSend) return;
    const payload: { answers?: GrillingAnswer[]; note?: string } = {};
    if (cluster && complete) {
      payload.answers = toAnswers(questions, picks, others);
    }
    if (trimmedNote) {
      payload.note = trimmedNote;
    }
    setNote("");
    onGenerate(payload);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-navy">
          {cluster ? "Grilling Questions" : "Continue"}
        </CardTitle>
        <CardDescription>
          {cluster
            ? "Answer the Grilling Questions, or write an Account note to skip, then Send."
            : noteRequired
              ? "Write an Account note to continue, or Confirm the Idea Frame."
              : "Send for the next Grilling Questions. An Account note is optional."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <GenerateError error={error} />
        {cluster ? (
          <GrillingQuestionFields
            attempted={false}
            disabled={disabled}
            formId="grilling-live"
            others={others}
            picks={picks}
            questions={questions}
            onOther={(index, value) =>
              setOthers((current) => current.map((item, i) => (i === index ? value : item)))
            }
            onPick={(index, value) =>
              setPicks((current) => current.map((item, i) => (i === index ? value : item)))
            }
          />
        ) : null}
        <div className="grid gap-2">
          <label htmlFor="account-note" className="text-sm font-medium">
            Account note
          </label>
          <Textarea
            id="account-note"
            disabled={disabled}
            placeholder="Add a free-form note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                send();
              }
            }}
          />
          <p className="text-sm text-muted-foreground">
            {cluster
              ? "A note without answers skips this cluster. Ctrl+Enter or Cmd+Enter to Send."
              : "Ctrl+Enter or Cmd+Enter to Send."}
          </p>
        </div>
        <Button disabled={!canSend} onClick={send}>
          <Send aria-hidden="true" />
          Send
        </Button>
      </CardContent>
    </Card>
  );
}

export function GrillingExhaustedHint({
  narrative,
  interpretation,
}: {
  narrative: Record<string, unknown>;
  interpretation: boolean;
}) {
  if (!interpretation || !isExhaustedHint(narrative)) {
    return null;
  }
  return (
    <div role="status" className="rounded-md border border-pending bg-card p-3">
      <p className="text-sm">
        The model thinks questioning is exhausted. Confirm is still your Decision.
      </p>
    </div>
  );
}
