"use client";

import { Fragment, useEffect, useId, useState, type ReactNode } from "react";
import { LoaderCircle, Pencil, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { OTHER, initialOthers, initialPicks } from "./GrillingClusterForm";
import type {
  AnswersTurn,
  GrillingAnswer,
  GrillingQuestion,
  GrillingTurn,
  IdeaTurn,
  ModelTurn,
  NoteTurn,
} from "./turns";
import { modelTurnBefore } from "./turns";

function answerLabel(answer: GrillingAnswer): string {
  return "option" in answer ? answer.option : `Other: ${answer.other}`;
}

function HistorySection({
  label,
  surface = "border bg-muted",
  children,
}: {
  label?: string;
  surface?: string;
  children: ReactNode;
}) {
  return (
    <li>
      {label ? (
        <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      ) : null}
      <div className={cn("rounded-md px-3 py-3", surface)}>{children}</div>
    </li>
  );
}

function ReceivingFrame({
  icon: Icon,
  iconClassName,
  label,
  children,
}: {
  icon: LucideIcon;
  iconClassName?: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <li aria-busy="true">
      <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-in-progress">
        <Icon aria-hidden="true" className={cn("size-3.5", iconClassName)} />
        {label}
      </p>
      <div className="rounded-md border border-in-progress/40 bg-card px-3 py-3">{children}</div>
    </li>
  );
}

function AccountTextView({
  label,
  ariaLabel,
  fieldLabel,
  turn,
  editing,
  locked,
  readOnly,
  dirty,
  onEdit,
  onCancel,
  onSave,
  onChange,
}: {
  label: string;
  ariaLabel: string;
  fieldLabel: string;
  turn: IdeaTurn | NoteTurn;
  editing: boolean;
  locked: boolean;
  readOnly: boolean;
  dirty: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onChange: (text: string) => void;
}) {
  if (editing) {
    return (
      <HistorySection label={label}>
        <div className="grid gap-3">
          <label className="grid gap-2 text-sm font-medium">
            {fieldLabel}
            <Textarea
              aria-label={ariaLabel}
              value={turn.text}
              onChange={(event) => onChange(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
            <Button disabled={!dirty} type="button" onClick={() => onSave()}>
              Save
            </Button>
          </div>
        </div>
      </HistorySection>
    );
  }

  return (
    <li>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
        <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 rounded-md border bg-muted px-3 py-3">
          <p className="whitespace-pre-wrap break-words text-sm">{turn.text}</p>
        </div>
        {readOnly ? null : (
          <Button
            disabled={locked}
            size="sm"
            type="button"
            variant="outline"
            className="shrink-0"
            onClick={onEdit}
          >
            <Pencil aria-hidden="true" />
            Edit
          </Button>
        )}
      </div>
    </li>
  );
}

/** Plain title — not <legend>; legend floats on the fieldset border and sits outside the card padding. */
function QuestionTitle({
  question,
  questionIndex,
  questionCount,
  id,
}: {
  question: GrillingQuestion;
  questionIndex: number;
  questionCount: number;
  id?: string;
}) {
  return (
    <p id={id} className="font-serif text-base text-navy">
      <span className="mr-2 font-sans text-xs font-medium text-muted-foreground">
        {questionIndex + 1}/{questionCount}
      </span>
      {question.text}
    </p>
  );
}

function SingleAnswerEditor({
  question,
  questionIndex,
  questionCount,
  answer,
  dirty,
  onChange,
  onCancel,
  onSave,
}: {
  question: GrillingQuestion;
  questionIndex: number;
  questionCount: number;
  answer: GrillingAnswer;
  dirty: boolean;
  onChange: (answer: GrillingAnswer) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const formId = `history-answer-${useId().replace(/:/g, "")}`;
  const fieldId = `${formId}-q`;
  const otherId = `${fieldId}-other`;
  const picks = initialPicks([question], [answer]);
  const others = initialOthers([question], [answer]);
  const selected = picks[0] ?? "";
  const otherText = others[0] ?? "";
  const incomplete = !selected || (selected === OTHER && !otherText.trim());

  const titleId = `${fieldId}-title`;

  return (
    <div className="grid gap-3">
      <div role="group" aria-labelledby={titleId} className="grid gap-2">
        <QuestionTitle
          id={titleId}
          question={question}
          questionCount={questionCount}
          questionIndex={questionIndex}
        />
        {question.options.map((option, optionIndex) => {
          const optionId = `${fieldId}-opt-${optionIndex}`;
          const isSelected = selected === option;
          return (
            <label
              key={optionId}
              htmlFor={optionId}
              className={cn(
                "flex min-h-11 cursor-pointer items-start gap-3 rounded-md border bg-card px-3 py-3 text-sm transition-colors duration-200",
                "hover:bg-muted",
                isSelected && "border-navy bg-muted",
              )}
            >
              <input
                id={optionId}
                type="radio"
                name={fieldId}
                className="mt-0.5 size-4 accent-navy"
                checked={isSelected}
                onChange={() => onChange({ option })}
              />
              <span>{option}</span>
            </label>
          );
        })}
        <label
          htmlFor={`${fieldId}-other-radio`}
          className={cn(
            "flex min-h-11 cursor-pointer items-start gap-3 rounded-md border bg-card px-3 py-3 text-sm transition-colors duration-200",
            "hover:bg-muted",
            selected === OTHER && "border-navy bg-muted",
          )}
        >
          <input
            id={`${fieldId}-other-radio`}
            type="radio"
            name={fieldId}
            className="mt-0.5 size-4 accent-navy"
            checked={selected === OTHER}
            onChange={() => onChange({ other: otherText })}
          />
          <span>Other</span>
        </label>
        {selected === OTHER ? (
          <div className="grid gap-2 pl-1">
            <label htmlFor={otherId} className="text-sm font-medium">
              Your answer
            </label>
            <Textarea
              id={otherId}
              value={otherText}
              onChange={(event) => onChange({ other: event.target.value })}
            />
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button disabled={!dirty || incomplete} type="button" onClick={() => onSave()}>
          Save
        </Button>
      </div>
    </div>
  );
}

function AnsweredClusterPairs({
  turnIndex,
  cluster,
  answers,
  editing,
  locked,
  readOnly,
  dirty,
  onEdit,
  onCancel,
  onSave,
  onDraftChange,
}: {
  turnIndex: number;
  cluster: ModelTurn | null;
  answers: AnswersTurn;
  editing: boolean;
  locked: boolean;
  readOnly: boolean;
  dirty: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onDraftChange: (turn: AnswersTurn) => void;
}) {
  const [editingAnswerIndex, setEditingAnswerIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!editing) {
      setEditingAnswerIndex(null);
    }
  }, [editing]);

  const questions = cluster?.questions ?? [];
  const questionCount = Math.max(questions.length, answers.answers.length);

  return (
    <Fragment>
      {answers.answers.map((answer, answerIndex) => {
        const question = questions[answerIndex];
        const editingThis = editing && editingAnswerIndex === answerIndex;

        if (editingThis && question) {
          return (
            <li key={`pair-${turnIndex}-${answerIndex}`}>
              <div className="rounded-md border bg-muted px-3 py-3">
                <SingleAnswerEditor
                  answer={answer}
                  dirty={dirty}
                  question={question}
                  questionCount={questionCount}
                  questionIndex={answerIndex}
                  onCancel={onCancel}
                  onChange={(next) => {
                    onDraftChange({
                      role: "account",
                      kind: "answers",
                      answers: answers.answers.map((item, index) =>
                        index === answerIndex ? next : item,
                      ),
                    });
                  }}
                  onSave={onSave}
                />
              </div>
            </li>
          );
        }

        return (
          <li key={`pair-${turnIndex}-${answerIndex}`} className="grid gap-2">
            {question ? (
              <div
                role="group"
                className="grid gap-2 rounded-md border bg-card px-3 py-3"
              >
                <QuestionTitle
                  question={question}
                  questionCount={questionCount}
                  questionIndex={answerIndex}
                />
              </div>
            ) : null}
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1 rounded-md border bg-muted px-3 py-3">
                <p className="whitespace-pre-wrap break-words text-sm">{answerLabel(answer)}</p>
              </div>
              {readOnly ? null : (
                <Button
                  disabled={locked || (editing && editingAnswerIndex !== answerIndex)}
                  size="sm"
                  type="button"
                  variant="outline"
                  className="shrink-0"
                  onClick={() => {
                    setEditingAnswerIndex(answerIndex);
                    onEdit();
                  }}
                >
                  <Pencil aria-hidden="true" />
                  Edit
                </Button>
              )}
            </div>
          </li>
        );
      })}
    </Fragment>
  );
}

function isAnsweredModel(turns: GrillingTurn[], index: number): boolean {
  const next = turns[index + 1];
  return next?.role === "account" && next.kind === "answers";
}

export function GrillingTurns({
  turns,
  generating,
  preview,
  locked,
  readOnly = false,
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
  readOnly?: boolean;
  editingIndex: number | null;
  draftTurn: GrillingTurn | null;
  dirty: boolean;
  onEdit: (index: number) => void;
  onCancel: () => void;
  onSave: (turn?: GrillingTurn) => void;
  onDraftChange: (turn: GrillingTurn) => void;
}) {
  return (
    <ol className="grid gap-3" aria-label="Grilling history">
      {turns.map((turn, index) => {
        const current = editingIndex === index && draftTurn ? draftTurn : turn;
        const editLocked = locked || (editingIndex !== null && editingIndex !== index);

        if (
          current.role === "model" &&
          !isAnsweredModel(turns, index) &&
          current.questions.length > 0
        ) {
          return null;
        }

        if (current.role === "model" && isAnsweredModel(turns, index)) {
          const preamble = current.preamble.trim();
          if (!preamble) {
            return null;
          }
          return (
            <li key={`preamble-${index}`}>
              <p className="border-l-2 border-navy/30 pl-3 font-serif text-sm italic leading-relaxed whitespace-pre-wrap break-words text-muted-foreground">
                {preamble}
              </p>
            </li>
          );
        }

        if (current.role === "account" && current.kind === "idea") {
          return (
            <AccountTextView
              key={`idea-${index}`}
              ariaLabel="Edit idea"
              dirty={editingIndex === index && dirty}
              editing={editingIndex === index}
              fieldLabel="Research idea"
              label="Research idea"
              locked={editLocked}
              readOnly={readOnly}
              turn={current}
              onCancel={onCancel}
              onChange={(text) => onDraftChange({ ...current, text })}
              onEdit={() => onEdit(index)}
              onSave={() => onSave()}
            />
          );
        }
        if (current.role === "account" && current.kind === "note") {
          return (
            <AccountTextView
              key={`note-${index}`}
              ariaLabel="Edit Account note"
              dirty={editingIndex === index && dirty}
              editing={editingIndex === index}
              fieldLabel="Account note"
              label="Account note"
              locked={editLocked}
              readOnly={readOnly}
              turn={current}
              onCancel={onCancel}
              onChange={(text) => onDraftChange({ ...current, text })}
              onEdit={() => onEdit(index)}
              onSave={() => onSave()}
            />
          );
        }
        if (current.role === "account" && current.kind === "answers") {
          const answersTurn =
            editingIndex === index && draftTurn?.role === "account" && draftTurn.kind === "answers"
              ? draftTurn
              : current;
          return (
            <AnsweredClusterPairs
              key={`answers-${index}`}
              answers={answersTurn}
              cluster={modelTurnBefore(turns, index)}
              dirty={editingIndex === index && dirty}
              editing={editingIndex === index}
              locked={editLocked}
              readOnly={readOnly}
              turnIndex={index}
              onCancel={onCancel}
              onDraftChange={onDraftChange}
              onEdit={() => onEdit(index)}
              onSave={() => onSave()}
            />
          );
        }
        return (
          <HistorySection key={`model-${index}`} surface="border bg-card">
            {current.role === "model" && current.preamble ? (
              <p className="font-serif text-base whitespace-pre-wrap break-words text-navy">
                {current.preamble}
              </p>
            ) : null}
          </HistorySection>
        );
      })}
      {generating ? (
        <ReceivingFrame icon={LoaderCircle} iconClassName="animate-spin" label="Receiving">
          <p className="font-serif text-base whitespace-pre-wrap break-words text-navy">
            {preview.trim() ? preview : "Waiting for the next Grilling Questions."}
          </p>
        </ReceivingFrame>
      ) : null}
    </ol>
  );
}
