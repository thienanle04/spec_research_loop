"""Loop HTTP schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.loop.catalog import CardKind, LoopStage, NodeHeadStatus, WorkflowNode


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class PatchSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class WorkingDraftPatchRequest(BaseModel):
    node: WorkflowNode | None = None
    narrative: dict[str, Any] | None = None
    expected_version: int = Field(ge=1)


class ConfirmRequest(BaseModel):
    node: WorkflowNode
    expected_version: int = Field(ge=1)
    stale_reaccept: bool = False


class HandlingOptionPickRequest(BaseModel):
    expected_version: int = Field(ge=1)
    handling_option_id: UUID | None = None
    prose: str | None = None
    target_node: WorkflowNode | None = None


class PrepareRequest(BaseModel):
    stage: LoopStage
    expected_version: int = Field(ge=1)


class CreateCardRequest(BaseModel):
    kind: CardKind
    body: dict[str, Any] = Field(default_factory=dict)
    expected_version: int = Field(ge=1)


class PatchCardRequest(BaseModel):
    body: dict[str, Any]
    expected_version: int = Field(ge=1)


class ReplaceCardsRequest(BaseModel):
    kind: CardKind
    bodies: list[dict[str, Any]] = Field(min_length=1)
    expected_version: int = Field(ge=1)


class HeadRevisionResponse(BaseModel):
    narrative: dict[str, Any]
    card_snapshot: list[dict[str, Any]]


class NodeHeadResponse(BaseModel):
    node: WorkflowNode
    status: NodeHeadStatus
    stage_revision_id: UUID | None
    generated_since_prepare: bool = False
    head_revision: HeadRevisionResponse | None = None

    model_config = {"from_attributes": True}


class CardResponse(BaseModel):
    id: UUID
    kind: CardKind
    body: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CardMutationResponse(CardResponse):
    version: int


class CardBatchMutationResponse(BaseModel):
    cards: list[CardResponse]
    version: int


class SpecVersionResponse(BaseModel):
    id: UUID
    document: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadinessSummary(BaseModel):
    state: str
    notice: str
    scores: dict[str, int] | None = None


class SpecArtifactExportRequest(BaseModel):
    critical_export_ack: bool = False


class SpecArtifactResponse(BaseModel):
    spec_version_id: UUID
    document: dict[str, Any]


class DecisionResponse(BaseModel):
    id: UUID
    kind: str
    node: WorkflowNode | None
    stage_revision_id: UUID | None
    detail: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StageRevisionResponse(BaseModel):
    id: UUID
    node: WorkflowNode
    revision_n: int
    narrative: dict[str, Any]
    card_snapshot: list[dict[str, Any]]
    freeze_hash: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LoopSessionResponse(BaseModel):
    id: UUID
    title: str | None
    version: int
    working_draft_node: WorkflowNode
    working_draft_narrative: dict[str, Any]
    node_heads: list[NodeHeadResponse]
    cards: list[CardResponse]
    stage_revisions: list[StageRevisionResponse]
    produced_spec_version: SpecVersionResponse | None
    valid_spec_version_id: UUID | None
    readiness: ReadinessSummary
    created_at: datetime
    updated_at: datetime


class LoopSessionSummary(BaseModel):
    id: UUID
    title: str | None
    version: int
    working_draft_node: WorkflowNode
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
