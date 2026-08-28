"""Semantic Scholar Academic Graph adapter."""

import asyncio
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.modules.research.normalization import normalize_doi
from app.modules.research.ports import (
    ScholarlyProviderError,
    ScholarlyRecord,
    SourcePreferences,
)

_PAPER_FIELDS = (
    "externalIds,url,title,abstract,venue,year,authors,publicationTypes,"
    "openAccessPdf"
)

_MIN_REQUEST_INTERVAL_SECONDS = 1.25
_MAX_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_BACKOFF_SECONDS = (5.0, 15.0, 30.0)
_MAX_SERVER_ERROR_RETRIES = 2
_SERVER_ERROR_BACKOFF_SECONDS = (1.0, 3.0)
_RETRYABLE_SERVER_ERRORS = {500, 502, 503, 504}


class _SharedIntervalRateLimiter:
    """Gate request starts across instances without binding to one event loop."""

    def __init__(
        self,
        *,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._reservation_lock = threading.Lock()
        self._next_start = 0.0

    async def wait(self) -> None:
        # Re-check after sleeping instead of reserving all concurrent calls up front.
        # A later 429 can then extend the shared cooldown for already-waiting calls.
        while True:
            now = self._clock()
            with self._reservation_lock:
                delay = self._next_start - now
                if delay <= 0:
                    self._next_start = now + self._interval
                    return
            await self._sleeper(delay)

    def defer(self, delay_seconds: float) -> None:
        """Apply a provider-requested cooldown to every adapter instance."""
        with self._reservation_lock:
            self._next_start = max(
                self._next_start,
                self._clock() + max(delay_seconds, 0.0),
            )


# FastAPI creates provider adapters per request. Keeping this limiter at module scope
# makes the API-key quota cumulative across search, resolve, recommendations,
# and every SemanticScholarSource instance in this backend process.
_SEMANTIC_SCHOLAR_RATE_LIMITER = _SharedIntervalRateLimiter(
    interval_seconds=_MIN_REQUEST_INTERVAL_SECONDS
)


class SemanticScholarSource:
    base_url = "https://api.semanticscholar.org/graph/v1"
    recommendations_base_url = "https://api.semanticscholar.org/recommendations/v1"

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        api_key: str | None = None,
        public_fallback_enabled: bool = True,
        rate_limiter: _SharedIntervalRateLimiter | None = None,
        retry_sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._timeout = timeout_seconds
        self._api_key = api_key
        self._public_fallback_enabled = public_fallback_enabled
        self._rate_limiter = rate_limiter or _SEMANTIC_SCHOLAR_RATE_LIMITER
        self._retry_sleeper = retry_sleeper

    async def search(
        self,
        *,
        query: str,
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        payload = await self._get_json(
            "/paper/search/bulk",
            params={
                "query": _bulk_query(query),
                "fields": _PAPER_FIELDS,
            },
        )
        records = [_to_record(item, discovery="keyword") for item in payload.get("data", [])]
        records.sort(
            key=lambda row: (
                _query_match_score(row, query),
                _preference_score(row, preferences),
            ),
            reverse=True,
        )
        return records[: max(limit, 0)]

    async def search_many(
        self,
        *,
        queries: list[str],
        preferences: SourcePreferences | None = None,
        limit: int = 10,
    ) -> list[ScholarlyRecord]:
        """Coalesce logical queries into one Semantic Scholar bulk request."""
        normalized = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
        if not normalized:
            return []
        provider_queries = _provider_query_plan(normalized)
        records = await self.search(
            query=_combined_query(provider_queries),
            preferences=preferences,
            limit=limit,
        )
        for record in records:
            matches = [
                query
                for query in normalized
                if _query_match_score(record, query) > (0, 0)
            ]
            # An unmatched result can still be returned by Semantic Scholar's broad
            # bulk search, but it must not receive synthetic coverage for every query.
            # Downstream relevance gates use this field as evidence of discovery.
            record.metadata["discovery_queries"] = matches
            record.metadata["provider_query_plan"] = provider_queries
        records.sort(
            key=lambda row: (
                max(_query_match_score(row, query) for query in normalized),
                _preference_score(row, preferences),
            ),
            reverse=True,
        )
        return records

    async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
        paper_id = _paper_identifier(identifier)
        payload = await self._get_json(
            f"/paper/{paper_id}",
            params={"fields": _PAPER_FIELDS},
            allow_not_found=True,
        )
        return _to_record(payload, discovery="resolved") if payload else None

    async def get_sources(
        self,
        *,
        identifiers: list[str],
    ) -> list[ScholarlyRecord | None]:
        """Resolve paper metadata in API-supported batches of at most 500 IDs."""
        records: list[ScholarlyRecord | None] = []
        paper_ids = [_paper_identifier(identifier) for identifier in identifiers]
        for start in range(0, len(paper_ids), 500):
            batch = paper_ids[start : start + 500]
            payload = await self._post_json(
                "/paper/batch",
                params={"fields": _PAPER_FIELDS},
                json={"ids": batch},
            )
            items = payload if isinstance(payload, list) else []
            records.extend(
                _to_record(item, discovery="resolved")
                if isinstance(item, dict)
                else None
                for item in items[: len(batch)]
            )
            records.extend([None] * (len(batch) - len(items)))
        return records

    async def expand_related(
        self,
        *,
        seeds: list[ScholarlyRecord],
        limit: int = 20,
    ) -> list[ScholarlyRecord]:
        seed_ids = [
            seed.provider_source_id
            for seed in seeds
            if seed.provider == "semantic_scholar" and seed.provider_source_id
        ]
        if not seed_ids:
            return []
        # One multi-seed recommendation call replaces two citation-edge calls per
        # seed. This is both more quota-efficient and naturally reranks the graph
        # expansion around the complete seed set.
        payload = await self._request_json(
            "POST",
            "/papers",
            params={"limit": max(limit, 0), "fields": _PAPER_FIELDS},
            json={"positivePaperIds": seed_ids, "negativePaperIds": []},
            base_url=self.recommendations_base_url,
        )
        items = payload.get("recommendedPapers", []) if isinstance(payload, dict) else []
        records: list[ScholarlyRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            record = _to_record(item, discovery="recommendation")
            record.metadata["citation_graph_seeds"] = seed_ids
            records.append(record)
        return records[:limit]

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str | int],
        allow_not_found: bool = False,
    ) -> dict[str, Any]:
        value = await self._request_json(
            "GET",
            path,
            params=params,
            allow_not_found=allow_not_found,
        )
        return value if isinstance(value, dict) else {}

    async def _post_json(
        self,
        path: str,
        *,
        params: dict[str, str | int],
        json: dict[str, Any],
    ) -> Any:
        return await self._request_json("POST", path, params=params, json=json)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int],
        json: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        base_url: str | None = None,
    ) -> Any:
        use_public_pool = not bool(self._api_key)
        response: httpx.Response | None = None
        rate_limit_attempt = 0
        server_error_attempt = 0
        while True:
            headers = (
                {} if use_public_pool else {"x-api-key": self._api_key or ""}
            )
            try:
                await self._rate_limiter.wait()
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.request(
                        method,
                        f"{base_url or self.base_url}{path}",
                        params=params,
                        headers=headers,
                        json=json,
                    )
            except httpx.TimeoutException as exc:
                raise ScholarlyProviderError(
                    "Semantic Scholar request timed out."
                ) from exc
            except httpx.RequestError as exc:
                raise ScholarlyProviderError(
                    "Could not connect to Semantic Scholar."
                ) from exc
            if response.status_code in _RETRYABLE_SERVER_ERRORS:
                if server_error_attempt == _MAX_SERVER_ERROR_RETRIES:
                    break
                delay = _SERVER_ERROR_BACKOFF_SECONDS[
                    min(
                        server_error_attempt,
                        len(_SERVER_ERROR_BACKOFF_SECONDS) - 1,
                    )
                ]
                defer = getattr(self._rate_limiter, "defer", None)
                if callable(defer):
                    defer(delay)
                await self._retry_sleeper(delay)
                server_error_attempt += 1
                continue
            if response.status_code != 429:
                break
            if (
                self._api_key
                and not use_public_pool
                and self._public_fallback_enabled
            ):
                # A key can be temporarily throttled while Semantic Scholar's
                # unauthenticated shared pool is still available. Switching pools
                # keeps this provider usable without falling back to OpenAlex.
                use_public_pool = True
                continue
            if rate_limit_attempt == _MAX_RATE_LIMIT_RETRIES:
                break
            delay = _retry_delay(response, rate_limit_attempt)
            defer = getattr(self._rate_limiter, "defer", None)
            if callable(defer):
                defer(delay)
            else:
                # Compatibility for custom/test limiters implementing only wait().
                await self._retry_sleeper(delay)
            rate_limit_attempt += 1

        if response is None:  # pragma: no cover - loop always performs one request
            raise ScholarlyProviderError("Semantic Scholar returned no response.")
        if allow_not_found and response.status_code == 404:
            return {}
        if response.is_error:
            raise ScholarlyProviderError(
                f"Semantic Scholar request failed (HTTP {response.status_code}).",
                status_code=response.status_code,
            )
        return response.json()


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After")
    try:
        requested = float(header) if header is not None else 0.0
    except ValueError:
        requested = 0.0
    fallback = _RATE_LIMIT_BACKOFF_SECONDS[
        min(attempt, len(_RATE_LIMIT_BACKOFF_SECONDS) - 1)
    ]
    # Semantic Scholar can omit Retry-After on a burst 429. A longer shared
    # cooldown is safer than immediately spending the remaining retry attempts.
    return max(requested, fallback) + 0.25


