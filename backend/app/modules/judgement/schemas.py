"""Judgement HTTP contracts."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from app.modules.loop.catalog import WorkflowNode


class JudgementNode(StrEnum):
    GAP_JUDGE = WorkflowNode.GAP_JUDGE.value
    CONTRIBUTION_JUDGE = WorkflowNode.CONTRIBUTION_JUDGE.value
    EVIDENCE_JUDGE = WorkflowNode.EVIDENCE_JUDGE.value
    EXPERIMENT_JUDGE = WorkflowNode.EXPERIMENT_JUDGE.value
    CONFERENCE_JUDGE = WorkflowNode.CONFERENCE_JUDGE.value
    AGGREGATOR = WorkflowNode.AGGREGATOR.value


class JudgementGenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    stale_reaccept: bool = False


class JudgeIssueExcerpt(BaseModel):
    citation_key: str = ""
    passage: str = ""


class JudgeIssueGrounds(BaseModel):
    subject: str = ""
    excerpts: list[JudgeIssueExcerpt] = Field(default_factory=list)


def parse_grounds(raw: Any) -> JudgeIssueGrounds:
    if isinstance(raw, JudgeIssueGrounds):
        return raw
    if isinstance(raw, dict):
        try:
            return JudgeIssueGrounds.model_validate(raw)
        except ValidationError:
            return JudgeIssueGrounds()
    return JudgeIssueGrounds()


def grounds_payload(grounds: JudgeIssueGrounds | dict[str, Any] | None) -> dict[str, Any]:
    return parse_grounds(grounds).model_dump()


class JudgeIssueDraft(BaseModel):
    finding_kind: str
    severity: str
    reason: str = ""
    suggestion: str = ""
    target_card_id: UUID | None = None
    grounds: JudgeIssueGrounds = Field(default_factory=JudgeIssueGrounds)


class JudgeLlmResponse(BaseModel):
    issues: list[JudgeIssueDraft] = Field(default_factory=list)


class ConferenceScores(BaseModel):
    originality: int = Field(ge=1, le=10)
    significance: int = Field(ge=1, le=10)
    soundness: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    reproducibility: int = Field(ge=1, le=10)


class ConferenceLlmResponse(BaseModel):
    scores: ConferenceScores


class HandlingOptionDraft(BaseModel):
    finding_kind: str = ""
    source_node: str = ""
    label: str = ""
    target_node: str = ""
    prose: str = ""


class AggregatorLlmResponse(BaseModel):
    options: list[HandlingOptionDraft] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class ReadinessState(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    BLOCKED = "blocked"
    READY = "ready"


READINESS_COPY = "This is not conference acceptance."


class JudgeIssueResponse(BaseModel):
    id: UUID
    finding_kind: str
    severity: str
    reason: str
    suggestion: str
    target_card_id: UUID | None = None
    source_node: str | None = None
    cluster: str | None = None
    grounds: JudgeIssueGrounds = Field(default_factory=JudgeIssueGrounds)

    model_config = {"from_attributes": True}


class HandlingOptionResponse(BaseModel):
    id: UUID
    finding_kind: str
    source_node: str
    label: str
    target_node: str
    prose: str
    aggregator_issue_id: UUID | None = None


class ClusterMap(BaseModel):
    consensus: list[JudgeIssueResponse] = Field(default_factory=list)
    disagreement: list[JudgeIssueResponse] = Field(default_factory=list)


class JudgeRunResponse(BaseModel):
    node: JudgementNode
    issues: list[JudgeIssueResponse]
    scores: ConferenceScores | None = None
    clusters: ClusterMap | None = None
    handling_options: list[HandlingOptionResponse] | None = None
    readiness: ReadinessState | None = None


class ReadinessResponse(BaseModel):
    state: ReadinessState
    notice: str = READINESS_COPY
    scores: ConferenceScores | None = None


class DraftPatchEvent(BaseModel):
    type: str = "draft_patch"
    node: JudgementNode
    issues: list[JudgeIssueResponse]
    scores: ConferenceScores | None = None
    clusters: ClusterMap | None = None
    handling_options: list[HandlingOptionResponse] | None = None
    readiness: ReadinessState | None = None


class ProgressEvent(BaseModel):
    type: str = "progress"
    node: JudgementNode
    message: str
    pct: int = Field(ge=0, le=100)


class DoneEvent(BaseModel):
    type: str = "done"
    node: JudgementNode
    version: int


class ErrorEvent(BaseModel):
    type: str = "error"
    node: JudgementNode
    code: str
    message: str
