"""Semantic Scholar adapter quota and endpoint coverage tests."""

from typing import Any, ClassVar, Self

import httpx
import pytest

from app.modules.research.adapters.semantic_scholar import (
    SemanticScholarSource,
    _bulk_query,
    _query_match_score,
    _SharedIntervalRateLimiter,
)
from app.modules.research.adapters.verifier import ProviderCitationVerifier
from app.modules.research.ports import ScholarlyProviderError, ScholarlyRecord
from app.modules.research.schemas import VerificationStatus


@pytest.mark.asyncio
async def test_shared_interval_limiter_spaces_request_reservations() -> None:
    current = [100.0]
    delays: list[float] = []

    async def advance(delay: float) -> None:
        delays.append(delay)
        current[0] += delay

    limiter = _SharedIntervalRateLimiter(
        interval_seconds=1.0,
        clock=lambda: current[0],
        sleeper=advance,
    )

    await limiter.wait()
    await limiter.wait()
    await limiter.wait()

    assert delays == [1.0, 1.0]


@pytest.mark.asyncio
async def test_shared_interval_limiter_applies_cooldown_to_waiting_requests() -> None:
    current = [100.0]
    delays: list[float] = []

    async def advance(delay: float) -> None:
        delays.append(delay)
        current[0] += delay

    limiter = _SharedIntervalRateLimiter(
        interval_seconds=1.0,
        clock=lambda: current[0],
        sleeper=advance,
    )

    await limiter.wait()
    limiter.defer(5.0)
    await limiter.wait()

    assert delays == [5.0]


@pytest.mark.asyncio
async def test_rate_limit_response_is_retried_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def wait(self) -> None:
            self.calls += 1

    class FakeAsyncClient:
        calls: ClassVar[int] = 0

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(self, method: str, url: str, **_kwargs: Any) -> httpx.Response:
            type(self).calls += 1
            request = httpx.Request(method, url)
            if type(self).calls == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "1"},
                    request=request,
                )
            return httpx.Response(200, json={"data": []}, request=request)

    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    limiter = RecordingLimiter()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    source = SemanticScholarSource(
        rate_limiter=limiter,  # type: ignore[arg-type]
        retry_sleeper=record_delay,
    )

    assert await source.search(query="claim verification", limit=5) == []
    assert limiter.calls == 2
    assert delays == [5.25]


@pytest.mark.asyncio
async def test_transient_server_errors_are_retried_with_short_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def wait(self) -> None:
            self.calls += 1

    class FakeAsyncClient:
        calls: ClassVar[int] = 0

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(self, method: str, url: str, **_kwargs: Any) -> httpx.Response:
            type(self).calls += 1
            request = httpx.Request(method, url)
            if type(self).calls < 3:
                return httpx.Response(
                    500 if type(self).calls == 1 else 503,
                    request=request,
                )
            return httpx.Response(200, json={"data": []}, request=request)

    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    limiter = RecordingLimiter()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    source = SemanticScholarSource(
        rate_limiter=limiter,  # type: ignore[arg-type]
        retry_sleeper=record_delay,
    )

    assert await source.search(query="claim verification", limit=5) == []
    assert limiter.calls == 3
    assert delays == [1.0, 3.0]


@pytest.mark.asyncio
async def test_rate_limited_api_key_falls_back_to_public_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def wait(self) -> None:
            self.calls += 1

    class FakeAsyncClient:
        headers_seen: ClassVar[list[dict[str, str]]] = []

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            **kwargs: Any,
        ) -> httpx.Response:
            headers = kwargs["headers"]
            type(self).headers_seen.append(headers)
            request = httpx.Request(method, url)
            if headers:
                return httpx.Response(429, request=request)
            return httpx.Response(200, json={"data": []}, request=request)

    limiter = RecordingLimiter()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    source = SemanticScholarSource(
        api_key="rate-limited-key",
        rate_limiter=limiter,  # type: ignore[arg-type]
    )

    assert await source.search(query="claim verification", limit=5) == []
    assert limiter.calls == 2
    assert FakeAsyncClient.headers_seen == [
        {"x-api-key": "rate-limited-key"},
        {},
    ]


