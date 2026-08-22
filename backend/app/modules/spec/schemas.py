"""Contracts for contribution-direction generation."""

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
