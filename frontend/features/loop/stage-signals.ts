import { LoopStage, NodeHeadStatus, WorkflowNode } from "@/lib/api/generated/model";
import type { LoopSessionResponse, NodeHeadResponse } from "@/lib/api/generated/model";
import { interpretationConfirmable } from "@/features/idea/turns";

import {
  LOOP_STAGE_CATALOG,
  catalogStage,
  descendants,
  ownedCardKinds,
  stageForWorkflowNode,
  upstreamOfStage,
} from "./catalog";

export type CompletionSignal = "complete" | "needs_work" | "stale" | "not_evaluated";

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
  const nodes = catalogStage(stage).nodes;
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
  const stageNodes = catalogStage(stage).nodes as readonly WorkflowNode[];
  return !stageNodes.includes(workingDraftNode);
}

export function deriveStageSignals({
  stage,
  nodeHeads,
  workingDraftNode,
}: {
  stage: LoopStage;
  nodeHeads: NodeHeadResponse[];
  workingDraftNode: WorkflowNode;
}): StageSignals {
  const statusByNode = new Map(nodeHeads.map((head) => [head.node, head.status]));
  const nodes = catalogStage(stage).nodes;
  const editing = stageForWorkflowNode(workingDraftNode) === stage;
  const incompleteUpstream = incompleteUpstreamNodes({ stage, nodeHeads });
  const available = incompleteUpstream.length === 0;

  if (nodes.length === 0) {
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

/** Mirror server mark after a successful node generate so Confirm/dimming update without refetch. */
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
 * Dim Stale revision/draft while the invalidation banner is showing and
 * Stale re-accept is still needed (ADR 0036). Dismiss hides the banner and undims.
 */
export function shouldDimStaleContent(
  head: NodeHeadResponse | undefined | null,
  invalidationBannerVisible: boolean,
): boolean {
  return needsStaleReaccept(head) && invalidationBannerVisible;
}

/** Banner dismiss subject: one Workflow Node or Spec Draft (ADR 0036). */
export type InvalidationBannerSubject = WorkflowNode | "spec_draft";

export function invalidationWaveKey(
  session: Pick<
    LoopSessionResponse,
    "node_heads" | "produced_spec_version" | "valid_spec_version_id"
  >,
): string {
  const staleNodes = session.node_heads
    .filter((head) => head.status === NodeHeadStatus.stale)
    .map((head) => head.node)
    .sort()
    .join(",");
  const specStale =
    session.produced_spec_version != null &&
    session.valid_spec_version_id !== session.produced_spec_version.id;
  if (!staleNodes && !specStale) {
    return "";
  }
  return `${staleNodes}|spec:${specStale ? "1" : "0"}`;
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

export function isInvalidationSubjectDismissed(
  subject: InvalidationBannerSubject,
  waveKey: string,
  dismissedBySubject: Readonly<Record<string, string>>,
): boolean {
  return waveKey !== "" && dismissedBySubject[subject] === waveKey;
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
  const owned = new Set(ownedCardKinds(session.working_draft_node));
  return session.cards.some((card) => owned.has(card.kind) && fieldText(card.body));
}
