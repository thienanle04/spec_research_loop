"""Spec module dependency bindings."""

import json
from collections.abc import AsyncIterator

from pydantic import TypeAdapter

from app.adapters.llm import get_llm_port
from app.modules.loop.catalog import WorkflowNode
from app.ports.llm import LlmPort


class FakeSpecLlmPort:
    """Domain fake for tests; not selected by runtime profiles (ADR 0034)."""

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
                    "experiments": [
                        {
                            "claim": "Claim-level verification reduces unsupported claims.",
                            "action": "Compare claim-level feedback against aggregate scores.",
                            "objective": "Measure unsupported-claim rate on held-out sources.",
                            "significance": "Shows whether localized feedback improves reliability.",
                        }
                    ]
                },
            },
            "FeasibilityReport": {
                "is_feasible": True,
                "conclusion": "The plan is feasible on a single GPU workstation.",
                "required_resources": ["24 GB VRAM", "8 hours compute"],
                "potential_bottlenecks": ["Full-text download rate limits"],
                "mitigation_strategies": ["Start with a smaller held-out evaluation set"],
            },
        }
        return TypeAdapter(schema).validate_python(payloads.get(schema.__name__, {}))


def get_contribution_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.CONTRIBUTION.value)


def get_claims_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.CLAIMS.value)


def get_experiment_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.EXPERIMENT_PLAN.value)


def get_feasibility_llm() -> LlmPort:
    return get_llm_port(WorkflowNode.FEASIBILITY.value)
