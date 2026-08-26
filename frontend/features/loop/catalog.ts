import { CardKind, LoopStage, WorkflowNode } from "@/lib/api/generated/model";

export const LOOP_STAGE_CATALOG = [
  {
    id: LoopStage.grilling,
    name: "Grilling",
    description: "Clarify the research idea through questions you confirm.",
    nodes: [WorkflowNode.idea_interpretation, WorkflowNode.idea_decomposition],
  },
  {
    id: LoopStage.related_work,
    name: "Related work",
    description: "Locate and assess prior work, synthesize the gap, and choose a contribution direction.",
    nodes: [
      WorkflowNode.research_inputs,
      WorkflowNode.related_work,
      WorkflowNode.gap,
      WorkflowNode.contribution,
    ],
  },
  {
    id: LoopStage.claims_evidence,
    name: "Claims/evidence",
    description: "State claims and the evidence that would support them.",
    nodes: [WorkflowNode.claims, WorkflowNode.evidence],
  },
  {
    id: LoopStage.experiment_planning,
    name: "Experiment planning",
    description: "Plan tests that could confirm or refute the claims.",
    nodes: [WorkflowNode.experiment_plan, WorkflowNode.feasibility],
  },
  {
    id: LoopStage.independent_judges,
    name: "Independent judges",
    description: "Separate judgement of the Research Spec.",
    nodes: [
      WorkflowNode.gap_judge,
      WorkflowNode.contribution_judge,
      WorkflowNode.evidence_judge,
      WorkflowNode.experiment_judge,
      WorkflowNode.conference_judge,
      WorkflowNode.aggregator,
    ],
  },
  {
    id: LoopStage.readiness,
    name: "Readiness",
    description: "Evaluate readiness criteria. Not conference acceptance.",
    nodes: [],
  },
] as const;

type CatalogStageId = (typeof LOOP_STAGE_CATALOG)[number]["id"];
type LegacyHiddenStage = typeof LoopStage.contribution;
type MissingStage = Exclude<LoopStage, CatalogStageId | LegacyHiddenStage>;
type ExtraStage = Exclude<CatalogStageId, LoopStage>;
const _allStagesPresent: MissingStage extends never ? true : MissingStage = true;
const _noExtraStages: ExtraStage extends never ? true : ExtraStage = true;
void _allStagesPresent;
void _noExtraStages;

type CatalogNode = (typeof LOOP_STAGE_CATALOG)[number]["nodes"][number];
type MissingNode = Exclude<WorkflowNode, CatalogNode>;
type ExtraNode = Exclude<CatalogNode, WorkflowNode>;
const _allNodesPresent: MissingNode extends never ? true : MissingNode = true;
const _noExtraNodes: ExtraNode extends never ? true : ExtraNode = true;
void _allNodesPresent;
void _noExtraNodes;

const INVALIDATION_CHILDREN: Record<WorkflowNode, readonly WorkflowNode[]> = {
  [WorkflowNode.idea_interpretation]: [WorkflowNode.idea_decomposition],
  [WorkflowNode.idea_decomposition]: [WorkflowNode.research_inputs, WorkflowNode.gap_judge],
  [WorkflowNode.research_inputs]: [WorkflowNode.related_work],
  [WorkflowNode.related_work]: [
    WorkflowNode.gap,
    WorkflowNode.gap_judge,
    WorkflowNode.contribution_judge,
    WorkflowNode.evidence_judge,
  ],
  [WorkflowNode.gap]: [
    WorkflowNode.contribution,
    WorkflowNode.gap_judge,
    WorkflowNode.contribution_judge,
  ],
  [WorkflowNode.contribution]: [
    WorkflowNode.claims,
    WorkflowNode.contribution_judge,
    WorkflowNode.experiment_judge,
  ],
  [WorkflowNode.claims]: [
    WorkflowNode.evidence,
    WorkflowNode.evidence_judge,
    WorkflowNode.experiment_judge,
  ],
  [WorkflowNode.evidence]: [
    WorkflowNode.experiment_plan,
    WorkflowNode.gap_judge,
    WorkflowNode.contribution_judge,
  ],
  [WorkflowNode.experiment_plan]: [WorkflowNode.feasibility, WorkflowNode.experiment_judge],
  [WorkflowNode.feasibility]: [WorkflowNode.experiment_judge, WorkflowNode.conference_judge],
  [WorkflowNode.gap_judge]: [WorkflowNode.aggregator],
  [WorkflowNode.contribution_judge]: [WorkflowNode.aggregator],
  [WorkflowNode.evidence_judge]: [WorkflowNode.aggregator],
  [WorkflowNode.experiment_judge]: [WorkflowNode.aggregator],
  [WorkflowNode.conference_judge]: [WorkflowNode.aggregator],
  [WorkflowNode.aggregator]: [],
};

