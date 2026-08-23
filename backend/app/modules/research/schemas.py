"""Backend contracts for the Research Workflow Nodes."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    WARNING = "warning"
    REJECTED = "rejected"


class GroundingStatus(StrEnum):
    PENDING = "pending"
    GROUNDED = "grounded"
    WARNING = "warning"
    REJECTED = "rejected"


class GapStatus(StrEnum):
    PROPOSED = "proposed"


class ResearchNode(StrEnum):
    RESEARCH_INPUTS = "research_inputs"
    RELATED_WORK = "related_work"
    GAP = "gap"


class PreferredSources(BaseModel):
    peer_reviewed_papers: bool = True
    official_proceedings: bool = True
    author_materials: bool = True
    sourced_surveys: bool = True


class ResearchInputs(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    preferred_sources: PreferredSources = Field(default_factory=PreferredSources)


class CitationBase(BaseModel):
    citation_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=9999)
    venue: str | None = None
    doi: str | None = Field(default=None, max_length=255)
    url: str | None = None
    provider: str | None = Field(default=None, max_length=100)
    provider_source_id: str | None = Field(default=None, max_length=255)
    abstract: str | None = None
    retrieved_at: datetime | None = None
    verification_status: VerificationStatus = VerificationStatus.PENDING
    metadata: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "source_metadata"),
    )

    @field_validator("citation_key", "title")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()


class CitationCreate(CitationBase):
    id: UUID | None = None


class CitationResponse(CitationBase):
    id: UUID
    session_id: UUID
    stage_revision_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceEvidence(BaseModel):
    passage: str = Field(min_length=1)
    location: str = Field(min_length=1)


class RelatedWorkFindingBase(BaseModel):
    citation_id: UUID
    what_was_done: str = Field(min_length=1)
    method_or_feedback: str | None = None
    limitation: str = Field(min_length=1)
    relevance: str | None = None
    supporting_passage: str = Field(min_length=1)
    evidence: dict[str, SourceEvidence] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    grounding_status: GroundingStatus = GroundingStatus.PENDING


class RelatedWorkFindingCreate(RelatedWorkFindingBase):
    id: UUID | None = None


class RelatedWorkFindingResponse(RelatedWorkFindingBase):
    id: UUID
    session_id: UUID
    stage_revision_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GapCardBody(BaseModel):
    statement: str = Field(min_length=1)
    supporting_citation_keys: list[str] = Field(default_factory=list)
    status: GapStatus = GapStatus.PROPOSED


class ResearchGenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    max_results: int = Field(default=5, ge=1, le=5)


class ProgressEvent(BaseModel):
    type: str = "progress"
    node: ResearchNode
    message: str
    pct: int = Field(ge=0, le=100)


class CitationUpsertEvent(BaseModel):
    type: str = "citation_upsert"
    node: ResearchNode = ResearchNode.RELATED_WORK
    citation: CitationResponse


class DraftPatchEvent(BaseModel):
    type: str = "draft_patch"
    node: ResearchNode
    narrative: dict


class WarningEvent(BaseModel):
    type: str = "warning"
    node: ResearchNode
    code: str
    message: str


class DoneEvent(BaseModel):
    type: str = "done"
    node: ResearchNode
    version: int
    citation_count: int = 0


class ErrorEvent(BaseModel):
    type: str = "error"
    node: ResearchNode
    code: str
    message: str
