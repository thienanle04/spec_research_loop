"""Deterministic scholarly source and verifier used by automated tests."""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from app.modules.research.normalization import normalize_doi
from app.modules.research.ports import (
    DocumentText,
    ScholarlyRecord,
    SourcePreferences,
    VerificationResult,
)
from app.modules.research.schemas import VerificationStatus

DEFAULT_RECORDS = (
    ScholarlyRecord(
        title="Large Language Models as Optimizers",
        authors=["Chengrun Yang", "Xuezhi Wang", "Yifeng Lu"],
        year=2023,
        venue="arXiv",
        doi="10.48550/arxiv.2309.03409",
        url="https://arxiv.org/abs/2309.03409",
        provider="fixture",
        provider_source_id="opro-2023",
        abstract=(
            "An optimizer model proposes prompts and receives task scores as "
            "feedback over multiple optimization rounds."
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={
            "fixture": True,
            "language": "en",
            "type": "article",
            "is_peer_reviewed": False,
        },
    ),
    ScholarlyRecord(
        title="Self-Refine: Iterative Refinement with Self-Feedback",
        authors=["Aman Madaan", "Nikunj Tandon", "Prakhar Gupta"],
        year=2023,
        venue="NeurIPS",
        doi="10.48550/arxiv.2303.17651",
        url="https://arxiv.org/abs/2303.17651",
        provider="fixture",
        provider_source_id="self-refine-2023",
        abstract=(
            "A language model generates feedback on its output and iteratively "
            "refines that output without supervised training data."
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={
            "fixture": True,
            "language": "en",
            "type": "article",
            "is_peer_reviewed": True,
        },
    ),
)


class FakeDocumentTextSource:
    """Keep fake-provider development and tests deterministic and offline."""

    async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText | None:
        if not record.abstract:
            return None
        return DocumentText(
            text=record.abstract.strip(),
            source_url=record.url,
            source_kind="abstract",
            original_content_type="text/plain",
        )


class FakeScholarlySourcePort:
    """In-memory provider with optional deterministic failure injection."""

    def __init__(
        self,
        records: Iterable[ScholarlyRecord] = DEFAULT_RECORDS,
        *,
        error: Exception | None = None,
    ) -> None:
        self.records = list(records)
        self.error = error
        self.search_calls: list[tuple[str, SourcePreferences | None, int]] = []
        self.get_calls: list[str] = []

    @classmethod
    def from_json(cls, path: str | Path) -> "FakeScholarlySourcePort":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        records = []
        for item in raw:
            if isinstance(item.get("retrieved_at"), str):
                item["retrieved_at"] = datetime.fromisoformat(item["retrieved_at"])
            records.append(ScholarlyRecord(**item))
        return cls(records)

    async def search(
        self,
        *,
        query: str,
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        self.search_calls.append((query, preferences, limit))
        if self.error is not None:
            raise self.error
        terms = {term.casefold() for term in query.split() if term.strip()}
        ranked = sorted(
            self.records,
            key=lambda row: (
                _preference_score(row, preferences),
                sum(
                    term in f"{row.title} {row.abstract or ''}".casefold()
                    for term in terms
                ),
            ),
            reverse=True,
        )
        return ranked[:limit]

    async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
        self.get_calls.append(identifier)
        if self.error is not None:
            raise self.error
        normalized = normalize_doi(identifier)
        folded = identifier.casefold()
        for row in self.records:
            if normalized and normalize_doi(row.doi) == normalized:
                return row
            if row.provider_source_id and row.provider_source_id.casefold() == folded:
                return row
            if row.url and row.url.casefold() == folded:
                return row
        return None


class FakeCitationVerifier:
    """Rule-based fake that remains useful when no live provider is configured."""

    async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
        if not citation.title.strip():
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                messages=["Citation title is missing"],
            )
        if citation.doi or citation.provider_source_id:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                messages=["Stable source identifier is present"],
                record=citation,
            )
        return VerificationResult(
            status=VerificationStatus.WARNING,
            messages=["Citation has no DOI or provider source id"],
            record=citation,
        )


def _preference_score(
    row: ScholarlyRecord, preferences: SourcePreferences | None
) -> int:
    if preferences is None:
        return 0
    source_type = str(row.metadata.get("type") or "").casefold()
    venue_type = str(row.metadata.get("source_type") or "").casefold()
    score = 0
    if preferences.peer_reviewed_papers and (
        row.metadata.get("is_peer_reviewed") is True or venue_type == "journal"
    ):
        score += 1
    if preferences.official_proceedings and venue_type == "conference":
        score += 1
    if preferences.author_materials and source_type in {"preprint", "report"}:
        score += 1
    if preferences.sourced_surveys and source_type == "review":
        score += 1
    return score
