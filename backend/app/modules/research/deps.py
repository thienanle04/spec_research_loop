"""Research dependency bindings kept local to the module."""

from typing import Annotated

from fastapi import Depends

from app.adapters.llm import FitWebUiLlmPort
from app.core.config import get_settings
from app.modules.research.adapters import (
    FakeCitationVerifier,
    FakeLlmPort,
    FakeScholarlySourcePort,
    OpenAlexSource,
    ProviderCitationVerifier,
)
from app.modules.research.ports import CitationVerifier, ScholarlySourcePort
from app.ports.llm import LlmPort


def get_scholarly_source() -> ScholarlySourcePort:
    settings = get_settings()
    if settings.research_source_provider.casefold() == "openalex":
        return OpenAlexSource(
            timeout_seconds=settings.research_provider_timeout_seconds,
            mailto=settings.openalex_mailto,
            api_key=settings.openalex_api_key,
        )
    return FakeScholarlySourcePort()


def get_research_llm() -> LlmPort:
    settings = get_settings()
    provider = settings.research_llm_provider.casefold()
    if provider == "fake":
        return FakeLlmPort()
    if provider == "fit_webui":
        if not settings.fit_webui_api_key:
            raise RuntimeError(
                "FIT_WEBUI_API_KEY is required when RESEARCH_LLM_PROVIDER=fit_webui"
            )
        return FitWebUiLlmPort(
            api_key=settings.fit_webui_api_key,
            default_model=settings.research_llm_model,
            base_url=settings.fit_webui_base_url,
            timeout_seconds=settings.fit_webui_timeout_seconds,
            max_tokens=settings.fit_webui_max_tokens,
        )
    raise RuntimeError(f"Unsupported research LLM provider: {provider}")


def get_citation_verifier(
    source: Annotated[ScholarlySourcePort, Depends(get_scholarly_source)],
) -> CitationVerifier:
    if isinstance(source, FakeScholarlySourcePort):
        return FakeCitationVerifier()
    return ProviderCitationVerifier(source)
