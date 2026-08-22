import { LoopStage, NodeHeadStatus, WorkflowNode } from "@/lib/api/generated/model";
import type { LoopSessionResponse, NodeHeadResponse } from "@/lib/api/generated/model";
import { clustersAnswered, parseTurns } from "@/features/idea/turns";

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
  if (Array.isArray(narrative.turns)) {
    return clustersAnswered(parseTurns(narrative));
  }
  if (fieldText(session.working_draft_narrative)) {
    return true;
  }
  const owned = new Set(ownedCardKinds(session.working_draft_node));
  return session.cards.some((card) => owned.has(card.kind) && fieldText(card.body));
}
