"""Judge and Aggregator system prompts carry Finding Kind contracts."""

from uuid import uuid4

import pytest

from app.adapters.llm.fake import FakeLlm
from app.modules.judgement.catalog import FINDING_KIND_FLOOR, FindingKind
from app.modules.judgement.service import GenerationRun, JudgementService
from app.modules.loop.catalog import WorkflowNode

_GAP_KINDS = (
    FindingKind.GAP_UNSUPPORTED_BY_SOURCES.value,
    FindingKind.GAP_ALREADY_ADDRESSED.value,
    FindingKind.GAP_UNTESTABLE.value,
)
_CONTRIBUTION_KINDS = (
    FindingKind.CONTRIBUTION_NOT_NOVEL.value,
    FindingKind.CONTRIBUTION_OVERCLAIMED.value,
)
_EVIDENCE_KINDS = (FindingKind.UNSUPPORTED_CITATION.value,)
_EXPERIMENT_KINDS = (
    FindingKind.CLAIM_BROADER_THAN_EXPERIMENT.value,
    FindingKind.EXPERIMENT_INSUFFICIENT_FOR_CLAIM.value,
)


def _run(node: WorkflowNode, *, view: dict | None = None) -> GenerationRun:
    return GenerationRun(
        session_id=uuid4(),
        account_id=uuid4(),
        node=node,
        version=1,
        view=view or {"node": node.value},
    )


async def _capture_system(node: WorkflowNode, response: str, *, view: dict | None = None) -> str:
    fake = FakeLlm(response=response)
    service = JudgementService(None, llm=fake)  # type: ignore[arg-type]
    await service._complete_llm(_run(node, view=view), fake)
    assert fake.calls
    return fake.calls[0].system


@pytest.mark.asyncio
async def test_gap_judge_system_names_kinds_floors_and_independence() -> None:
    system = await _capture_system(
        WorkflowNode.GAP_JUDGE,
        '{"issues": []}',
    )
    for kind in _GAP_KINDS:
        assert kind in system
        assert FINDING_KIND_FLOOR[FindingKind(kind)].value in system
    assert "independen" in system.lower()
    assert "do not drop" in system.lower() or "must not drop" in system.lower()
    assert "verifier" in system.lower()
    assert "must not invent" in system.lower() or "do not invent" in system.lower()
    assert system != "judge-gap"


@pytest.mark.asyncio
async def test_contribution_judge_system_names_kinds_and_floors() -> None:
    system = await _capture_system(
        WorkflowNode.CONTRIBUTION_JUDGE,
        '{"issues": []}',
    )
    for kind in _CONTRIBUTION_KINDS:
        assert kind in system
        assert FINDING_KIND_FLOOR[FindingKind(kind)].value in system
    assert "independen" in system.lower()
    assert system != "judge-contribution"


@pytest.mark.asyncio
async def test_evidence_judge_system_keeps_unsupported_citation_floor() -> None:
    system = await _capture_system(
        WorkflowNode.EVIDENCE_JUDGE,
        '{"issues": []}',
    )
    assert FindingKind.UNSUPPORTED_CITATION.value in system
    assert "CRITICAL" in system
    assert "verifier" in system.lower()
    assert system != "judge-evidence"


@pytest.mark.asyncio
async def test_experiment_judge_system_names_claim_experiment_kinds() -> None:
    system = await _capture_system(
        WorkflowNode.EXPERIMENT_JUDGE,
        '{"issues": []}',
    )
    for kind in _EXPERIMENT_KINDS:
        assert kind in system
    assert system != "judge-experiment"


@pytest.mark.asyncio
async def test_conference_judge_system_is_scores_only() -> None:
    system = await _capture_system(
        WorkflowNode.CONFERENCE_JUDGE,
        '{"scores": {"originality": 5, "significance": 5, "soundness": 5, "clarity": 5, "reproducibility": 5}}',
    )
    assert "scores only" in system.lower() or "criterion scores only" in system.lower()
    assert "originality" in system.lower()
    assert "Judge Issue" in system or "finding kind" in system.lower()
    assert system != "judge-conference"


@pytest.mark.asyncio
async def test_aggregator_system_is_phrasing_only_and_does_not_invent_other() -> None:
    view = {
        "node": "aggregator",
        "judge_runs": [
            {"node": node.value, "issues": [], "scores": None}
            for node in (
                WorkflowNode.GAP_JUDGE,
                WorkflowNode.CONTRIBUTION_JUDGE,
                WorkflowNode.EVIDENCE_JUDGE,
                WorkflowNode.EXPERIMENT_JUDGE,
                WorkflowNode.CONFERENCE_JUDGE,
            )
        ],
    }
    view["judge_runs"][-1]["scores"] = {
        "originality": 5,
        "significance": 5,
        "soundness": 5,
        "clarity": 5,
        "reproducibility": 5,
    }
    system = await _capture_system(
        WorkflowNode.AGGREGATOR,
        '{"options": []}',
        view=view,
    )
    assert "phras" in system.lower()
    assert "Other" in system
    assert "must not invent" in system.lower() or "do not invent" in system.lower()
    assert "Severity" in system
    assert system != "aggregator"
