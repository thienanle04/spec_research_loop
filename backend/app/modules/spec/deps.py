"""Spec module dependency bindings."""

import json

from app.adapters.llm import FitWebUiLlmPort
from app.core.config import get_settings
from app.ports.llm import LlmPort


class FakeSpecLlmPort:
    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        del system, prompt, model
        return json.dumps(
            [
                {
                    "title": "Focus on the optimization method",
                    "description": "Place the contribution in the search, mutation, or selection strategy.",
                },
                {
                    "title": "Focus on claim–evidence verification",
                    "description": "Place the contribution in how unsupported claims are detected and localized.",
                },
                {
                    "title": "Focus on human-in-the-loop control",
                    "description": "Place the contribution in how people confirm and adjust the iterative process.",
                },
            ]
        )


def get_spec_llm() -> LlmPort:
    settings = get_settings()
    provider = settings.research_llm_provider.casefold()
    if provider == "fake":
        return FakeSpecLlmPort()
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
    raise RuntimeError(f"Unsupported LLM provider for Spec: {provider}")
