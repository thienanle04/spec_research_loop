"""Contracts for spec schemas."""

from enum import StrEnum
from pydantic import BaseModel, Field

class ContributionDirectionKind(StrEnum):
    PROPOSED = "proposed"
    COMBINE = "combine"
    OTHER = "other"

class ContributionDirection(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: ContributionDirectionKind = ContributionDirectionKind.PROPOSED

class ContributionDirectionsRequest(BaseModel):
    expected_version: int = Field(ge=1)

class ContributionDirectionsResponse(BaseModel):
    version: int
    directions: list[ContributionDirection]

# --- CLAIMS & EVIDENCE ---
class ClaimEvidenceCard(BaseModel):
    id: str
    claim: str
    baseline: str
    metric: str
    evidence: str
    rejection_condition: str

class GenerateClaimsRequest(BaseModel):
    expected_version: int = Field(ge=1)

class GenerateClaimsResponse(BaseModel):
    version: int
    cards: list[ClaimEvidenceCard]

# --- EXPERIMENT ---
class ExperimentPlan(BaseModel):
    baselines: list[str]
    metrics: list[str]
    evaluation_protocol: str
    ablation_study: list[str]
    generalization: list[str]

class GenerateExperimentRequest(BaseModel):
    expected_version: int = Field(ge=1)

class GenerateExperimentResponse(BaseModel):
    version: int
    plan: ExperimentPlan

# --- FEASIBILITY ---
class FeasibilityReport(BaseModel):
    estimated_vram: str
    estimated_time: str
    is_feasible: bool
    suggestions: list[str]

class CheckFeasibilityRequest(BaseModel):
    expected_version: int = Field(ge=1)
    # Optionally can pass the plan if it's being actively edited, 
    # or rely on the narrative in DB.
    plan: ExperimentPlan | None = None

class CheckFeasibilityResponse(BaseModel):
    version: int
    report: FeasibilityReport
