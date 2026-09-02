import { LoopStage, NodeHeadStatus, WorkflowNode } from "@/lib/api/generated/model";
import type { LoopSessionResponse, NodeHeadResponse } from "@/lib/api/generated/model";
import { interpretationConfirmable } from "@/features/idea/turns";

import {
  LOOP_STAGE_CATALOG,
  catalogStage,
  descendants,
  ownedCardKinds,
  stageForWorkflowNode,
  stageWorkNodes,
  upstreamOfStage,
} from "./catalog";

export type CompletionSignal = "complete" | "needs_work" | "stale" | "not_evaluated" | "blocked" | "ready";

export type StageSignals = {
  completion: CompletionSignal;
  editing: boolean;
  available: boolean;
};

export function incompleteUpstreamNodes({
  stage,
  nodeHeads,
}: {
  stage: LoopStage;
  nodeHeads: NodeHeadResponse[];
}): WorkflowNode[] {
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  return [...upstreamOfStage(stage)].filter(
    (node) => statusByNode.get(node) !== NodeHeadStatus.current,
  );
}

export type StageActions = {
  canStart: boolean;
  canRecompute: boolean;
  editableNodes: WorkflowNode[];
};

export function deriveStageActions({
  stage,
  nodeHeads,
}: {
  stage: LoopStage;
  nodeHeads: NodeHeadResponse[];
}): StageActions {
  const nodes = stageWorkNodes(stage);
  if (nodes.length === 0 || incompleteUpstreamNodes({ stage, nodeHeads }).length > 0) {
    return { canStart: false, canRecompute: false, editableNodes: [] };
  }
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  const statuses = nodes.map((node) => statusByNode.get(node) ?? NodeHeadStatus.empty);
  const hasEmpty = statuses.includes(NodeHeadStatus.empty);
  const hasStale = statuses.includes(NodeHeadStatus.stale);
  return {
    canStart: hasEmpty && !hasStale,
    canRecompute: hasStale,
    editableNodes: nodes.filter((node) => statusByNode.get(node) === NodeHeadStatus.current),
  };
}

export function shouldAutoPrepare({
  stage,
  selectedNode,
  workingDraftNode,
  nodeHeads,
}: {
  stage: LoopStage;
  selectedNode: WorkflowNode | undefined;
  workingDraftNode: WorkflowNode;
  nodeHeads: NodeHeadResponse[];
}): boolean {
  if (!selectedNode) {
    return false;
  }
  if (incompleteUpstreamNodes({ stage, nodeHeads }).length > 0) {
    return false;
  }
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  const viewedStatus = statusByNode.get(selectedNode) ?? NodeHeadStatus.empty;
  if (viewedStatus !== NodeHeadStatus.empty && viewedStatus !== NodeHeadStatus.stale) {
    return false;
  }
  if (selectedNode === workingDraftNode) {
    return false;
  }
  const wdStatus = statusByNode.get(workingDraftNode) ?? NodeHeadStatus.empty;
  if (wdStatus !== NodeHeadStatus.current) {
    return false;
  }
  const stageNodes = stageWorkNodes(stage);
  return !stageNodes.includes(workingDraftNode);
}

export function deriveStageSignals({
  stage,
  nodeHeads,
  workingDraftNode,
  readinessState,
}: {
  stage: LoopStage;
  nodeHeads: NodeHeadResponse[];
  workingDraftNode: WorkflowNode;
  readinessState?: "not_evaluated" | "blocked" | "ready";
}): StageSignals {
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  const nodes = stageWorkNodes(stage);
  const editing = stageForWorkflowNode(workingDraftNode) === stage;
  const incompleteUpstream = incompleteUpstreamNodes({ stage, nodeHeads });
  const available = incompleteUpstream.length === 0;

  if (nodes.length === 0) {
    if (stage === LoopStage.readiness) {
      const completion =
        readinessState === "blocked" || readinessState === "ready"
          ? readinessState
          : "not_evaluated";
      return { completion, editing: false, available };
    }
    return { completion: "not_evaluated", editing: false, available };
  }

  const statuses = nodes.map((node) => statusByNode.get(node) ?? NodeHeadStatus.empty);
  if (statuses.includes(NodeHeadStatus.stale)) {
    return { completion: "stale", editing, available };
  }
  if (statuses.every((status) => status === NodeHeadStatus.current)) {
    return { completion: "complete", editing, available };
  }
  return { completion: "needs_work", editing, available };
}

