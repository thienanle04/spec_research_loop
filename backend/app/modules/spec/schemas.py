"""Contracts for spec schemas."""

from enum import StrEnum
from pydantic import BaseModel, Field

# --- MOCK DATA SCHEMA (from feat/spec) ---
class SpecConstructionContext(BaseModel):
    problem_statement: str
    research_questions: list[str]
    research_gap: str
    related_works_summary: str
    hardware_constraint: str = "RTX 3090, 24GB VRAM"

# --- CONTRIBUTION ---
class ContributionOption(BaseModel):
    id: str = Field(description="Mã option, VD: A, B, C, D, OTHER")
    title: str = Field(description="Tên hướng đóng góp")
    description: str = Field(description="Mô tả chi tiết cách tiếp cận")

class GenerateContributionResponse(BaseModel):
    options: list[ContributionOption]

# Dùng chung cho các bước xác nhận, payload lưu vào narrative JSONB
class ConfirmRequest(BaseModel):
    session_id: str
    confirmed_data: dict

# --- CLAIMS & EVIDENCE ---
class ClaimEvidenceCard(BaseModel):
    id: str
    claim: str
    baseline: str
    metric: str
    evidence: str
    rejection_condition: str

class GenerateClaimsResponse(BaseModel):
    cards: list[ClaimEvidenceCard]

# --- EXPERIMENT ---
class ExperimentPlan(BaseModel):
    baselines: list[str]
    metrics: list[str]
    evaluation_protocol: str
    ablation_study: list[str]
    generalization: list[str]

class GenerateExperimentResponse(BaseModel):
    plan: ExperimentPlan

# --- FEASIBILITY ---
class FeasibilityReport(BaseModel):
    estimated_vram: str
    estimated_time: str
    is_feasible: bool
    suggestions: list[str]


# --- REAL SCHEMA (from feat/research) ---
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
