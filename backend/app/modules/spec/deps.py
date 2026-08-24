"""Spec module dependency bindings."""

import json
from collections.abc import AsyncIterator

from pydantic import TypeAdapter

from app.adapters.llm import FitWebUiLlmPort
from app.core.config import get_settings
from app.ports.llm import LlmPort


class FakeSpecLlmPort:
    async def stream(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        yield await self.complete(system=system, prompt=prompt, model=model)

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

    async def complete_structured[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
    ) -> T:
        del system, prompt, model
        payloads: dict[str, object] = {
            "GenerateClaimsResponse": {
                "version": 1,
                "cards": [
                    {
                        "id": "claim-1",
                        "claim": "Claim-level verification reduces unsupported claims.",
                        "baseline": "Aggregate-score feedback",
                        "metric": "Unsupported claim rate",
                        "evidence": "Evaluation on held-out scholarly sources",
                        "rejection_condition": "No statistically significant reduction",
                    }
                ],
            },
            "GenerateExperimentResponse": {
                "version": 1,
                "plan": {
                    "baselines": ["Aggregate-score feedback"],
                    "metrics": ["Unsupported claim rate"],
                    "evaluation_protocol": "Compare methods on held-out sources.",
                    "ablation_study": ["Remove claim-level verification"],
                    "generalization": ["Evaluate across research domains"],
                },
            },
            "FeasibilityReport": {
                "estimated_vram": "24 GB",
                "estimated_time": "8 hours",
                "is_feasible": True,
                "suggestions": ["Start with a smaller held-out evaluation set"],
            },
        }
        return TypeAdapter(schema).validate_python(payloads.get(schema.__name__, {}))


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
