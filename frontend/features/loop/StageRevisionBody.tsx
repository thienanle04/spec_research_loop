import { CardKind, WorkflowNode } from "@/lib/api/generated/model";

import { parseFrame, parseTurns } from "@/features/idea/turns";

import { CARD_KIND_LABELS, WORKFLOW_NODE_LABELS } from "./catalog";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function unknownFields(value: Record<string, unknown>, knownKeys: readonly string[]): Record<string, unknown> | null {
  const rest: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (!knownKeys.includes(key)) {
      rest[key] = entry;
    }
  }
  return Object.keys(rest).length > 0 ? rest : null;
}

function JsonFallback({ value }: { value: unknown }) {
  return (
    <pre className="max-w-full overflow-x-auto rounded-md bg-muted/60 p-3 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function fieldText(value: unknown): string | null {
  if (!isRecord(value) || typeof value.text !== "string") {
    return null;
  }
  return value.text;
}

function cardKindLabel(kind: unknown): string {
  if (typeof kind === "string" && Object.values(CardKind).includes(kind as CardKind)) {
    return CARD_KIND_LABELS[kind as CardKind];
  }
  return typeof kind === "string" ? kind : "Card";
}

function GrillingRevision({ narrative }: { narrative: Record<string, unknown> }) {
  const frame = parseFrame(narrative);
  const turns = parseTurns(narrative);
  const leftover = unknownFields(narrative, ["turns", "frame", "exhausted"]);
  return (
    <div className="grid min-w-0 grid-cols-1 gap-3">
      {frame.intent || frame.problem || frame.research_question ? (
        <dl className="grid gap-2 text-sm">
          {frame.intent ? (
            <div>
              <dt className="font-medium">Intent</dt>
              <dd className="whitespace-pre-wrap">{frame.intent}</dd>
            </div>
          ) : null}
          {frame.problem ? (
            <div>
              <dt className="font-medium">Problem</dt>
              <dd className="whitespace-pre-wrap">{frame.problem}</dd>
            </div>
          ) : null}
          {frame.research_question ? (
            <div>
              <dt className="font-medium">Research question</dt>
              <dd className="whitespace-pre-wrap">{frame.research_question}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {turns.length > 0 ? (
        <ol className="grid gap-2 text-sm">
          {turns.map((turn, index) => (
            <li key={index} className="rounded-md border bg-muted/40 px-3 py-2">
              {turn.role === "account" && turn.kind === "answers" ? (
                <p>{turn.answers.map((answer) => ("option" in answer ? answer.option : answer.other)).join(", ")}</p>
              ) : turn.role === "model" ? (
                <p className="whitespace-pre-wrap">{turn.preamble || turn.questions.map((q) => q.text).join(" ")}</p>
              ) : (
                <p className="whitespace-pre-wrap">{turn.text}</p>
              )}
            </li>
          ))}
        </ol>
      ) : null}
      {leftover ? <JsonFallback value={leftover} /> : null}
    </div>
  );
}

export function StageRevisionBody({
  node,
  payload,
  showNodeLabel = true,
}: {
  node: WorkflowNode;
  payload: unknown;
  showNodeLabel?: boolean;
}) {
  if (!isRecord(payload)) {
    return (
      <div className="grid min-w-0 grid-cols-1 gap-2">
        {showNodeLabel ? <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p> : null}
        <JsonFallback value={payload} />
      </div>
    );
  }

  const narrative = isRecord(payload.narrative) ? payload.narrative : null;
  const grilling =
    narrative && (Array.isArray(narrative.turns) || isRecord(narrative.frame));
  const narrativeText = narrative && !grilling ? fieldText(narrative) : null;
  const cards = Array.isArray(payload.card_snapshot) ? payload.card_snapshot : null;
  const hasConfirmedGapCard =
    node === WorkflowNode.gap &&
    Boolean(cards?.some((card) => isRecord(card) && card.kind === CardKind.gap));
  const unknownNarrative =
    narrative && !grilling
      ? unknownFields(narrative, hasConfirmedGapCard ? ["text", "candidate"] : ["text"])
      : null;
  const unknownNode = unknownFields(payload, ["narrative", "card_snapshot"]);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-2">
      {showNodeLabel ? <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p> : null}
      {grilling && narrative ? <GrillingRevision narrative={narrative} /> : null}
      {narrativeText ? <p className="text-sm whitespace-pre-wrap">{narrativeText}</p> : null}
      {unknownNarrative ? <JsonFallback value={unknownNarrative} /> : null}
      {narrative === null && payload.narrative !== undefined ? (
        <JsonFallback value={payload.narrative} />
      ) : null}
      {cards
        ? cards.map((card, index) => {
            if (!isRecord(card)) {
              return <JsonFallback key={index} value={card} />;
            }
            const body = isRecord(card.body) ? card.body : null;
            const text = body ? fieldText(body) : null;
            const unknownBody = body ? unknownFields(body, ["text"]) : null;
            const unknownCard = unknownFields(card, ["id", "kind", "body"]);
            return (
              <div key={typeof card.id === "string" ? card.id : index} className="min-w-0 rounded-md border bg-muted/40 px-3 py-2">
                <p className="text-sm font-medium">{cardKindLabel(card.kind)}</p>
                {text ? <p className="text-sm whitespace-pre-wrap">{text}</p> : null}
                {unknownBody ? <JsonFallback value={unknownBody} /> : null}
                {body === null && card.body !== undefined ? <JsonFallback value={card.body} /> : null}
                {unknownCard ? <JsonFallback value={unknownCard} /> : null}
              </div>
            );
          })
        : payload.card_snapshot !== undefined
          ? <JsonFallback value={payload.card_snapshot} />
          : null}
      {unknownNode ? <JsonFallback value={unknownNode} /> : null}
    </div>
  );
}
