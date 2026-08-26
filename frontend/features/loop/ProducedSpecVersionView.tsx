"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CardKind, type SpecVersionResponse, WorkflowNode } from "@/lib/api/generated/model";

import { CARD_KIND_LABELS, LOOP_STAGE_CATALOG, WORKFLOW_NODE_LABELS } from "./catalog";

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

function SpecNode({ node, payload }: { node: WorkflowNode; payload: unknown }) {
  if (!isRecord(payload)) {
    return (
      <div className="grid min-w-0 grid-cols-1 gap-2">
        <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p>
        <JsonFallback value={payload} />
      </div>
    );
  }

  const narrative = isRecord(payload.narrative) ? payload.narrative : null;
  const narrativeText = narrative ? fieldText(narrative) : null;
  const cards = Array.isArray(payload.card_snapshot) ? payload.card_snapshot : null;
  const hasConfirmedGapCard =
    node === WorkflowNode.gap &&
    Boolean(cards?.some((card) => isRecord(card) && card.kind === CardKind.gap));
  const unknownNarrative = narrative
    ? unknownFields(narrative, hasConfirmedGapCard ? ["text", "candidate"] : ["text"])
    : null;
  const unknownNode = unknownFields(payload, ["narrative", "card_snapshot"]);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-2">
      <p className="text-sm font-medium">{WORKFLOW_NODE_LABELS[node]}</p>
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

function SpecDocument({ document }: { document: Record<string, unknown> }) {
  const nodes = isRecord(document.nodes) ? document.nodes : null;
  const unknownRoot = unknownFields(document, ["nodes"]);
  const catalogNodes = new Set<string>(
    LOOP_STAGE_CATALOG.flatMap((stage) => [...stage.nodes]),
  );
  const extraNodes = nodes
    ? Object.fromEntries(Object.entries(nodes).filter(([key]) => !catalogNodes.has(key)))
    : null;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      {nodes ? (
        <>
          {LOOP_STAGE_CATALOG.filter((stage) => stage.nodes.length > 0).map((stage) => {
            const present = stage.nodes.filter((node) => nodes[node] !== undefined);
            if (present.length === 0) {
              return null;
            }
            return (
              <section key={stage.id} className="min-w-0" aria-label={`${stage.name} in Produced Spec Version`}>
                <h3 className="font-serif text-navy">{stage.name}</h3>
                <div className="mt-2 grid min-w-0 grid-cols-1 gap-3">
                  {present.map((node) => (
                    <SpecNode key={node} node={node} payload={nodes[node]} />
                  ))}
                </div>
              </section>
            );
          })}
          {extraNodes && Object.keys(extraNodes).length > 0 ? <JsonFallback value={extraNodes} /> : null}
          {unknownRoot ? <JsonFallback value={unknownRoot} /> : null}
        </>
      ) : (
        <JsonFallback value={document} />
      )}
    </div>
  );
}

export function ProducedSpecVersionView({
  produced,
  validSpecVersionId,
}: {
  produced: SpecVersionResponse | null;
  validSpecVersionId: string | null;
}) {
  const stale = Boolean(produced && produced.id !== validSpecVersionId);

  return (
    <section aria-label="Produced Spec Version">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-navy">Produced Spec Version</CardTitle>
          <CardDescription>
            {produced
              ? stale
                ? "Stale. This Produced Spec Version is not the Valid Spec Version."
                : "This Produced Spec Version is the Valid Spec Version."
              : "No Produced Spec Version"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {produced ? (
            <div className="grid min-w-0 grid-cols-1 gap-4">
              {stale ? <p className="text-sm font-medium text-pending">Stale</p> : null}
              <SpecDocument document={produced.document} />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}