@pytest.mark.asyncio
async def test_every_semantic_scholar_endpoint_uses_one_shared_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def wait(self) -> None:
            self.calls += 1

    class FakeAsyncClient:
        calls: ClassVar[
            list[tuple[str, str, dict[str, str | int], dict[str, Any] | None]]
        ] = []

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            *,
            params: dict[str, str | int],
            headers: dict[str, str],
            json: dict[str, Any] | None,
        ) -> httpx.Response:
            del headers
            self.calls.append((method, url, params, json))
            request = httpx.Request(method, url)
            if url.endswith("/paper/search/bulk"):
                return httpx.Response(200, json={"data": []}, request=request)
            if url.endswith("/paper/batch"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "paperId": paper_id,
                            "title": "Rate-limited scholarly source",
                            "authors": [],
                        }
                        for paper_id in (json or {}).get("ids", [])
                    ],
                    request=request,
                )
            if url.endswith("/recommendations/v1/papers"):
                return httpx.Response(
                    200,
                    json={
                        "recommendedPapers": [
                            {
                                "paperId": "R1",
                                "title": "Recommended related paper",
                                "authors": [],
                            }
                        ]
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "paperId": "S1",
                    "title": "Rate-limited scholarly source",
                    "authors": [],
                },
                request=request,
            )

    limiter = RecordingLimiter()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    source = SemanticScholarSource(
        api_key="test-key",
        rate_limiter=limiter,  # type: ignore[arg-type]
    )

    await source.search(query="claim verification", limit=5)
    await source.get_source(identifier="S1")
    await source.get_sources(identifiers=["S1", "DOI:10.1000/example"])
    related = await source.expand_related(
        seeds=[
            ScholarlyRecord(
                title="Seed",
                provider="semantic_scholar",
                provider_source_id="S1",
            )
        ],
        limit=2,
    )

    # bulk search + single resolve + batch resolve + one multi-seed recommendation
    assert limiter.calls == 4
    assert FakeAsyncClient.calls[0][0:2] == (
        "GET",
        "https://api.semanticscholar.org/graph/v1/paper/search/bulk",
    )
    assert FakeAsyncClient.calls[0][2] == {
        "query": "claim verification",
        "fields": (
            "externalIds,url,title,abstract,venue,year,authors,publicationTypes,"
            "openAccessPdf"
        ),
    }
    assert FakeAsyncClient.calls[2][0:2] == (
        "POST",
        "https://api.semanticscholar.org/graph/v1/paper/batch",
    )
    assert FakeAsyncClient.calls[2][3] == {
        "ids": ["S1", "DOI:10.1000/example"]
    }
    assert FakeAsyncClient.calls[3][0:2] == (
        "POST",
        "https://api.semanticscholar.org/recommendations/v1/papers",
    )
    assert FakeAsyncClient.calls[3][3] == {
        "positivePaperIds": ["S1"],
        "negativePaperIds": [],
    }
    assert [record.provider_source_id for record in related] == ["R1"]
    assert related[0].metadata["citation_graph_seeds"] == ["S1"]


def test_bulk_query_translates_boolean_words_outside_phrases() -> None:
    assert _bulk_query(
        '"research and development" AND (survey OR review) NOT privacy'
    ) == '"research and development"+survey|review -privacy'


@pytest.mark.asyncio
async def test_search_many_gives_each_logical_query_an_independent_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.calls = 0

        async def wait(self) -> None:
            self.calls += 1

    class FakeAsyncClient:
        queries: ClassVar[list[str]] = []

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            **kwargs: Any,
        ) -> httpx.Response:
            type(self).queries.append(kwargs["params"]["query"])
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "paperId": "S1",
                            "title": "Claim verification and fact checking",
                            "authors": [],
                        },
                        {
                            "paperId": "S2",
                            "title": "Highway pavement distress detection",
                            "authors": [],
                        }
                    ]
                },
                request=httpx.Request(method, url),
            )

    limiter = RecordingLimiter()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    source = SemanticScholarSource(rate_limiter=limiter)  # type: ignore[arg-type]

    records = await source.search_many(
        queries=["claim verification", "fact checking"],
        limit=5,
    )

    assert limiter.calls == 2
    assert FakeAsyncClient.queries == ["claim verification", "fact checking"]
    assert records[0].metadata["discovery_queries"] == [
        "claim verification",
    ]
    assert records[1].metadata["discovery_queries"] == []
    assert records[2].metadata["discovery_queries"] == ["fact checking"]


