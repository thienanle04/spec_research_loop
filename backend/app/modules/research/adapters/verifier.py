"""Citation verifier backed by the configured scholarly provider."""

from difflib import SequenceMatcher

from app.modules.research.normalization import normalize_doi
from app.modules.research.ports import (
    BatchScholarlySourcePort,
    ScholarlyProviderError,
    ScholarlyRecord,
    ScholarlySourcePort,
    VerificationResult,
)
from app.modules.research.schemas import VerificationStatus


class ProviderCitationVerifier:
    def __init__(self, source: ScholarlySourcePort) -> None:
        self._source = source

    async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
        identifier = _identifier(citation)
        if not identifier:
            return _missing_identifier_result()
        resolved = await self._source.get_source(identifier=identifier)
        return _compare(citation, resolved)

    async def verify_many(
        self,
        *,
        citations: list[ScholarlyRecord],
    ) -> list[VerificationResult]:
        if not isinstance(self._source, BatchScholarlySourcePort):
            return [await self.verify(citation=citation) for citation in citations]

        results: list[VerificationResult | None] = [None] * len(citations)
        resolvable: list[tuple[int, ScholarlyRecord, str]] = []
        for index, citation in enumerate(citations):
            identifier = _identifier(citation)
            if identifier:
                resolvable.append((index, citation, identifier))
            else:
                results[index] = _missing_identifier_result()

        try:
            resolved = await self._source.get_sources(
                identifiers=[item[2] for item in resolvable]
            )
        except ScholarlyProviderError as exc:
            # These records were just returned by the configured scholarly provider.
            # A second batch lookup improves confidence but must not invalidate a
            # successful search when that optional endpoint is transiently throttled.
            for index, citation, _ in resolvable:
                results[index] = _discovery_result(citation, reason=str(exc))
            return [result or _unresolved_result() for result in results]
        for (index, citation, _), record in zip(resolvable, resolved, strict=True):
            results[index] = _compare(citation, record)
        return [result or _unresolved_result() for result in results]


def _identifier(citation: ScholarlyRecord) -> str | None:
    return citation.doi or citation.provider_source_id or citation.url


def _missing_identifier_result() -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.WARNING,
        messages=["Citation has no provider-resolvable identifier"],
    )


def _unresolved_result() -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.REJECTED,
        messages=["The scholarly provider could not resolve this Citation"],
    )


def _discovery_result(
    citation: ScholarlyRecord,
    *,
    reason: str,
) -> VerificationResult:
    if citation.provider and _identifier(citation):
        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            messages=[
                (
                    "Citation identity is supported by the provider search response; "
                    f"the secondary batch lookup was unavailable: {reason}"
                )
            ],
            record=citation,
        )
    return VerificationResult(
        status=VerificationStatus.WARNING,
        messages=[
            (
                "Citation could not be rechecked because the secondary provider "
                f"lookup was unavailable: {reason}"
            )
        ],
        record=citation,
    )


def _compare(
    citation: ScholarlyRecord,
    resolved: ScholarlyRecord | None,
) -> VerificationResult:
    if resolved is None:
        return _unresolved_result()
    if citation.doi and normalize_doi(citation.doi) != normalize_doi(resolved.doi):
        return VerificationResult(
            status=VerificationStatus.REJECTED,
            messages=["Resolved DOI does not match the stored DOI"],
            record=resolved,
        )
    similarity = SequenceMatcher(
        None,
        citation.title.casefold(),
        resolved.title.casefold(),
    ).ratio()
    if similarity < 0.75:
        return VerificationResult(
            status=VerificationStatus.WARNING,
            messages=["Resolved title differs from the stored title"],
            record=resolved,
        )
    return VerificationResult(
        status=VerificationStatus.VERIFIED,
        messages=["Identifier and title match the scholarly provider"],
        record=resolved,
    )
