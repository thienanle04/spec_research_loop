"""OpenAlex implementation of the scholarly source port."""

from datetime import UTC, datetime

import httpx

from app.modules.research.normalization import normalize_doi
from app.modules.research.ports import (
    ScholarlyProviderError,
    ScholarlyRecord,
    SourcePreferences,
)


class OpenAlexSource:
    base_url = "https://api.openalex.org"

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        mailto: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._mailto = mailto
        self._api_key = api_key

    async def search(
        self,
        *,
        query: str,
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        params: dict[str, str | int] = {"search": query, "per_page": limit}
        params.update(self._authentication_params())
        response = await self._get(f"{self.base_url}/works", params=params)
        records = [_to_record(item) for item in response.json().get("results", [])]
        records.sort(
            key=lambda record: _preference_score(record, preferences), reverse=True
        )
        return records

    async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
        normalized_doi = normalize_doi(identifier)
        lookup = f"https://doi.org/{normalized_doi}" if normalized_doi else identifier
        params = self._authentication_params()
        response = await self._get(
            f"{self.base_url}/works/{lookup}", params=params, allow_not_found=True
        )
        if response.status_code == 404:
            return None
        return _to_record(response.json())

    def _authentication_params(self) -> dict[str, str]:
        if not self._api_key:
            raise ScholarlyProviderError(
                "OpenAlex API key is not configured. Add OPENALEX_API_KEY to "
                "backend/.env, then restart the backend."
            )
        params = {"api_key": self._api_key}
        if self._mailto:
            params["mailto"] = self._mailto
        return params

    async def _get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        allow_not_found: bool = False,
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ScholarlyProviderError("OpenAlex request timed out.") from exc
        except httpx.RequestError as exc:
            raise ScholarlyProviderError(
                "Could not connect to OpenAlex. Check the network connection."
            ) from exc
        if allow_not_found and response.status_code == 404:
            return response
        if response.is_error:
            raise ScholarlyProviderError(
                _http_error_message(response.status_code),
                status_code=response.status_code,
            )
        return response


def _http_error_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return (
            f"OpenAlex rejected the request (HTTP {status_code}). Check that "
            "OPENALEX_API_KEY is valid."
        )
    if status_code == 429:
        return (
            "OpenAlex rate limit or daily usage budget was exceeded (HTTP 429). "
            "Wait for the limit to reset or check OpenAlex usage."
        )
    if status_code >= 500:
        return f"OpenAlex is temporarily unavailable (HTTP {status_code})."
    return f"OpenAlex search request failed (HTTP {status_code})."


def _to_record(item: dict) -> ScholarlyRecord:
    location = item.get("primary_location") or {}
    source = location.get("source") or {}
    return ScholarlyRecord(
        title=item.get("display_name") or "Untitled source",
        authors=[
            authorship.get("author", {}).get("display_name", "Unknown")
            for authorship in item.get("authorships", [])
        ],
        year=item.get("publication_year"),
        venue=source.get("display_name"),
        doi=normalize_doi(item.get("doi")),
        url=location.get("landing_page_url") or item.get("doi"),
        provider="openalex",
        provider_source_id=item.get("id"),
        abstract=_abstract(item.get("abstract_inverted_index")),
        retrieved_at=datetime.now(UTC),
        metadata=item,
    )


def _abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positions = sorted(
        (position, word) for word, indexes in inverted.items() for position in indexes
    )
    return " ".join(word for _, word in positions)


def _preference_score(
    record: ScholarlyRecord, preferences: SourcePreferences | None
) -> int:
    if preferences is None:
        return 0
    source_type = str(
        ((record.metadata.get("primary_location") or {}).get("source") or {}).get(
            "type"
        )
        or ""
    ).casefold()
    work_type = str(record.metadata.get("type") or "").casefold()
    score = 0
    if preferences.peer_reviewed_papers and source_type == "journal":
        score += 1
    if preferences.official_proceedings and source_type == "conference":
        score += 1
    if preferences.author_materials and work_type in {"preprint", "report"}:
        score += 1
    if preferences.sourced_surveys and work_type == "review":
        score += 1
    return score
