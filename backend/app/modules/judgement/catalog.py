"""Finding Kind catalog and Severity floors for Judge Issues."""

from enum import StrEnum

from app.modules.loop.catalog import LOOP_STAGE_NODES, LoopStage, WorkflowNode

JUDGE_NODES: frozenset[WorkflowNode] = frozenset(
    LOOP_STAGE_NODES[LoopStage.INDEPENDENT_JUDGES]
)

GENERATABLE_JUDGE_NODES: frozenset[WorkflowNode] = frozenset(
    {
        WorkflowNode.GAP_JUDGE,
        WorkflowNode.CONTRIBUTION_JUDGE,
        WorkflowNode.EVIDENCE_JUDGE,
        WorkflowNode.EXPERIMENT_JUDGE,
    }
)


class FindingKind(StrEnum):
    GAP_UNSUPPORTED_BY_SOURCES = "gap_unsupported_by_sources"
    GAP_ALREADY_ADDRESSED = "gap_already_addressed"
    GAP_UNTESTABLE = "gap_untestable"
    CONTRIBUTION_NOT_NOVEL = "contribution_not_novel"
    CONTRIBUTION_OVERCLAIMED = "contribution_overclaimed"
    UNSUPPORTED_CITATION = "unsupported_citation"
    CLAIM_BROADER_THAN_EXPERIMENT = "claim_broader_than_experiment"
    EXPERIMENT_INSUFFICIENT_FOR_CLAIM = "experiment_insufficient_for_claim"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.MINOR: 0,
    Severity.MAJOR: 1,
    Severity.CRITICAL: 2,
}

FINDING_KIND_FLOOR: dict[FindingKind, Severity] = {
    FindingKind.GAP_UNSUPPORTED_BY_SOURCES: Severity.CRITICAL,
    FindingKind.GAP_ALREADY_ADDRESSED: Severity.CRITICAL,
    FindingKind.GAP_UNTESTABLE: Severity.MAJOR,
    FindingKind.CONTRIBUTION_NOT_NOVEL: Severity.MAJOR,
    FindingKind.CONTRIBUTION_OVERCLAIMED: Severity.MAJOR,
    FindingKind.UNSUPPORTED_CITATION: Severity.CRITICAL,
    FindingKind.CLAIM_BROADER_THAN_EXPERIMENT: Severity.MAJOR,
    FindingKind.EXPERIMENT_INSUFFICIENT_FOR_CLAIM: Severity.MAJOR,
}


def apply_floor(kind: FindingKind, severity: Severity) -> Severity:
    floor = FINDING_KIND_FLOOR[kind]
    if SEVERITY_RANK[severity] < SEVERITY_RANK[floor]:
        return floor
    return severity


def parse_finding_kind(raw: str) -> FindingKind | None:
    try:
        return FindingKind(raw)
    except ValueError:
        return None


def parse_severity(raw: str) -> Severity | None:
    try:
        return Severity(raw.upper())
    except ValueError:
        return None
