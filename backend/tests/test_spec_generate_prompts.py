"""Claims / experiment / feasibility generate system prompts."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from app.modules.loop.service import LoopService
from app.modules.spec.schemas import (
    ClaimEvidenceCard,
    ExperimentItem,
    ExperimentPlan,
    FeasibilityReport,
    GenerateClaimsResponse,
)
from app.modules.spec.service import SpecService

_CLAIM_PAYLOAD = GenerateClaimsResponse(
    version=1,
    cards=[
        ClaimEvidenceCard(
            id="claim-1",
            claim="c",
            baseline="b",
            metric="m",
            evidence="e",
            rejection_condition="r",
        )
    ],
)
_PLAN = ExperimentPlan(
    experiments=[
        ExperimentItem(
            claim="c",
            action="a",
            objective="o",
            significance="s",
        )
    ]
)
_FEASIBILITY = FeasibilityReport(
    is_feasible=True,
    conclusion="ok",
    required_resources=["time"],
    potential_bottlenecks=["none"],
    mitigation_strategies=["n/a"],
)


class _CapturingStructuredLlm:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.systems: list[str] = []
        self.prompts: list[str] = []

    async def complete_structured[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
    ) -> T:
        del model
        self.systems.append(system)
        self.prompts.append(prompt)
        return TypeAdapter(schema).validate_python(
            self.payload.model_dump()
            if hasattr(self.payload, "model_dump")
            else self.payload
        )


async def _stub_ready(service: SpecService, monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(working_draft_node="claims")

    async def ready(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return session

    async def update(*_args: object, **_kwargs: object) -> int:
        return 2

    async def view(*_args: object, **_kwargs: object) -> dict:
        return {
            "node": "claims",
            "cards": [{"kind": "contribution", "text": "Primary"}],
            "gap_statement": "Gap",
            "working_draft": {"narrative": {}, "cards": []},
            "experiment_plan": {"experiments": [{"claim": "c"}]},
        }

    monkeypatch.setattr(service, "_ensure_node_ready", ready)
    monkeypatch.setattr(service, "_update_narrative", update)
    monkeypatch.setattr(LoopService, "project_prompt_view", view)


@pytest.mark.asyncio
async def test_claims_system_grounds_in_prompt_view_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _CapturingStructuredLlm(_CLAIM_PAYLOAD)
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]
    await _stub_ready(service, monkeypatch)
    await service.generate_claims(
        session_id=uuid4(), account_id=uuid4(), expected_version=1
    )
    system = llm.systems[0]
    assert "Prompt View" in system
    assert "do not invent" in system.lower() or "must not invent" in system.lower()
    assert "dataset" in system.lower() or "numeric" in system.lower()
    prompt = llm.prompts[0]
    assert prompt.count("Primary") >= 1


@pytest.mark.asyncio
async def test_experiment_system_grounds_in_prompt_view_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _CapturingStructuredLlm(_PLAN)
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]
    await _stub_ready(service, monkeypatch)
    await service.generate_experiment_plan(
        session_id=uuid4(), account_id=uuid4(), expected_version=1
    )
    system = llm.systems[0]
    assert "Prompt View" in system
    assert "do not invent" in system.lower() or "must not invent" in system.lower()


@pytest.mark.asyncio
async def test_feasibility_system_does_not_duplicate_plan_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _CapturingStructuredLlm(_FEASIBILITY)
    service = SpecService(None, llm=llm)  # type: ignore[arg-type]
    await _stub_ready(service, monkeypatch)
    await service.check_feasibility(
        session_id=uuid4(), account_id=uuid4(), expected_version=1
    )
    system = llm.systems[0]
    assert "Prompt View" in system
    assert "do not invent" in system.lower() or "must not invent" in system.lower()
    prompt = llm.prompts[0]
    assert prompt.count('"experiments"') <= 1
