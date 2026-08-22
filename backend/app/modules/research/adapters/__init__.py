"""Scholarly source and verifier adapters for the research module."""

from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import (
    FakeCitationVerifier,
    FakeScholarlySourcePort,
)
from app.modules.research.adapters.openalex import OpenAlexSource
from app.modules.research.adapters.verifier import ProviderCitationVerifier

__all__ = [
    "FakeCitationVerifier",
    "FakeLlmPort",
    "FakeScholarlySourcePort",
    "OpenAlexSource",
    "ProviderCitationVerifier",
]
