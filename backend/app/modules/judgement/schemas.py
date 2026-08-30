"""Judgement HTTP contracts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

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


class JudgeIssueDraft(BaseModel):
    finding_kind: str
    severity: str
    reason: str = ""
    suggestion: str = ""
    target_card_id: UUID | None = None


class JudgeLlmResponse(BaseModel):
    issues: list[JudgeIssueDraft] = Field(default_factory=list)


class JudgeIssueResponse(BaseModel):
    id: UUID
    finding_kind: str
    severity: str
    reason: str
    suggestion: str
    target_card_id: UUID | None = None

    model_config = {"from_attributes": True}


class JudgeRunResponse(BaseModel):
    node: JudgementNode
    issues: list[JudgeIssueResponse]


class ProgressEvent(BaseModel):
    type: str = "progress"
    node: JudgementNode
    message: str
    pct: int = Field(ge=0, le=100)


class DraftPatchEvent(BaseModel):
    type: str = "draft_patch"
    node: JudgementNode
    issues: list[JudgeIssueResponse]


class DoneEvent(BaseModel):
    type: str = "done"
    node: JudgementNode
    version: int


class ErrorEvent(BaseModel):
    type: str = "error"
    node: JudgementNode
    code: str
    message: str