def _combined_query(queries: list[str]) -> str:
    if len(queries) == 1:
        return queries[0]
    # Semantic Scholar's bulk-search parser accepts `term|term` but currently
    # returns HTTP 500 for parenthesized groups or whitespace around `|`.
    return "|".join(queries)


def _provider_query_plan(queries: list[str]) -> list[str]:
    """Add short recall anchors without spending additional HTTP requests."""
    planned = list(queries)
    seen = {query.casefold() for query in planned}
    for query in queries:
        anchor = _recall_anchor(query)
        if anchor and anchor.casefold() not in seen:
            planned.append(anchor)
            seen.add(anchor.casefold())
    return planned


def _recall_anchor(query: str) -> str:
    ignored = {
        "and",
        "or",
        "not",
        "benchmark",
        "study",
        "survey",
        "review",
        "evaluation",
        "comparison",
        "impact",
        "limitation",
        "challenge",
    }
    words = [
        word
        for word in re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
        if word not in ignored
    ]
    # Three domain-bearing terms retain intent while avoiding Semantic Scholar's
    # implicit all-keyword constraint on long bulk-search queries.
    return " ".join(words[:3]) if len(words) >= 2 else ""


def _bulk_query(value: str) -> str:
    """Translate provider-neutral Boolean words to bulk-search operators."""
    segments = re.split(r'("(?:[^"\\]|\\.)*")', value)
    for index in range(0, len(segments), 2):
        segment = re.sub(r"\bAND\b", "+", segments[index], flags=re.IGNORECASE)
        segment = re.sub(r"\bOR\b", "|", segment, flags=re.IGNORECASE)
        segment = re.sub(r"\bNOT\s+", "-", segment, flags=re.IGNORECASE)
        segment = segment.replace("(", " ").replace(")", " ")
        segment = re.sub(r"\s*([+|])\s*", r"\1", segment)
        segments[index] = segment
    return re.sub(r"\s+", " ", "".join(segments)).strip()


