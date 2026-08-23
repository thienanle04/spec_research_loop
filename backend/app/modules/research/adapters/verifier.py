"""Citation verifier backed by the configured scholarly provider."""

from difflib import SequenceMatcher

from app.modules.research.normalization import normalize_doi
from app.modules.research.ports import (
    ScholarlyRecord,
    ScholarlySourcePort,
    VerificationResult,
)
from app.modules.research.schemas import VerificationStatus


class ProviderCitationVerifier:
    def __init__(self, source: ScholarlySourcePort) -> None:
        self._source = source

    async def verify(self, *, citation: ScholarlyRecord) -> VerificationResult:
        identifier = citation.doi or citation.provider_source_id or citation.url
        if not identifier:
            return VerificationResult(
                status=VerificationStatus.WARNING,
                messages=["Citation has no provider-resolvable identifier"],
            )
        resolved = await self._source.get_source(identifier=identifier)
        if resolved is None:
            return VerificationResult(
                status=VerificationStatus.REJECTED,
                messages=["The scholarly provider could not resolve this Citation"],
            )
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
