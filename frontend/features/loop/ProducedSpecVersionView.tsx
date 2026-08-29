"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { SpecVersionResponse } from "@/lib/api/generated/model";

import { LOOP_STAGE_CATALOG } from "./catalog";
import { StageRevisionBody } from "./StageRevisionBody";

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
                    <StageRevisionBody key={node} node={node} payload={nodes[node]} />
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
