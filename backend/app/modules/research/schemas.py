"""Backend contracts for the Research Workflow Nodes."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


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


class CounterEvidenceRelevance(StrEnum):
    PENDING = "pending"
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class CounterEvidenceSupport(StrEnum):
    PENDING = "pending"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"


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


class CounterEvidenceContentBasis(StrEnum):
    METADATA_ONLY = "metadata_only"
    ABSTRACT = "abstract"
    FULL_TEXT = "full_text"


class GapClaimKind(StrEnum):
    EXISTING_CAPABILITY = "existing_capability"
    UNRESOLVED_LIMITATION = "unresolved_limitation"
    TECHNICAL_MECHANISM = "technical_mechanism"
    HUMAN_EVALUATION = "human_evaluation"
    DOMAIN_SCOPE = "domain_scope"


class GapClaimEvidence(BaseModel):
    """A Related Work passage that directly anchors one atomic Gap claim."""

    citation_key: str = Field(min_length=1)
    passage: str = Field(min_length=1)
    location: str = Field(min_length=1)


class GapClaimAssessment(BaseModel):
    """One independently falsifiable clause used to build the final Gap."""

    claim_id: str = Field(min_length=1)
    kind: GapClaimKind
    statement: str = Field(min_length=1)
    supporting_citation_keys: list[str] = Field(default_factory=list)
    supporting_evidence: list[GapClaimEvidence] = Field(default_factory=list)
    counter_evidence_result_keys: list[str] = Field(default_factory=list)
    outcome: CounterEvidenceOutcome = CounterEvidenceOutcome.INCONCLUSIVE
    assessment: str = ""


class CounterEvidenceResult(BaseModel):
    """A persisted source assessment with identity and content checks kept separate."""

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
    content_basis: CounterEvidenceContentBasis = (
        CounterEvidenceContentBasis.METADATA_ONLY
    )
    source_object_key: str | None = None
    evidence_passage: str | None = None
    evidence_location: str | None = None
    grounding_status: GroundingStatus = GroundingStatus.PENDING
    relevance_status: CounterEvidenceRelevance = CounterEvidenceRelevance.PENDING
    support_status: CounterEvidenceSupport = CounterEvidenceSupport.PENDING
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
    assessed_statement: str = ""
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
    claim_assessments: list[GapClaimAssessment] = Field(default_factory=list)
    readiness_messages: list[str] = Field(default_factory=list)
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

    def evidence_readiness_messages(self) -> list[str]:
        messages: list[str] = []
        normalized_statement = " ".join(self.statement.casefold().split())
        normalized_assessed = " ".join(
            self.search_audit.assessed_statement.casefold().split()
        )
        supported = set(self.supporting_citation_keys)
        eligible = set(self.evidence_check.eligible_citation_keys)
        audit = self.search_audit
        results = audit.counter_evidence_results
        claims = audit.claim_assessments
        result_keys = [item.result_key for item in results]
        claim_ids = [item.claim_id for item in claims]

        if not normalized_statement:
            messages.append("The Gap statement is empty.")
        elif normalized_statement != normalized_assessed:
            messages.append("The Gap statement changed after the literature audit.")
        if not supported:
            messages.append("The Gap has no supporting Citations.")
        elif not supported <= eligible:
            messages.append(
                "Some supporting Citations are not both identity-verified and source-grounded."
            )
        if not self.evidence_check.ready:
            messages.append("The Related Work evidence check is incomplete.")
        if not audit.complete or audit.completed_at is None:
            messages.append("The literature search audit is incomplete.")
        if not audit.related_work_queries or not audit.counter_evidence_queries:
            messages.append("The audit does not contain both search query sets.")
        if not audit.providers:
            messages.append("The audit does not record a scholarly provider.")

        expected_related = min(5, audit.related_work_candidate_count)
        if (
            expected_related == 0
            or audit.related_work_analyzed_count != expected_related
            or len(supported) != audit.related_work_analyzed_count
        ):
            messages.append(
                "Related Work analysis does not cover the selected source portfolio."
            )
        expected_counter = min(5, audit.counter_evidence_candidate_count)
        if (
            expected_counter == 0
            or audit.counter_evidence_analyzed_count == 0
            or audit.counter_evidence_analyzed_count > expected_counter
            or len(results) != audit.counter_evidence_analyzed_count
        ):
            messages.append(
                "Counter-evidence analysis does not cover the selected source portfolio."
            )

        if audit.counter_evidence_outcome not in {
            CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE,
            CounterEvidenceOutcome.GAP_NARROWED,
        }:
            messages.append("The counter-evidence outcome does not support this Gap.")
        if len(set(result_keys)) != len(result_keys):
            messages.append("Counter-evidence result identifiers are not unique.")
        if any(
            result.verification_status is not VerificationStatus.VERIFIED
            for result in results
        ):
            messages.append("Every counter-evidence source identity must be verified.")
        if any(
            result.content_basis is CounterEvidenceContentBasis.METADATA_ONLY
            or result.grounding_status is not GroundingStatus.GROUNDED
            or not (result.evidence_passage or "").strip()
            or not (result.evidence_location or "").strip()
            for result in results
        ):
            messages.append(
                "Every counter-evidence assessment must be grounded in source content."
            )
        if any(
            result.relevance_status is not CounterEvidenceRelevance.RELEVANT
            for result in results
        ):
            messages.append(
                "Every counter-evidence source must be directly relevant to the Gap claims."
            )
        if any(
            result.support_status is not CounterEvidenceSupport.SUPPORTED
            for result in results
        ):
            messages.append(
                "Every counter-evidence rationale must be semantically supported by "
                "the retrieved source content."
            )

        if not claims or len(set(claim_ids)) != len(claim_ids):
            messages.append(
                "Atomic Gap claims are missing or have duplicate identifiers."
            )
        allowed_claim_outcomes = {
            CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE,
            CounterEvidenceOutcome.GAP_NARROWED,
        }
        if any(
            not claim.supporting_citation_keys
            or not set(claim.supporting_citation_keys) <= eligible
            or not claim.supporting_evidence
            or {
                evidence.citation_key for evidence in claim.supporting_evidence
            }
            != set(claim.supporting_citation_keys)
            or claim.outcome not in allowed_claim_outcomes
            for claim in claims
        ):
            messages.append(
                "Every atomic Gap claim must have eligible passage-level provenance "
                "and a supporting audit outcome."
            )
        claim_outcomes = {claim.outcome for claim in claims}
        expected_outcome = (
            CounterEvidenceOutcome.GAP_NOT_SUPPORTED
            if CounterEvidenceOutcome.GAP_NOT_SUPPORTED in claim_outcomes
            else (
                CounterEvidenceOutcome.GAP_NARROWED
                if CounterEvidenceOutcome.GAP_NARROWED in claim_outcomes
                else (
                    CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE
                    if claim_outcomes
                    == {CounterEvidenceOutcome.NO_DIRECT_COUNTER_EVIDENCE}
                    else CounterEvidenceOutcome.INCONCLUSIVE
                )
            )
        )
        if audit.counter_evidence_outcome is not expected_outcome:
            messages.append(
                "The overall counter-evidence outcome is inconsistent with the atomic claims."
            )
        mapped_support = {
            key for claim in claims for key in claim.supporting_citation_keys
        }
        if mapped_support != supported:
            messages.append(
                "Supporting Citations are not mapped exactly to the atomic Gap claims."
            )
        counter_key_set = set(result_keys)
        if any(
            set(claim.counter_evidence_result_keys) != counter_key_set
            for claim in claims
        ):
            messages.append(
                "Every atomic Gap claim must be checked against every selected counter-evidence source."
            )
        return messages

    def is_evidence_ready(self) -> bool:
        return not self.evidence_readiness_messages()

    @model_validator(mode="after")
    def downgrade_stale_candidate_status(self) -> "GapCardBody":
        self.search_audit.readiness_messages = self.evidence_readiness_messages()
        if self.status is GapStatus.CANDIDATE and self.search_audit.readiness_messages:
            self.status = GapStatus.INSUFFICIENT_EVIDENCE
        return self

    def is_confirmable(self) -> bool:
        # Evidence readiness is advisory. An Account may confirm a Gap Candidate
        # after reviewing the warnings, including a negative or inconclusive audit.
        return bool(self.statement.strip())


class ResearchGenerateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    # Optional compatibility override for research ideas without named tools.
    # Tool-oriented Related Work derives its Citation target from discovered tools.
    max_results: int | None = Field(default=None, ge=1)


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
