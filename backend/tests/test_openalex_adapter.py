"""OpenAlex adapter error handling tests."""

import httpx
import pytest

from app.modules.research.adapters.openalex import OpenAlexSource
from app.modules.research.ports import ScholarlyProviderError


@pytest.mark.asyncio
async def test_openalex_requires_api_key_before_search() -> None:
    source = OpenAlexSource()

    with pytest.raises(ScholarlyProviderError, match="OPENALEX_API_KEY"):
        await source.search(query="claim verification")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (403, "API_KEY is valid"),
        (429, "daily usage budget"),
        (503, "temporarily unavailable"),
    ],
)
async def test_openalex_converts_http_status_to_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    message: str,
) -> None:
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, str | int],
    ) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(status_code, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    source = OpenAlexSource(api_key="test-key")

    with pytest.raises(ScholarlyProviderError, match=message):
        await source.search(query="claim verification")
