"use client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { GrillingClusterForm } from "./GrillingClusterForm";
import type { GrillingTurn, IdeaTurn } from "./turns";
import { modelTurnBefore } from "./turns";

function answerLabel(answer: { option: string } | { other: string }): string {
  return "option" in answer ? answer.option : `Other: ${answer.other}`;
}

function AccountIdeaView({
  turn,
  editing,
  locked,
  dirty,
  onEdit,
  onCancel,
  onSave,
  onChange,
}: {
  turn: IdeaTurn;
  editing: boolean;
  locked: boolean;
  dirty: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onChange: (text: string) => void;
}) {
  return (
    <li>
      <p className="mb-1 text-xs font-medium text-muted-foreground">Account</p>
      <div className="rounded-md border bg-muted px-3 py-3">
        {editing ? (
          <div className="grid gap-3">
            <Textarea aria-label="Edit idea" value={turn.text} onChange={(event) => onChange(event.target.value)} />
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={onCancel}>
                Cancel
              </Button>
              <Button disabled={!dirty} type="button" onClick={onSave}>
                Save
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid gap-3">
            <p className="whitespace-pre-wrap break-words text-sm">{turn.text}</p>
            <Button
              disabled={locked}
              size="sm"
              type="button"
              variant="outline"
              className="justify-self-start"
              onClick={onEdit}
            >
              Edit
            </Button>
          </div>
        )}
      </div>
    </li>
  );
}

export function GrillingTurns({
  turns,
  generating,
  preview,
  locked,
  editingIndex,
  draftTurn,
  dirty,
  onEdit,
  onCancel,
  onSave,
  onDraftChange,
}: {
  turns: GrillingTurn[];
  generating: boolean;
  preview: string;
  locked: boolean;
  editingIndex: number | null;
  draftTurn: GrillingTurn | null;
  dirty: boolean;
  onEdit: (index: number) => void;
  onCancel: () => void;
  onSave: (turn?: GrillingTurn) => void;
  onDraftChange: (turn: GrillingTurn) => void;
}) {
  const last = turns.at(-1);
  const hideLastQuestions = last?.role === "model" && last.questions.length > 0 && !generating;

  return (
    <ol className="grid gap-3" aria-label="Grilling transcript">
      {turns.map((turn, index) => {
        const isLastModel = hideLastQuestions && index === turns.length - 1;
        const current = editingIndex === index && draftTurn ? draftTurn : turn;
        if (current.role === "account" && current.kind === "idea") {
          return (
            <AccountIdeaView
              key={`idea-${index}`}
              dirty={editingIndex === index && dirty}
              editing={editingIndex === index}
              locked={locked || (editingIndex !== null && editingIndex !== index)}
              turn={current}
              onCancel={onCancel}
              onChange={(text) => onDraftChange({ ...current, text })}
              onEdit={() => onEdit(index)}
              onSave={onSave}
            />
          );
        }
        if (current.role === "account" && current.kind === "answers") {
          const cluster = modelTurnBefore(turns, index);
          return (
            <li key={`answers-${index}`}>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Account</p>
              <div className="rounded-md border bg-muted px-3 py-3">
                {editingIndex === index && cluster ? (
                  <GrillingClusterForm
                    cancelLabel="Cancel"
                    initialAnswers={current.answers}
                    questions={cluster.questions}
                    submitDisabled={false}
                    submitLabel="Save"
                    disabled={false}
                    onCancel={onCancel}
                    onSubmit={(answers) => {
                      onSave({ role: "account", kind: "answers", answers });
                    }}
                  />
                ) : (
                  <div className="grid gap-3">
                    <ul className="grid gap-1 text-sm">
                      {current.answers.map((answer, answerIndex) => (
                        <li key={answerIndex}>{answerLabel(answer)}</li>
                      ))}
                    </ul>
                    <Button
                      disabled={locked || (editingIndex !== null && editingIndex !== index)}
                      size="sm"
                      type="button"
                      variant="outline"
                      className="justify-self-start"
                      onClick={() => onEdit(index)}
                    >
                      Edit
                    </Button>
                  </div>
                )}
              </div>
            </li>
          );
        }
        return (
          <li key={`model-${index}`}>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Questions</p>
            <div className="rounded-md border bg-card px-3 py-3">
              {current.preamble ? (
                <p className="font-serif text-base whitespace-pre-wrap break-words text-navy">
                  {current.preamble}
                </p>
              ) : null}
              {!isLastModel && current.questions.length > 0 ? (
                <ol className="mt-3 grid gap-2 text-sm">
                  {current.questions.map((question) => (
                    <li key={question.text}>{question.text}</li>
                  ))}
                </ol>
              ) : null}
            </div>
          </li>
        );
      })}
      {generating ? (
        <li>
          <p className="mb-1 text-xs font-medium text-in-progress">In progress</p>
          <div className="rounded-md border border-in-progress/40 bg-card px-3 py-3">
            <p className="font-serif text-base whitespace-pre-wrap break-words text-navy">
              {preview.trim() ? preview : "…"}
            </p>
          </div>
        </li>
      ) : null}
    </ol>
  );
}
