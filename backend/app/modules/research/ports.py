"""Module-local ports for scholarly retrieval and Citation verification."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.modules.research.schemas import VerificationStatus


class ScholarlyProviderError(RuntimeError):
    """Safe, provider-neutral error that can be shown to an API client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class ScholarlyRecord:
    """Provider-neutral scholarly source returned by a search adapter."""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    provider: str | None = None
    provider_source_id: str | None = None
    abstract: str | None = None
    retrieved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentText:
    """Normalized scholarly text ready for S3 persistence and passage retrieval."""

    text: str
    source_url: str | None = None
    source_kind: str = "abstract"
    original_content_type: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VerificationResult:
    status: VerificationStatus
    messages: list[str] = field(default_factory=list)
    record: ScholarlyRecord | None = None


@dataclass(slots=True)
class SourcePreferences:
    """Provider-neutral ranking preferences confirmed in Research Inputs."""

    peer_reviewed_papers: bool = True
    official_proceedings: bool = True
    author_materials: bool = True
    sourced_surveys: bool = True


@runtime_checkable
class ScholarlySourcePort(Protocol):
    async def search(
        self,
        *,
        query: str,
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        """Search a scholarly provider without leaking its response shape."""
        ...

    async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
        """Resolve a DOI, provider id, or URL to one source record."""
        ...


@runtime_checkable
class MultiQueryScholarlySourcePort(Protocol):
    async def search_many(
        self,
        *,
        queries: list[str],
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        """Search several logical queries using a provider-efficient request plan."""
        ...


@runtime_checkable
class BatchScholarlySourcePort(Protocol):
    async def get_sources(
        self,
        *,
        identifiers: list[str],
    ) -> list[ScholarlyRecord | None]:
        """Resolve multiple identifiers while preserving the input order."""
        ...


@runtime_checkable
class CitationGraphPort(Protocol):
    async def expand_related(
        self,
        *,
        seeds: list[ScholarlyRecord],
        limit: int = 20,
    ) -> list[ScholarlyRecord]:
        """Expand seed papers through a provider's related-paper graph."""
        ...


@runtime_checkable
class DocumentTextPort(Protocol):
    async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText | None:
        """Fetch and normalize the best available text for one scholarly record."""
        ...


@runtime_checkable
class CitationVerifier(Protocol):
    async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
        """Verify Citation identity and metadata against a source."""
        ...


@runtime_checkable
class BatchCitationVerifier(Protocol):
    async def verify_many(
        self,
        *,
        citations: list[ScholarlyRecord],
    ) -> list[VerificationResult]:
        """Verify multiple Citations in one provider operation when supported."""
        ...
