"use client";

import type { ReactNode } from "react";
import { LoaderCircle, MessageSquare, Pencil, User, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { GrillingClusterForm } from "./GrillingClusterForm";
import type { GrillingTurn, IdeaTurn } from "./turns";
import { modelTurnBefore } from "./turns";

function answerLabel(answer: { option: string } | { other: string }): string {
  return "option" in answer ? answer.option : `Other: ${answer.other}`;
}

function TurnFrame({
  label,
  icon: Icon,
  iconClassName,
  tone = "text-muted-foreground",
  surface = "border bg-muted",
  busy,
  children,
}: {
  label: string;
  icon: LucideIcon;
  iconClassName?: string;
  tone?: string;
  surface?: string;
  busy?: boolean;
  children: ReactNode;
}) {
  return (
    <li aria-busy={busy || undefined}>
      <p className={cn("mb-1 flex items-center gap-1.5 text-xs font-medium", tone)}>
        <Icon aria-hidden="true" className={cn("size-3.5", iconClassName)} />
        {label}
      </p>
      <div className={cn("rounded-md px-3 py-3", surface)}>{children}</div>
    </li>
  );
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
    <TurnFrame icon={User} label="Account">
      {editing ? (
        <div className="grid gap-3">
          <label className="grid gap-2 text-sm font-medium">
            Research idea
            <Textarea
              aria-label="Edit idea"
              value={turn.text}
              onChange={(event) => onChange(event.target.value)}
            />
          </label>
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
            <Pencil aria-hidden="true" />
            Edit
          </Button>
        </div>
      )}
    </TurnFrame>
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
        const editLocked = locked || (editingIndex !== null && editingIndex !== index);
        if (current.role === "account" && current.kind === "idea") {
          return (
            <AccountIdeaView
              key={`idea-${index}`}
              dirty={editingIndex === index && dirty}
              editing={editingIndex === index}
              locked={editLocked}
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
            <TurnFrame key={`answers-${index}`} icon={User} label="Account">
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
                  <ul className="grid gap-3">
                    {current.answers.map((answer, answerIndex) => {
                      const question = cluster?.questions[answerIndex];
                      return (
                        <li key={`${question?.text ?? "answer"}-${answerIndex}`} className="grid gap-1">
                          {question ? (
                            <p className="font-serif text-sm text-navy">{question.text}</p>
                          ) : null}
                          <p className="text-sm">{answerLabel(answer)}</p>
                        </li>
                      );
                    })}
                  </ul>
                  <Button
                    disabled={editLocked}
                    size="sm"
                    type="button"
                    variant="outline"
                    className="justify-self-start"
                    onClick={() => onEdit(index)}
                  >
                    <Pencil aria-hidden="true" />
                    Edit
                  </Button>
                </div>
              )}
            </TurnFrame>
          );
        }
        return (
          <TurnFrame
            key={`model-${index}`}
            icon={MessageSquare}
            label="Questions"
            surface="border bg-card"
          >
            {current.preamble ? (
              <p className="font-serif text-base whitespace-pre-wrap break-words text-navy">
                {current.preamble}
              </p>
            ) : null}
            {isLastModel ? (
              <p className="mt-3 text-sm text-muted-foreground">
                Open cluster — answer every Grilling Question below.
              </p>
            ) : current.questions.length > 0 ? (
              <ol className="mt-3 grid gap-2 text-sm">
                {current.questions.map((question) => (
                  <li key={question.text}>{question.text}</li>
                ))}
              </ol>
            ) : null}
          </TurnFrame>
        );
      })}
      {generating ? (
        <TurnFrame
          busy
          icon={LoaderCircle}
          iconClassName="animate-spin"
          label="Receiving"
          surface="border border-in-progress/40 bg-card"
          tone="text-in-progress"
        >
          <p className="font-serif text-base whitespace-pre-wrap break-words text-navy">
            {preview.trim() ? preview : "Waiting for the next Grilling Questions."}
          </p>
        </TurnFrame>
      ) : null}
    </ol>
  );
}
