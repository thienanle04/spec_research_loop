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
    description: "Locate and assess prior work.",
    nodes: [WorkflowNode.research_inputs, WorkflowNode.related_work],
  },
  {
    id: LoopStage.gap,
    name: "Gap",
    description: "Synthesize the research gap from related work.",
    nodes: [WorkflowNode.gap],
  },
  {
    id: LoopStage.contribution,
    name: "Contribution",
    description: "Choose a contribution direction after the gap.",
    nodes: [WorkflowNode.contribution],
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
    id: LoopStage.spec_draft,
    name: "Spec Draft",
    description: "Read the Produced Spec Version before Independent judges.",
    nodes: [],
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
type MissingStage = Exclude<LoopStage, CatalogStageId>;
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

export const HANDLING_OPTION_TARGETS = [
  WorkflowNode.gap,
  WorkflowNode.contribution,
  WorkflowNode.claims,
  WorkflowNode.evidence,
  WorkflowNode.experiment_plan,
  WorkflowNode.idea_decomposition,
] as const;

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

export function isIndependentJudgeNode(node: WorkflowNode): boolean {
  return (
    stageForWorkflowNode(node) === LoopStage.independent_judges &&
    node !== WorkflowNode.aggregator
  );
}

export function stagePathNodes(stage: LoopStage): readonly WorkflowNode[] {
  if (stage === LoopStage.independent_judges) {
    return [];
  }
  return catalogStage(stage).nodes;
}

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

export const CARD_KIND_OWNERS: Record<CardKind, WorkflowNode[]> = {
  [CardKind.problem]: [WorkflowNode.idea_decomposition],
  [CardKind.research_question]: [WorkflowNode.idea_decomposition],
  [CardKind.constraint]: [WorkflowNode.idea_decomposition],
  [CardKind.open_question]: [WorkflowNode.idea_decomposition],
  [CardKind.gap]: [WorkflowNode.gap],
  [CardKind.contribution]: [WorkflowNode.contribution],
  [CardKind.claim]: [WorkflowNode.claims, WorkflowNode.evidence],
  [CardKind.evidence]: [WorkflowNode.evidence],
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
  return (Object.values(CardKind) as CardKind[]).filter((kind) => CARD_KIND_OWNERS[kind].includes(node));
}

export function resolveSelectedStage(
  stageQuery: string | null,
  workingDraftNode: WorkflowNode,
): LoopStage {
  if (isLoopStage(stageQuery)) {
    return stageQuery;
  }
  return stageForWorkflowNode(workingDraftNode);
}

export function isWorkflowNode(value: string | null): value is WorkflowNode {
  return Object.values(WorkflowNode).some((node) => node === value);
}

export type NavStop = {
  stage: LoopStage;
  node?: WorkflowNode;
  exportScratch?: boolean;
  specVersionId?: string;
};

export function navStops(): NavStop[] {
  return LOOP_STAGE_CATALOG.flatMap((stage) => {
    if (stage.id === LoopStage.independent_judges || stage.nodes.length === 0) {
      return [{ stage: stage.id }];
    }
    return [...stage.nodes].map((node) => ({ stage: stage.id, node }));
  });
}

export function sessionHref(sessionId: string, stop: NavStop): string {
  const params = new URLSearchParams({ stage: stop.stage });
  if (stop.node) {
    params.set("node", stop.node);
  }
  if (stop.exportScratch && stop.stage === LoopStage.readiness) {
    params.set("export_scratch", "1");
    if (stop.specVersionId) {
      params.set("spec_version", stop.specVersionId);
    }
  }
  return `/sessions/${sessionId}?${params.toString()}`;
}

export function isExportScratchEditorOpen(
  stage: LoopStage | null,
  searchParams: { get: (name: string) => string | null },
): boolean {
  return stage === LoopStage.readiness && searchParams.get("export_scratch") === "1";
}

export function railStop(stage: LoopStage): NavStop {
  if (stage === LoopStage.independent_judges) {
    return { stage };
  }
  const nodes = catalogStage(stage).nodes as readonly WorkflowNode[];
  return nodes[0] ? { stage, node: nodes[0] } : { stage };
}

export function resolveSelectedNode(
  stage: LoopStage,
  nodeQuery: string | null,
  workingDraftNode: WorkflowNode,
): WorkflowNode | undefined {
  const nodes = catalogStage(stage).nodes as readonly WorkflowNode[];
  if (stage === LoopStage.independent_judges) {
    if (nodes.includes(workingDraftNode)) {
      return workingDraftNode;
    }
    return WorkflowNode.aggregator;
  }
  if (nodes.length === 0) {
    return undefined;
  }
  if (isWorkflowNode(nodeQuery) && nodes.includes(nodeQuery)) {
    return nodeQuery;
  }
  if (!nodeQuery && nodes.includes(workingDraftNode)) {
    return workingDraftNode;
  }
  return nodes[0];
}

export function adjacentStop(current: NavStop, delta: -1 | 1): NavStop | null {
  const stops = navStops();
  const index = stops.findIndex(
    (stop) => stop.stage === current.stage && stop.node === current.node,
  );
  if (index < 0) {
    return null;
  }
  return stops[index + delta] ?? null;
}

export function workingDraftStop(node: WorkflowNode): NavStop {
  const stage = stageForWorkflowNode(node);
  if (stage === LoopStage.independent_judges) {
    return { stage };
  }
  return { stage, node };
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
