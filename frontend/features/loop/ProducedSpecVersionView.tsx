"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { frameHasContent } from "@/features/idea/turns";
import { WorkflowNode, type SpecVersionResponse } from "@/lib/api/generated/model";

import { LOOP_STAGE_CATALOG } from "./catalog";
import { StageRevisionBody } from "./StageRevisionBody";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** Workflow Nodes omitted from Spec Draft read UI (still in the Spec Version document). */
const SPEC_DRAFT_HIDDEN_NODES = new Set<WorkflowNode>([WorkflowNode.research_inputs]);

function isGrillingNarrative(narrative: Record<string, unknown>): boolean {
  return Array.isArray(narrative.turns) || isRecord(narrative.frame);
}

/** Spec Draft hides grilling turn lists; blank Idea Frames omit the whole node section. */
function includeOnSpecDraft(node: WorkflowNode, payload: unknown): boolean {
  if (SPEC_DRAFT_HIDDEN_NODES.has(node)) {
    return false;
  }
  if (!isRecord(payload)) {
    return true;
  }
  const narrative = isRecord(payload.narrative) ? payload.narrative : null;
  if (narrative && isGrillingNarrative(narrative) && !frameHasContent(narrative)) {
    return false;
  }
  return true;
}

function SpecDocument({
  document,
  sessionId,
}: {
  document: Record<string, unknown>;
  sessionId: string;
}) {
  const nodes = isRecord(document.nodes) ? document.nodes : null;

  if (!nodes) {
    return null;
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      {LOOP_STAGE_CATALOG.filter((stage) => stage.nodes.length > 0).map((stage) => {
        const present = stage.nodes.filter(
          (node) => nodes[node] !== undefined && includeOnSpecDraft(node, nodes[node]),
        );
        if (present.length === 0) {
          return null;
        }
        return (
          <section key={stage.id} className="min-w-0" aria-label={`${stage.name} in Produced Spec Version`}>
            <h3 className="font-serif text-navy">{stage.name}</h3>
            <div className="mt-2 grid min-w-0 grid-cols-1 gap-3">
              {present.map((node) => (
                <StageRevisionBody
                  key={node}
                  node={node}
                  payload={nodes[node]}
                  sessionId={sessionId}
                  showLeftovers={false}
                  showTurns={false}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function ProducedSpecVersionView({
  produced,
  validSpecVersionId,
  sessionId,
}: {
  produced: SpecVersionResponse | null;
  validSpecVersionId: string | null;
  sessionId: string;
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
              <SpecDocument document={produced.document} sessionId={sessionId} />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}
