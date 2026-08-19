"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import type { GrillingAnswer, GrillingQuestion } from "./turns";

export const OTHER = "__other__";

export function answersComplete(
  questions: GrillingQuestion[],
  picks: string[],
  others: string[],
): boolean {
  return questions.every((_, index) => {
    const pick = picks[index];
    if (!pick) return false;
    if (pick === OTHER) return Boolean(others[index]?.trim());
    return true;
  });
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

export function GrillingQuestionFields({
  questions,
  picks,
  others,
  disabled,
  onPick,
  onOther,
}: {
  questions: GrillingQuestion[];
  picks: string[];
  others: string[];
  disabled: boolean;
  onPick: (index: number, value: string) => void;
  onOther: (index: number, value: string) => void;
}) {
  return (
    <div className="grid gap-4">
      {questions.map((question, index) => (
        <fieldset key={`${question.text}-${index}`} className="grid gap-2">
          <legend className="font-serif text-base text-navy">{question.text}</legend>
          {question.options.map((option) => (
            <label key={option} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name={`grilling-q-${index}`}
                checked={picks[index] === option}
                disabled={disabled}
                onChange={() => onPick(index, option)}
              />
              {option}
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`grilling-q-${index}`}
              checked={picks[index] === OTHER}
              disabled={disabled}
              onChange={() => onPick(index, OTHER)}
            />
            Other
          </label>
          {picks[index] === OTHER ? (
            <Textarea
              aria-label={`Other answer for ${question.text}`}
              disabled={disabled}
              value={others[index] ?? ""}
              onChange={(event) => onOther(index, event.target.value)}
            />
          ) : null}
        </fieldset>
      ))}
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
  const [picks, setPicks] = useState(() => initialPicks(questions, initialAnswers));
  const [others, setOthers] = useState(() => initialOthers(questions, initialAnswers));
  const [dirty, setDirty] = useState(false);
  const complete = useMemo(
    () => answersComplete(questions, picks, others),
    [others, picks, questions],
  );
  const requireDirty = initialAnswers !== undefined;
  const canSubmit = complete && !disabled && !submitDisabled && (!requireDirty || dirty);

  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        onSubmit(toAnswers(questions, picks, others));
      }}
    >
      <GrillingQuestionFields
        disabled={disabled}
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
        <Button disabled={!canSubmit} type="submit">
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