def test_bulk_candidates_prioritize_query_terms_in_title() -> None:
    title_match = ScholarlyRecord(
        title="Claim verification methods",
        abstract="An evaluation study.",
    )
    abstract_match = ScholarlyRecord(
        title="An evaluation study",
        abstract="Methods for claim verification.",
    )

    assert _query_match_score(title_match, "claim verification") > _query_match_score(
        abstract_match,
        "claim verification",
    )


def test_query_match_uses_whole_tokens_instead_of_substrings() -> None:
    unrelated = ScholarlyRecord(
        title="Training systems for highway maintenance",
        abstract="A general engineering evaluation.",
    )

    assert _query_match_score(unrelated, "AI") == (0, 0)


@pytest.mark.asyncio
async def test_provider_verifier_uses_one_batch_lookup() -> None:
    class BatchSource:
        def __init__(self) -> None:
            self.identifiers: list[str] = []

        async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
            raise AssertionError(f"Unexpected individual lookup for {identifier}")

        async def get_sources(
            self,
            *,
            identifiers: list[str],
        ) -> list[ScholarlyRecord | None]:
            self.identifiers = identifiers
            return [
                ScholarlyRecord(
                    title="First paper",
                    provider_source_id="S1",
                ),
                ScholarlyRecord(
                    title="Second paper",
                    provider_source_id="S2",
                ),
            ]

    source = BatchSource()
    verifier = ProviderCitationVerifier(source)  # type: ignore[arg-type]
    results = await verifier.verify_many(
        citations=[
            ScholarlyRecord(title="First paper", provider_source_id="S1"),
            ScholarlyRecord(title="Second paper", provider_source_id="S2"),
        ]
    )

    assert source.identifiers == ["S1", "S2"]
    assert [result.status for result in results] == [
        VerificationStatus.VERIFIED,
        VerificationStatus.VERIFIED,
    ]


@pytest.mark.asyncio
async def test_provider_verifier_warns_when_batch_identity_check_is_throttled() -> None:
    class ThrottledBatchSource:
        async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
            raise AssertionError(f"Unexpected individual lookup for {identifier}")

        async def get_sources(
            self,
            *,
            identifiers: list[str],
        ) -> list[ScholarlyRecord | None]:
            del identifiers
            raise ScholarlyProviderError(
                "Semantic Scholar request failed (HTTP 429).",
                status_code=429,
            )

    verifier = ProviderCitationVerifier(ThrottledBatchSource())  # type: ignore[arg-type]
    results = await verifier.verify_many(
        citations=[
            ScholarlyRecord(
                title="Discovered paper",
                provider="semantic_scholar",
                provider_source_id="S1",
            ),
            ScholarlyRecord(title="Metadata without an identifier"),
        ]
    )

    assert [result.status for result in results] == [
        VerificationStatus.WARNING,
        VerificationStatus.WARNING,
    ]
    assert "could not be independently rechecked" in results[0].messages[0]


@pytest.mark.asyncio
async def test_provider_verifier_keeps_discovered_record_when_recheck_is_empty() -> None:
    class EmptyBatchSource:
        async def get_source(self, *, identifier: str) -> ScholarlyRecord | None:
            raise AssertionError(f"Unexpected individual lookup for {identifier}")

        async def get_sources(
            self,
            *,
            identifiers: list[str],
        ) -> list[ScholarlyRecord | None]:
            return [None for _ in identifiers]

    citation = ScholarlyRecord(
        title="Provider-discovered tool paper",
        provider="semantic_scholar",
        provider_source_id="S1",
    )
    verifier = ProviderCitationVerifier(EmptyBatchSource())  # type: ignore[arg-type]

    [result] = await verifier.verify_many(citations=[citation])

    assert result.status is VerificationStatus.WARNING
    assert result.record is citation
    assert "independent identifier lookup returned no record" in result.messages[0]


def test_semantic_scholar_instances_share_the_process_limiter() -> None:
    first = SemanticScholarSource(api_key="first")
    second = SemanticScholarSource(api_key="second")

    assert first._rate_limiter is second._rate_limiter
