export type GrillingAnswer = { option: string } | { other: string };

export type GrillingQuestion = {
  text: string;
  options: string[];
};

export type IdeaTurn = {
  role: "account";
  kind: "idea";
  text: string;
};

export type AnswersTurn = {
  role: "account";
  kind: "answers";
  answers: GrillingAnswer[];
};

export type ModelTurn = {
  role: "model";
  preamble: string;
  questions: GrillingQuestion[];
};

export type GrillingTurn = IdeaTurn | AnswersTurn | ModelTurn;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function parseAnswer(value: unknown): GrillingAnswer | null {
  const record = asRecord(value);
  if (!record) return null;
  if (typeof record.option === "string" && record.option.trim()) {
    return { option: record.option };
  }
  if (typeof record.other === "string" && record.other.trim()) {
    return { other: record.other };
  }
  return null;
}

function parseQuestion(value: unknown): GrillingQuestion | null {
  const record = asRecord(value);
  if (!record || typeof record.text !== "string" || !record.text.trim()) return null;
  if (!Array.isArray(record.options)) return null;
  const options = record.options.filter(
    (item): item is string => typeof item === "string" && item.trim().length > 0,
  );
  if (options.length < 2) return null;
  return { text: record.text, options };
}

function parseTurn(value: unknown): GrillingTurn | null {
  const record = asRecord(value);
  if (!record) return null;
  if (record.role === "account" && record.kind === "idea" && typeof record.text === "string") {
    return { role: "account", kind: "idea", text: record.text };
  }
  if (record.role === "account" && record.kind === "answers" && Array.isArray(record.answers)) {
    const answers = record.answers.map(parseAnswer);
    if (answers.some((item) => item === null)) return null;
    return { role: "account", kind: "answers", answers: answers as GrillingAnswer[] };
  }
  if (record.role === "model") {
    const preamble = typeof record.preamble === "string" ? record.preamble : "";
    const questions = Array.isArray(record.questions)
      ? record.questions.map(parseQuestion).filter((item): item is GrillingQuestion => item !== null)
      : [];
    return { role: "model", preamble, questions };
  }
  return null;
}

export function parseTurns(narrative: Record<string, unknown> | undefined): GrillingTurn[] {
  if (!narrative || !Array.isArray(narrative.turns)) return [];
  return narrative.turns.map(parseTurn).filter((item): item is GrillingTurn => item !== null);
}

export function isExhaustedHint(narrative: Record<string, unknown> | undefined): boolean {
  return narrative?.exhausted === true;
}

export function hasIdea(turns: GrillingTurn[]): boolean {
  return turns.some((turn) => turn.role === "account" && turn.kind === "idea");
}

export function unansweredCluster(turns: GrillingTurn[]): GrillingQuestion[] | null {
  const last = turns.at(-1);
  if (!last || last.role !== "model" || last.questions.length === 0) return null;
  return last.questions;
}

export function lastIsAccount(turns: GrillingTurn[]): boolean {
  return turns.at(-1)?.role === "account";
}

export function clustersAnswered(turns: GrillingTurn[]): boolean {
  if (!hasIdea(turns)) return false;
  let pending = false;
  for (const turn of turns) {
    if (turn.role === "model") {
      pending = turn.questions.length > 0;
    } else if (turn.role === "account" && turn.kind === "answers") {
      pending = false;
    }
  }
  return !pending;
}

export function modelTurnBefore(turns: GrillingTurn[], index: number): ModelTurn | null {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const turn = turns[cursor];
    if (turn.role === "model") return turn;
  }
  return null;
}

export function withEditedTurn(turns: GrillingTurn[], index: number, next: GrillingTurn): GrillingTurn[] {
  return turns.slice(0, index).concat(next);
}
