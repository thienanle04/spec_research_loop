"use client";

import { useId, useMemo, useRef, useState } from "react";
import { Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { GrillingAnswer, GrillingQuestion } from "./turns";

export const OTHER = "__other__";

export function unansweredIndices(
  questions: GrillingQuestion[],
  picks: string[],
  others: string[],
): number[] {
  return questions.flatMap((_, index) => {
    const pick = picks[index];
    if (!pick) return [index];
    if (pick === OTHER && !others[index]?.trim()) return [index];
    return [];
  });
}

export function answersComplete(
  questions: GrillingQuestion[],
  picks: string[],
  others: string[],
): boolean {
  return unansweredIndices(questions, picks, others).length === 0;
}

export function toAnswers(
  questions: GrillingQuestion[],
  picks: string[],
  others: string[],
): GrillingAnswer[] {
  return questions.map((_, index) =>
    picks[index] === OTHER
      ? { other: others[index]?.trim() ?? "" }
      : { option: picks[index] },
  );
}

export function initialPicks(questions: GrillingQuestion[], answers?: GrillingAnswer[]): string[] {
  return questions.map((_, index) => {
    const answer = answers?.[index];
    if (answer && "option" in answer) return answer.option;
    if (answer && "other" in answer) return OTHER;
    return "";
  });
}

export function initialOthers(questions: GrillingQuestion[], answers?: GrillingAnswer[]): string[] {
  return questions.map((_, index) => {
    const answer = answers?.[index];
    return answer && "other" in answer ? answer.other : "";
  });
}

function questionError(pick: string | undefined, other: string | undefined): string | null {
  if (!pick) return "Select an option";
  if (pick === OTHER && !other?.trim()) return "Write an Other answer";
  return null;
}

export function GrillingQuestionFields({
  formId,
  questions,
  picks,
  others,
  disabled,
  attempted,
  onPick,
  onOther,
}: {
  formId: string;
  questions: GrillingQuestion[];
  picks: string[];
  others: string[];
  disabled: boolean;
  attempted: boolean;
  onPick: (index: number, value: string) => void;
  onOther: (index: number, value: string) => void;
}) {
  return (
    <div className="grid gap-4">
      {questions.map((question, index) => {
        const fieldId = `${formId}-q-${index}`;
        const errorId = `${fieldId}-error`;
        const otherId = `${fieldId}-other`;
        const error = attempted ? questionError(picks[index], others[index]) : null;
        const selected = picks[index];

        return (
          <fieldset
            key={fieldId}
            id={fieldId}
            aria-describedby={error ? errorId : undefined}
            aria-invalid={error ? true : undefined}
            className="scroll-mt-[var(--header-height)] grid gap-2"
          >
            <legend className="font-serif text-base text-navy">
              <span className="mr-2 font-sans text-xs font-medium text-muted-foreground">
                {index + 1}/{questions.length}
              </span>
              {question.text}
            </legend>
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
                    disabled && "cursor-not-allowed opacity-50 hover:bg-card",
                  )}
                >
                  <input
                    id={optionId}
                    type="radio"
                    name={fieldId}
                    className="mt-0.5 size-4 accent-navy"
                    checked={isSelected}
                    disabled={disabled}
                    onChange={() => onPick(index, option)}
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
                disabled && "cursor-not-allowed opacity-50 hover:bg-card",
              )}
            >
              <input
                id={`${fieldId}-other-radio`}
                type="radio"
                name={fieldId}
                className="mt-0.5 size-4 accent-navy"
                checked={selected === OTHER}
                disabled={disabled}
                onChange={() => onPick(index, OTHER)}
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
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? errorId : undefined}
                  disabled={disabled}
                  value={others[index] ?? ""}
                  onChange={(event) => onOther(index, event.target.value)}
                />
              </div>
            ) : null}
            {error ? (
              <p id={errorId} className="text-sm font-medium text-destructive">
                {error}
              </p>
            ) : null}
          </fieldset>
        );
      })}
    </div>
  );
}

export function GrillingClusterForm({
  questions,
  disabled,
  submitLabel,
  cancelLabel,
  submitDisabled,
  initialAnswers,
  onSubmit,
  onCancel,
}: {
  questions: GrillingQuestion[];
  disabled: boolean;
  submitLabel: string;
  cancelLabel?: string;
  submitDisabled?: boolean;
  initialAnswers?: GrillingAnswer[];
  onSubmit: (answers: GrillingAnswer[]) => void;
  onCancel?: () => void;
}) {
  const formId = `grilling-cluster-${useId().replace(/:/g, "")}`;
  const summaryRef = useRef<HTMLDivElement>(null);
  const [picks, setPicks] = useState(() => initialPicks(questions, initialAnswers));
  const [others, setOthers] = useState(() => initialOthers(questions, initialAnswers));
  const [dirty, setDirty] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const missing = useMemo(
    () => unansweredIndices(questions, picks, others),
    [others, picks, questions],
  );
  const complete = missing.length === 0;
  const requireDirty = initialAnswers !== undefined;
  const locked = disabled || Boolean(submitDisabled);
  const unchanged = requireDirty && !dirty;
  const canAttempt = !locked && !unchanged;
  const answeredCount = questions.length - missing.length;

  return (
    <form
      className="grid gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!canAttempt) return;
        if (!complete) {
          setAttempted(true);
          requestAnimationFrame(() => summaryRef.current?.focus());
          return;
        }
        onSubmit(toAnswers(questions, picks, others));
      }}
    >
      <p role="status" aria-atomic="true" className="text-sm text-muted-foreground">
        {answeredCount} of {questions.length} Grilling Questions answered
      </p>
      <div className="h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div
          className="h-full bg-navy transition-[width] duration-200"
          style={{ width: `${questions.length === 0 ? 0 : (answeredCount / questions.length) * 100}%` }}
        />
      </div>
      {attempted && missing.length > 0 ? (
        <div
          ref={summaryRef}
          role="alert"
          tabIndex={-1}
          aria-labelledby={`${formId}-error-title`}
          className="scroll-mt-[var(--header-height)] rounded-md border border-destructive bg-card p-3"
        >
          <h2 id={`${formId}-error-title`} className="text-sm font-medium text-destructive">
            There is a problem
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-sm">
            {missing.map((index) => (
              <li key={`${formId}-missing-${index}`}>
                <a
                  className="text-in-progress underline-offset-4 hover:underline"
                  href={`#${formId}-q-${index}`}
                >
                  {questionError(picks[index], others[index])} for question {index + 1}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <GrillingQuestionFields
        attempted={attempted}
        disabled={disabled}
        formId={formId}
        others={others}
        picks={picks}
        questions={questions}
        onOther={(index, value) => {
          setDirty(true);
          setOthers((current) => current.map((item, i) => (i === index ? value : item)));
        }}
        onPick={(index, value) => {
          setDirty(true);
          setPicks((current) => current.map((item, i) => (i === index ? value : item)));
        }}
      />
      <div className="flex flex-wrap gap-2">
        {onCancel ? (
          <Button type="button" variant="outline" onClick={onCancel}>
            {cancelLabel ?? "Cancel"}
          </Button>
        ) : null}
        <Button
          aria-describedby={unchanged ? `${formId}-unchanged` : undefined}
          disabled={!canAttempt}
          type="submit"
        >
          <Send aria-hidden="true" />
          {submitLabel}
        </Button>
      </div>
      {unchanged ? (
        <p id={`${formId}-unchanged`} className="text-sm text-muted-foreground">
          Save is available after you change an answer.
        </p>
      ) : null}
    </form>
  );
}
