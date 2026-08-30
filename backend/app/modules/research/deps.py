"""Research dependency bindings kept local to the module."""

from typing import Annotated

from fastapi import Depends

from app.adapters.llm import (
    FitWebUiLlmPort,
    TracingLlm,
    configure_llm_trace_logger,
)
from app.adapters.storage import MemoryObjectStorage, get_object_storage
from app.core.config import get_settings
from app.modules.research.adapters import (
    CompositeScholarlySource,
    FakeCitationVerifier,
    FakeLlmPort,
    FakeScholarlySourcePort,
    HttpDocumentTextSource,
    OpenAlexSource,
    ProviderCitationVerifier,
    SemanticScholarSource,
)
from app.modules.research.ports import (
    CitationVerifier,
    DocumentTextPort,
    ScholarlySourcePort,
)
from app.ports.llm import LlmPort
from app.ports.storage import ObjectStoragePort

_memory_object_storage = MemoryObjectStorage()


def get_scholarly_source() -> ScholarlySourcePort:
    settings = get_settings()
    providers = [
        item.strip().casefold()
        for item in settings.research_source_provider.split(",")
        if item.strip()
    ]
    sources: list[ScholarlySourcePort] = []
    for provider in providers:
        if provider == "fake":
            sources.append(FakeScholarlySourcePort())
        elif provider == "openalex":
            sources.append(
                OpenAlexSource(
                    timeout_seconds=settings.research_provider_timeout_seconds,
                    mailto=settings.openalex_mailto,
                    api_key=settings.openalex_api_key,
                )
            )
        elif provider == "semantic_scholar":
            sources.append(
                SemanticScholarSource(
                    timeout_seconds=settings.research_provider_timeout_seconds,
                    api_key=settings.semantic_scholar_api_key,
                    public_fallback_enabled=(
                        settings.semantic_scholar_public_fallback_enabled
                    ),
                )
            )
        else:
            raise RuntimeError(f"Unsupported research source provider: {provider}")
    if not sources:
        return FakeScholarlySourcePort()
    return sources[0] if len(sources) == 1 else CompositeScholarlySource(sources)


def get_document_text_source() -> DocumentTextPort:
    settings = get_settings()
    return HttpDocumentTextSource(
        timeout_seconds=settings.research_text_timeout_seconds,
        max_bytes=settings.research_text_max_bytes,
    )


def get_research_object_storage() -> ObjectStoragePort | None:
    provider = get_settings().research_text_storage.casefold()
    if provider == "disabled":
        return None
    if provider == "memory":
        return _memory_object_storage
    if provider == "s3":
        return get_object_storage()
    raise RuntimeError(f"Unsupported research text storage: {provider}")


def get_research_llm() -> LlmPort:
    settings = get_settings()
    provider = settings.research_llm_provider.casefold()
    if provider == "fake":
        llm: LlmPort = FakeLlmPort()
    elif provider == "fit_webui":
        if not settings.fit_webui_api_key:
            raise RuntimeError(
                "FIT_WEBUI_API_KEY is required when RESEARCH_LLM_PROVIDER=fit_webui"
            )
        llm = FitWebUiLlmPort(
            api_key=settings.fit_webui_api_key,
            default_model=settings.research_llm_model,
            base_url=settings.fit_webui_base_url,
            timeout_seconds=settings.fit_webui_timeout_seconds,
            max_tokens=settings.fit_webui_max_tokens,
        )
    else:
        raise RuntimeError(f"Unsupported research LLM provider: {provider}")

    if settings.llm_trace:
        configure_llm_trace_logger()
        return TracingLlm(llm, node="research")
    return llm


def get_citation_verifier(
    source: Annotated[ScholarlySourcePort, Depends(get_scholarly_source)],
) -> CitationVerifier:
    if isinstance(source, FakeScholarlySourcePort):
        return FakeCitationVerifier()
    return ProviderCitationVerifier(source)
