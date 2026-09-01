"""Scholarly source, text-retrieval, and verifier adapters."""

from app.modules.research.adapters.composite import CompositeScholarlySource
from app.modules.research.adapters.document_text import HttpDocumentTextSource
from app.modules.research.adapters.fake_llm import FakeLlmPort
from app.modules.research.adapters.fake_source import (
    FakeCitationVerifier,
    FakeDocumentTextSource,
    FakeScholarlySourcePort,
)
from app.modules.research.adapters.openalex import OpenAlexSource
from app.modules.research.adapters.semantic_scholar import SemanticScholarSource
from app.modules.research.adapters.verifier import ProviderCitationVerifier

__all__ = [
    "CompositeScholarlySource",
    "FakeCitationVerifier",
    "FakeDocumentTextSource",
    "FakeLlmPort",
    "FakeScholarlySourcePort",
    "HttpDocumentTextSource",
    "OpenAlexSource",
    "ProviderCitationVerifier",
    "SemanticScholarSource",
]