def _paper_identifier(value: str) -> str:
    doi = normalize_doi(value)
    if doi and doi.startswith("10.") and "/" in doi:
        return f"DOI:{doi}"
    folded = value.strip()
    if "arxiv.org/abs/" in folded.casefold():
        return f"ARXIV:{folded.rstrip('/').rsplit('/', 1)[-1]}"
    return folded


def _to_record(
    item: dict,
    *,
    discovery: str,
    seed_id: str | None = None,
) -> ScholarlyRecord:
    external_ids = item.get("externalIds") or {}
    open_pdf = item.get("openAccessPdf") or {}
    metadata = dict(item)
    metadata.update(
        {
            "discovery_types": [discovery],
            "provider_ids": {"semantic_scholar": item.get("paperId")},
            "full_text_url": open_pdf.get("url"),
        }
    )
    if seed_id:
        metadata["citation_graph_seeds"] = [seed_id]
    return ScholarlyRecord(
        title=item.get("title") or "Untitled source",
        authors=[author.get("name", "Unknown") for author in item.get("authors", [])],
        year=item.get("year"),
        venue=item.get("venue"),
        doi=normalize_doi(external_ids.get("DOI")),
        url=item.get("url") or open_pdf.get("url"),
        provider="semantic_scholar",
        provider_source_id=item.get("paperId"),
        abstract=item.get("abstract"),
        retrieved_at=datetime.now(UTC),
        metadata=metadata,
    )


def _preference_score(
    record: ScholarlyRecord,
    preferences: SourcePreferences | None,
) -> int:
    if preferences is None:
        return 0
    types = {
        str(item).casefold() for item in record.metadata.get("publicationTypes") or []
    }
    score = 0
    if preferences.peer_reviewed_papers and types & {"journalarticle", "conference"}:
        score += 1
    if preferences.official_proceedings and "conference" in types:
        score += 1
    if preferences.author_materials and "review" not in types:
        score += 1
    if preferences.sourced_surveys and "review" in types:
        score += 1
    return score


def _query_match_score(record: ScholarlyRecord, query: str) -> tuple[int, int]:
    terms = {
        term.casefold()
        for term in re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if term.casefold() not in {"and", "or", "not"}
    }
    title = record.title.casefold()
    abstract = (record.abstract or "").casefold()
    return (
        sum(term in title for term in terms),
        sum(term in abstract for term in terms),
    )
