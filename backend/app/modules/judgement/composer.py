"""Deterministic Aggregator composer: copy Severity, group, never majority-vote."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.judgement.catalog import Severity
from app.modules.loop.catalog import FIVE_JUDGE_NODES, WorkflowNode

CLUSTER_CONSENSUS = "consensus"
CLUSTER_DISAGREEMENT = "disagreement"

HANDLING_OPTION_TARGETS: frozenset[str] = frozenset(
    {
        WorkflowNode.GAP.value,
        WorkflowNode.CONTRIBUTION.value,
        WorkflowNode.CLAIMS.value,
        WorkflowNode.EVIDENCE.value,
        WorkflowNode.EXPERIMENT_PLAN.value,
        WorkflowNode.IDEA_DECOMPOSITION.value,
    }
)


@dataclass
class CopiedIssue:
    source_node: str
    source_issue_id: UUID | None
    finding_kind: str
    severity: str
    reason: str
    suggestion: str
    target_card_id: UUID | None
    cluster: str


@dataclass
class ComposedReport:
    issues: list[CopiedIssue]
    scores: dict[str, int] | None
    readiness: str


def compose_from_view(view: dict[str, Any]) -> ComposedReport:
    issues: list[CopiedIssue] = []
    scores: dict[str, int] | None = None
    runs = view.get("judge_runs")
    if not isinstance(runs, list):
        runs = []
    allowed_nodes = {node.value for node in FIVE_JUDGE_NODES}
    for run in runs:
        if not isinstance(run, dict):
            continue
        source = run.get("node")
        if source not in allowed_nodes:
            continue
        raw_scores = run.get("scores")
        if isinstance(raw_scores, dict) and source == WorkflowNode.CONFERENCE_JUDGE.value:
            keys = (
                "originality",
                "significance",
                "soundness",
                "clarity",
                "reproducibility",
            )
            if all(key in raw_scores for key in keys):
                scores = {key: int(raw_scores[key]) for key in keys}
        raw_issues = run.get("issues")
        if not isinstance(raw_issues, list):
            continue
        for item in raw_issues:
            copied = _copy_issue(source, item)
            if copied is not None:
                issues.append(copied)
    _assign_clusters(issues)
    readiness = (
        "blocked"
        if any(item.severity == Severity.CRITICAL.value for item in issues)
        else "ready"
    )
    return ComposedReport(issues=issues, scores=scores, readiness=readiness)


def filter_handling_options(
    drafts: list[Any], issues: list[CopiedIssue]
) -> list[dict[str, str]]:
    offered: set[tuple[str, str]] = {
        (item.finding_kind, item.source_node)
        for item in issues
        if item.severity in {Severity.CRITICAL.value, Severity.MAJOR.value}
    }
    minor: set[tuple[str, str]] = {
        (item.finding_kind, item.source_node)
        for item in issues
        if item.severity == Severity.MINOR.value
    }
    kept: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for draft in drafts:
        finding_kind = str(getattr(draft, "finding_kind", "") or "").strip()
        source_node = str(getattr(draft, "source_node", "") or "").strip()
        label = str(getattr(draft, "label", "") or "").strip()
        target_node = str(getattr(draft, "target_node", "") or "").strip()
        prose = str(getattr(draft, "prose", "") or "").strip()
        if not finding_kind or not source_node or not label or not target_node:
            continue
        if _is_other(label) or _is_other(target_node):
            continue
        if target_node not in HANDLING_OPTION_TARGETS:
            continue
        key = (finding_kind, source_node)
        if key in minor or key not in offered:
            continue
        option_key = (finding_kind, source_node, target_node)
        if option_key in seen:
            continue
        seen.add(option_key)
        kept.append(
            {
                "finding_kind": finding_kind,
                "source_node": source_node,
                "label": label,
                "target_node": target_node,
                "prose": prose,
            }
        )
    return kept


def _copy_issue(source_node: str, item: Any) -> CopiedIssue | None:
    if not isinstance(item, dict):
        return None
    finding_kind = item.get("finding_kind")
    severity = item.get("severity")
    if not isinstance(finding_kind, str) or not finding_kind:
        return None
    if severity not in {
        Severity.CRITICAL.value,
        Severity.MAJOR.value,
        Severity.MINOR.value,
    }:
        return None
    raw_id = item.get("id")
    source_issue_id = None
    if isinstance(raw_id, str) and raw_id:
        try:
            source_issue_id = UUID(raw_id)
        except ValueError:
            source_issue_id = None
    raw_card = item.get("target_card_id")
    target_card_id = None
    if isinstance(raw_card, str) and raw_card:
        try:
            target_card_id = UUID(raw_card)
        except ValueError:
            target_card_id = None
    reason = item.get("reason")
    suggestion = item.get("suggestion")
    return CopiedIssue(
        source_node=source_node,
        source_issue_id=source_issue_id,
        finding_kind=finding_kind,
        severity=severity,
        reason=reason if isinstance(reason, str) else "",
        suggestion=suggestion if isinstance(suggestion, str) else "",
        target_card_id=target_card_id,
        cluster=CLUSTER_DISAGREEMENT,
    )


def _assign_clusters(issues: list[CopiedIssue]) -> None:
    by_kind: dict[str, list[CopiedIssue]] = defaultdict(list)
    for item in issues:
        by_kind[item.finding_kind].append(item)
    for group in by_kind.values():
        nodes = {item.source_node for item in group}
        cluster = CLUSTER_CONSENSUS if len(nodes) >= 2 else CLUSTER_DISAGREEMENT
        for item in group:
            item.cluster = cluster


def _is_other(value: str) -> bool:
    return value.strip().casefold() == "other"