export const WORKFLOW_NODE_LABELS: Record<WorkflowNode, string> = {
  [WorkflowNode.idea_interpretation]: "Idea interpretation",
  [WorkflowNode.idea_decomposition]: "Idea decomposition",
  [WorkflowNode.research_inputs]: "Research inputs",
  [WorkflowNode.related_work]: "Related work",
  [WorkflowNode.gap]: "Gap",
  [WorkflowNode.contribution]: "Contribution direction",
  [WorkflowNode.claims]: "Claims",
  [WorkflowNode.evidence]: "Evidence",
  [WorkflowNode.experiment_plan]: "Experiment plan",
  [WorkflowNode.feasibility]: "Feasibility",
  [WorkflowNode.gap_judge]: "Gap Judge",
  [WorkflowNode.contribution_judge]: "Contribution Judge",
  [WorkflowNode.evidence_judge]: "Evidence Judge",
  [WorkflowNode.experiment_judge]: "Experiment Judge",
  [WorkflowNode.conference_judge]: "Conference Judge",
  [WorkflowNode.aggregator]: "Aggregator",
};

export function catalogStage(id: LoopStage) {
  const stage = LOOP_STAGE_CATALOG.find((entry) => entry.id === id);
  if (!stage) {
    throw new Error(`Loop Stage ${id} is missing from the catalog`);
  }
  return stage;
}

export function isLoopStage(value: string | null): value is LoopStage {
  return Object.values(LoopStage).some((stage) => stage === value);
}

export function stageForWorkflowNode(node: WorkflowNode): LoopStage {
  const stage = LOOP_STAGE_CATALOG.find((entry) =>
    (entry.nodes as readonly WorkflowNode[]).includes(node),
  );
  if (!stage) {
    throw new Error(`Workflow Node ${node} is missing from the Loop Stage catalog`);
  }
  return stage.id;
}

export const CARD_KIND_OWNER: Record<CardKind, WorkflowNode> = {
  [CardKind.problem]: WorkflowNode.idea_decomposition,
  [CardKind.research_question]: WorkflowNode.idea_decomposition,
  [CardKind.constraint]: WorkflowNode.idea_decomposition,
  [CardKind.open_question]: WorkflowNode.idea_decomposition,
  [CardKind.gap]: WorkflowNode.gap,
  [CardKind.contribution]: WorkflowNode.contribution,
  [CardKind.claim]: WorkflowNode.claims,
  [CardKind.evidence]: WorkflowNode.evidence,
};

export const CARD_KIND_LABELS: Record<CardKind, string> = {
  [CardKind.problem]: "Problem",
  [CardKind.research_question]: "Research question",
  [CardKind.gap]: "Gap",
  [CardKind.contribution]: "Contribution",
  [CardKind.claim]: "Claim",
  [CardKind.evidence]: "Evidence",
  [CardKind.constraint]: "Constraint",
  [CardKind.open_question]: "Open question",
};

export function ownedCardKinds(node: WorkflowNode): CardKind[] {
  return (Object.values(CardKind) as CardKind[]).filter((kind) => CARD_KIND_OWNER[kind] === node);
}

export function resolveSelectedStage(
  stageQuery: string | null,
  workingDraftNode: WorkflowNode,
): LoopStage {
  if (isLoopStage(stageQuery) && stageQuery !== LoopStage.contribution) {
    return stageQuery;
  }
  return stageForWorkflowNode(workingDraftNode);
}

export function ancestors(node: WorkflowNode): Set<WorkflowNode> {
  const found = new Set<WorkflowNode>();
  const stack = Object.entries(INVALIDATION_CHILDREN)
    .filter(([, children]) => children.includes(node))
    .map(([parent]) => parent as WorkflowNode);
  while (stack.length > 0) {
    const parent = stack.pop();
    if (!parent || found.has(parent)) {
      continue;
    }
    found.add(parent);
    stack.push(
      ...Object.entries(INVALIDATION_CHILDREN)
        .filter(([, children]) => children.includes(parent))
        .map(([grandparent]) => grandparent as WorkflowNode),
    );
  }
  return found;
}

export function descendants(node: WorkflowNode): Set<WorkflowNode> {
  const found = new Set<WorkflowNode>();
  const stack = [...INVALIDATION_CHILDREN[node]];
  while (stack.length > 0) {
    const child = stack.pop();
    if (!child || found.has(child)) {
      continue;
    }
    found.add(child);
    stack.push(...INVALIDATION_CHILDREN[child]);
  }
  return found;
}

export function upstreamOfStage(stage: LoopStage): Set<WorkflowNode> {
  const stageNodes = new Set<WorkflowNode>(catalogStage(stage).nodes);
  const upstream = new Set<WorkflowNode>();
  for (const node of stageNodes) {
    for (const parent of ancestors(node)) {
      if (!stageNodes.has(parent)) {
        upstream.add(parent);
      }
    }
  }
  return upstream;
}