export function staleInvalidationStages({
  node,
  nodeHeads,
}: {
  node: WorkflowNode;
  nodeHeads: NodeHeadResponse[];
}): LoopStage[] {
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  if (statusByNode.get(node) !== NodeHeadStatus.current) {
    return [];
  }
  const stages = new Set<LoopStage>();
  for (const child of descendants(node)) {
    if (statusByNode.get(child) === NodeHeadStatus.current) {
      stages.add(stageForWorkflowNode(child));
    }
  }
  return LOOP_STAGE_CATALOG.map((stage) => stage.id).filter((id) => stages.has(id));
}

/** Confirm needs Stale re-accept when the head is Stale and no post-prepare generate ran. */
export function needsStaleReaccept(head: NodeHeadResponse | undefined | null): boolean {
  return (
    head?.status === NodeHeadStatus.stale && head.generated_since_prepare !== true
  );
}

/** Mirror server mark after a successful node generate so Confirm/banner update without refetch. */
export function withGeneratedSincePrepare(
  session: LoopSessionResponse,
  node: WorkflowNode = session.working_draft_node,
): LoopSessionResponse {
  return {
    ...session,
    node_heads: session.node_heads.map((head) =>
      head.node === node ? { ...head, generated_since_prepare: true } : head,
    ),
  };
}

/**
 * Independent judges is a dashboard, not an Aggregator node tab. Judge Confirm
 * marks Aggregator Stale until Confirm Aggregator; that must not open the
 * “Aggregator is Stale / Generate again” banner (ADR 0040). Node line only while
 * Stale re-accept is still needed (ADR 0036); generate hides it even when browsing
 * the Stale Stage Revision.
 */
export function invalidationBannerNodeSubject(args: {
  selectedStage: LoopStage;
  selectedNode: WorkflowNode | undefined;
  viewedHead: NodeHeadResponse | undefined | null;
}): WorkflowNode | null {
  if (args.selectedStage === LoopStage.independent_judges) {
    return null;
  }
  if (args.selectedNode == null || !needsStaleReaccept(args.viewedHead)) {
    return null;
  }
  return args.selectedNode;
}

/** Whether Spec Draft's invalidation line belongs in the current-view banner. */
export function specInvalidationInView(args: {
  selectedNode: WorkflowNode | undefined;
  selectedStage: LoopStage;
  viewedNodeStale: boolean;
  specVersionStale: boolean;
}): boolean {
  if (!args.specVersionStale) {
    return false;
  }
  return (
    args.viewedNodeStale ||
    args.selectedStage === LoopStage.spec_draft ||
    args.selectedNode == null
  );
}

function fieldText(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  const text = (value as Record<string, unknown>).text;
  return typeof text === "string" ? text.trim() : "";
}

export function hasConfirmableWorkingDraft(
  session: Pick<LoopSessionResponse, "working_draft_node" | "working_draft_narrative" | "cards">,
): boolean {
  const narrative = session.working_draft_narrative as Record<string, unknown>;
  if (
    session.working_draft_node === WorkflowNode.idea_interpretation ||
    Array.isArray(narrative.turns)
  ) {
    return interpretationConfirmable(narrative);
  }
  if (fieldText(session.working_draft_narrative)) {
    return true;
  }
  const owned = ownedCardKinds(session.working_draft_node);
  if (session.working_draft_node === WorkflowNode.claims) {
    return owned.every((kind) =>
      session.cards.some((card) => card.kind === kind && cardBodyNonblank(card.body)),
    );
  }
  return session.cards.some((card) => owned.includes(card.kind) && cardBodyNonblank(card.body));
}

function cardBodyNonblank(body: unknown): boolean {
  if (fieldText(body)) {
    return true;
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return false;
  }
  const record = body as Record<string, unknown>;
  return ["statement", "claim", "evidence"].some((key) => {
    const value = record[key];
    return typeof value === "string" && value.trim().length > 0;
  });
}
