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
    CANDIDATE = "candidate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    # Backward-compatible read support for Gap Cards created before search audits.
    PROPOSED = "proposed"


class CounterEvidenceOutcome(StrEnum):
    NO_DIRECT_COUNTER_EVIDENCE = "no_direct_counter_evidence"
    GAP_NARROWED = "gap_narrowed"
    GAP_NOT_SUPPORTED = "gap_not_supported"
    INCONCLUSIVE = "inconclusive"


class CounterEvidenceResult(BaseModel):
    """A persisted metadata-only assessment of one counter-evidence source."""

    result_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=9999)
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    provider: str | None = None
    provider_source_id: str | None = None
    abstract: str | None = None
    retrieval_score: float | None = Field(default=None, ge=0, le=1)
    reranker_score: float | None = Field(default=None, ge=0, le=1)
    discovery_queries: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.PENDING
    verification_messages: list[str] = Field(default_factory=list)
    impact: CounterEvidenceOutcome = CounterEvidenceOutcome.INCONCLUSIVE
    rationale: str = "This result was not included in the validated assessment."


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
    is_active: bool = True
    pinned: bool = False
    retrieval_score: float | None = Field(default=None, ge=0, le=1)
    text_object_key: str | None = None
    text_source_url: str | None = None
    text_source_kind: str | None = None
    text_checksum: str | None = None
    text_char_count: int | None = Field(default=None, ge=0)
    text_retrieved_at: datetime | None = None
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
    source_object_key: str | None = None
    source_location: str | None = None
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


class GapSearchAudit(BaseModel):
    related_work_queries: list[str] = Field(default_factory=list)
    counter_evidence_queries: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    related_work_candidate_count: int = Field(default=0, ge=0)
    related_work_analyzed_count: int = Field(default=0, ge=0, le=5)
    counter_evidence_candidate_count: int = Field(default=0, ge=0)
    counter_evidence_analyzed_count: int = Field(default=0, ge=0, le=5)
    counter_evidence_outcome: CounterEvidenceOutcome = (
        CounterEvidenceOutcome.INCONCLUSIVE
    )
    counter_evidence_assessment: str = ""
    counter_evidence_results: list[CounterEvidenceResult] = Field(default_factory=list)
    completed_at: datetime | None = None
    complete: bool = False


class GapEvidenceCheck(BaseModel):
    verified_citation_keys: list[str] = Field(default_factory=list)
    grounded_citation_keys: list[str] = Field(default_factory=list)
    eligible_citation_keys: list[str] = Field(default_factory=list)
    ready: bool = False
    messages: list[str] = Field(default_factory=list)


class GapCardBody(BaseModel):
    statement: str = Field(min_length=1)
    supporting_citation_keys: list[str] = Field(default_factory=list)
    status: GapStatus = GapStatus.INSUFFICIENT_EVIDENCE
    search_audit: GapSearchAudit = Field(default_factory=GapSearchAudit)
    evidence_check: GapEvidenceCheck = Field(default_factory=GapEvidenceCheck)

    def is_confirmable(self) -> bool:
        # Evidence readiness is advisory. An Account may confirm a Gap Candidate
        # after reviewing the warnings, including a negative or inconclusive audit.
        return bool(self.statement.strip())


class ResearchGenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    max_results: int = Field(default=5, ge=1, le=5)


class CitationSelectionUpdate(BaseModel):
    pinned: bool


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
