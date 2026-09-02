"""Loop catalog: Workflow Nodes, Loop Stages, invalidation edges, Card owners."""

from enum import StrEnum


class WorkflowNode(StrEnum):
    IDEA_INTERPRETATION = "idea_interpretation"
    IDEA_DECOMPOSITION = "idea_decomposition"
    RESEARCH_INPUTS = "research_inputs"
    RELATED_WORK = "related_work"
    GAP = "gap"
    CONTRIBUTION = "contribution"
    CLAIMS = "claims"
    EVIDENCE = "evidence"
    EXPERIMENT_PLAN = "experiment_plan"
    FEASIBILITY = "feasibility"
    GAP_JUDGE = "gap_judge"
    CONTRIBUTION_JUDGE = "contribution_judge"
    EVIDENCE_JUDGE = "evidence_judge"
    EXPERIMENT_JUDGE = "experiment_judge"
    CONFERENCE_JUDGE = "conference_judge"
    AGGREGATOR = "aggregator"


class LoopStage(StrEnum):
    GRILLING = "grilling"
    RELATED_WORK = "related_work"
    GAP = "gap"
    CONTRIBUTION = "contribution"
    CLAIMS_EVIDENCE = "claims_evidence"
    EXPERIMENT_PLANNING = "experiment_planning"
    SPEC_DRAFT = "spec_draft"
    INDEPENDENT_JUDGES = "independent_judges"
    READINESS = "readiness"


class CardKind(StrEnum):
    PROBLEM = "problem"
    RESEARCH_QUESTION = "research_question"
    GAP = "gap"
    CONTRIBUTION = "contribution"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    CONSTRAINT = "constraint"
    OPEN_QUESTION = "open_question"


class NodeHeadStatus(StrEnum):
    EMPTY = "empty"
    CURRENT = "current"
    STALE = "stale"


class DecisionKind(StrEnum):
    CONFIRM = "confirm"
    EDIT = "edit"
    PICK = "pick"
    REVERT = "revert"
    EXPORT_ACK = "export_ack"


WORKFLOW_NODES: tuple[WorkflowNode, ...] = tuple(
    node for node in WorkflowNode if node is not WorkflowNode.EVIDENCE
)

LOOP_STAGE_NODES: dict[LoopStage, tuple[WorkflowNode, ...]] = {
    LoopStage.GRILLING: (
        WorkflowNode.IDEA_INTERPRETATION,
        WorkflowNode.IDEA_DECOMPOSITION,
    ),
    LoopStage.RELATED_WORK: (
        WorkflowNode.RESEARCH_INPUTS,
        WorkflowNode.RELATED_WORK,
    ),
    LoopStage.GAP: (WorkflowNode.GAP,),
    LoopStage.CONTRIBUTION: (WorkflowNode.CONTRIBUTION,),
    LoopStage.CLAIMS_EVIDENCE: (WorkflowNode.CLAIMS,),
    LoopStage.EXPERIMENT_PLANNING: (
        WorkflowNode.EXPERIMENT_PLAN,
        WorkflowNode.FEASIBILITY,
    ),
    LoopStage.SPEC_DRAFT: (),
    LoopStage.INDEPENDENT_JUDGES: (
        WorkflowNode.GAP_JUDGE,
        WorkflowNode.CONTRIBUTION_JUDGE,
        WorkflowNode.EVIDENCE_JUDGE,
        WorkflowNode.EXPERIMENT_JUDGE,
        WorkflowNode.CONFERENCE_JUDGE,
        WorkflowNode.AGGREGATOR,
    ),
    LoopStage.READINESS: (),
}

# parent → children (invalidation DAG). Spec Version is not a node; feasibility feeds conference_judge.
_EDGES: dict[WorkflowNode, tuple[WorkflowNode, ...]] = {
    WorkflowNode.IDEA_INTERPRETATION: (WorkflowNode.IDEA_DECOMPOSITION,),
    WorkflowNode.IDEA_DECOMPOSITION: (
        WorkflowNode.RESEARCH_INPUTS,
        WorkflowNode.GAP_JUDGE,
    ),
    WorkflowNode.RESEARCH_INPUTS: (WorkflowNode.RELATED_WORK,),
    WorkflowNode.RELATED_WORK: (
        WorkflowNode.GAP,
        WorkflowNode.GAP_JUDGE,
        WorkflowNode.CONTRIBUTION_JUDGE,
        WorkflowNode.EVIDENCE_JUDGE,
    ),
    WorkflowNode.GAP: (
        WorkflowNode.CONTRIBUTION,
        WorkflowNode.GAP_JUDGE,
        WorkflowNode.CONTRIBUTION_JUDGE,
    ),
    WorkflowNode.CONTRIBUTION: (
        WorkflowNode.CLAIMS,
        WorkflowNode.CONTRIBUTION_JUDGE,
        WorkflowNode.EXPERIMENT_JUDGE,
    ),
    WorkflowNode.CLAIMS: (
        WorkflowNode.EXPERIMENT_PLAN,
        WorkflowNode.EVIDENCE_JUDGE,
        WorkflowNode.EXPERIMENT_JUDGE,
    ),
    WorkflowNode.EVIDENCE: (),
    WorkflowNode.EXPERIMENT_PLAN: (
        WorkflowNode.FEASIBILITY,
        WorkflowNode.EXPERIMENT_JUDGE,
    ),
    WorkflowNode.FEASIBILITY: (
        WorkflowNode.EXPERIMENT_JUDGE,
        WorkflowNode.CONFERENCE_JUDGE,
    ),
    WorkflowNode.GAP_JUDGE: (WorkflowNode.AGGREGATOR,),
    WorkflowNode.CONTRIBUTION_JUDGE: (WorkflowNode.AGGREGATOR,),
    WorkflowNode.EVIDENCE_JUDGE: (WorkflowNode.AGGREGATOR,),
    WorkflowNode.EXPERIMENT_JUDGE: (WorkflowNode.AGGREGATOR,),
    WorkflowNode.CONFERENCE_JUDGE: (WorkflowNode.AGGREGATOR,),
    WorkflowNode.AGGREGATOR: (),
}

