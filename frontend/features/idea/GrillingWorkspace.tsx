"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { WorkingDraftCardCanvas } from "@/features/loop/WorkingDraftCardCanvas";
import {
  getGetSessionApiLoopSessionsSessionIdGetQueryKey,
  usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch,
} from "@/lib/api/generated/endpoints";
import { WorkflowNode, type LoopSessionResponse } from "@/lib/api/generated/model";

import { GenerateError, IdeaGeneratePanel } from "./IdeaGeneratePanel";
import { GrillingClusterForm } from "./GrillingClusterForm";
import { GrillingTurns } from "./GrillingTurns";
import {
  clustersAnswered,
  hasIdea,
  isExhaustedHint,
  lastIsAccount,
  parseTurns,
  unansweredCluster,
  withEditedTurn,
  type GrillingAnswer,
  type GrillingTurn,
} from "./turns";

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
}: {
  session: LoopSessionResponse;
  sessionId: string;
  locked: boolean;
  generating: boolean;
  preview: string;
  error: string | null;
  saveBlocked: boolean;
  showGenerateCards: boolean;
  onGenerate: (payload: { message?: string; answers?: GrillingAnswer[] }) => void;
  onEditState: (state: { editing: boolean; dirty: boolean }) => void;
}) {
  const queryClient = useQueryClient();
  const patchWorkingDraft = usePatchWorkingDraftApiLoopSessionsSessionIdWorkingDraftPatch();
  const narrative = session.working_draft_narrative as Record<string, unknown>;
  const turns = parseTurns(narrative);
  const interpretation = session.working_draft_node === WorkflowNode.idea_interpretation;
  const cluster = unansweredCluster(turns);
  const ideaReady = hasIdea(turns);
  const recluster = interpretation && ideaReady && lastIsAccount(turns) && !cluster;
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
    const edited = nextTurn ?? draftTurn;
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

  return (
    <div className="grid gap-4">
      {showTurns ? (
        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-navy">Transcript</CardTitle>
            <CardDescription>
              Grilling Questions are not Cards. Confirm freezes this turn list.
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
      {interpretation && cluster && !generating ? (
        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-navy">Send</CardTitle>
            <CardDescription>
              Answer every Grilling Question, then Send. Confirm when you have a shared understanding.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <GrillingClusterForm
              disabled={saveBlocked || editing}
              questions={cluster}
              submitLabel="Send"
              onSubmit={(answers) => onGenerate({ answers })}
            />
            <GenerateError error={error} />
          </CardContent>
        </Card>
      ) : null}
      {recluster && !generating ? (
        <IdeaGeneratePanel
          error={error}
          generating={generating}
          mode="recluster"
          saveBlocked={saveBlocked || editing}
          onGenerate={() => onGenerate({})}
        />
      ) : null}
      {!interpretation && generating ? (
        <p role="status" className="text-sm text-in-progress">
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
    <p role="status" className="text-sm text-pending">
      The model thinks questioning is exhausted. Confirm is still your Decision.
    </p>
  );
}

export function interpretationConfirmable(narrative: Record<string, unknown>): boolean {
  return clustersAnswered(parseTurns(narrative));
}
