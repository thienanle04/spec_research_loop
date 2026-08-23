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


from app.modules.loop.catalog import WorkflowNode
from app.adapters.llm import get_llm_port

def get_spec_llm() -> LlmPort:
    settings = get_settings()
    provider = settings.research_llm_provider.casefold()
    if provider == "fake":
        return FakeSpecLlmPort()
    # Always use the standard LangChain LLM port so complete_structured works
    return get_llm_port(WorkflowNode.CLAIMS.value)