FIVE_JUDGE_NODES: tuple[WorkflowNode, ...] = (
    WorkflowNode.GAP_JUDGE,
    WorkflowNode.CONTRIBUTION_JUDGE,
    WorkflowNode.EVIDENCE_JUDGE,
    WorkflowNode.EXPERIMENT_JUDGE,
    WorkflowNode.CONFERENCE_JUDGE,
)

CARD_KIND_OWNERS: dict[CardKind, tuple[WorkflowNode, ...]] = {
    CardKind.PROBLEM: (WorkflowNode.IDEA_DECOMPOSITION,),
    CardKind.RESEARCH_QUESTION: (WorkflowNode.IDEA_DECOMPOSITION,),
    CardKind.CONSTRAINT: (WorkflowNode.IDEA_DECOMPOSITION,),
    CardKind.OPEN_QUESTION: (WorkflowNode.IDEA_DECOMPOSITION,),
    CardKind.GAP: (WorkflowNode.GAP,),
    CardKind.CONTRIBUTION: (WorkflowNode.CONTRIBUTION,),
    CardKind.CLAIM: (WorkflowNode.CLAIMS,),
    CardKind.EVIDENCE: (WorkflowNode.CLAIMS,),
}

_OWNER_KINDS: dict[WorkflowNode, tuple[CardKind, ...]] = {}
for _kind, _owners in CARD_KIND_OWNERS.items():
    for _owner in _owners:
        _OWNER_KINDS[_owner] = (*_OWNER_KINDS.get(_owner, ()), _kind)


def owned_kinds(node: WorkflowNode) -> tuple[CardKind, ...]:
    return _OWNER_KINDS.get(node, ())


def active_workflow_node(node: WorkflowNode) -> WorkflowNode:
    if node is WorkflowNode.EVIDENCE:
        return WorkflowNode.CLAIMS
    return node


def _card_body_nonblank(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    for key in ("text", "statement", "claim", "evidence"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def claims_confirmable(cards: object) -> bool:
    kinds: set[CardKind] = set()
    if not isinstance(cards, list):
        return False
    for card in cards:
        kind_raw = getattr(card, "kind", None)
        body = getattr(card, "body", None)
        if kind_raw is None and isinstance(card, dict):
            kind_raw = card.get("kind")
            body = card.get("body")
        try:
            kind = kind_raw if isinstance(kind_raw, CardKind) else CardKind(str(kind_raw))
        except ValueError:
            continue
        if kind in (CardKind.CLAIM, CardKind.EVIDENCE) and _card_body_nonblank(body):
            kinds.add(kind)
    return CardKind.CLAIM in kinds and CardKind.EVIDENCE in kinds


HANDLING_OPTION_TARGETS: frozenset[str] = frozenset(
    {
        WorkflowNode.GAP.value,
        WorkflowNode.CONTRIBUTION.value,
        WorkflowNode.CLAIMS.value,
        WorkflowNode.EXPERIMENT_PLAN.value,
        WorkflowNode.IDEA_DECOMPOSITION.value,
    }
)


def descendants(node: WorkflowNode) -> frozenset[WorkflowNode]:
    found: set[WorkflowNode] = set()
    stack = list(_EDGES[node])
    while stack:
        child = stack.pop()
        if child in found:
            continue
        found.add(child)
        stack.extend(_EDGES[child])
    return frozenset(found)


def ancestors(node: WorkflowNode) -> frozenset[WorkflowNode]:
    found: set[WorkflowNode] = set()
    stack = [parent for parent, children in _EDGES.items() if node in children]
    while stack:
        parent = stack.pop()
        if parent in found:
            continue
        found.add(parent)
        stack.extend(p for p, children in _EDGES.items() if parent in children)
    return frozenset(found)


def upstream_of_stage(stage: LoopStage) -> frozenset[WorkflowNode]:
    stage_nodes = set(LOOP_STAGE_NODES[stage])
    up: set[WorkflowNode] = set()
    for node in stage_nodes:
        up.update(ancestors(node) - stage_nodes)
    return frozenset(up)


def first_needs_work(
    stage: LoopStage,
    status_by_node: dict[WorkflowNode, NodeHeadStatus],
) -> WorkflowNode | None:
    for node in LOOP_STAGE_NODES[stage]:
        if status_by_node[node] in (NodeHeadStatus.EMPTY, NodeHeadStatus.STALE):
            return node
    return None


def prepare_landing(
    stage: LoopStage,
    status_by_node: dict[WorkflowNode, NodeHeadStatus],
) -> WorkflowNode | None:
    needs_work = first_needs_work(stage, status_by_node)
    if needs_work is None:
        return None
    if stage is LoopStage.INDEPENDENT_JUDGES:
        return WorkflowNode.AGGREGATOR
    return needs_work
