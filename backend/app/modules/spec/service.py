"""Spec application services."""

import json
import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OperationalErrorException
from app.modules.loop.catalog import NodeHeadStatus, WorkflowNode, ancestors
from app.modules.loop.models import LoopSession, NodeHead
from app.modules.loop.service import LoopService
from app.modules.spec.schemas import (
    CheckFeasibilityResponse,
    ContributionDirection,
    ContributionDirectionKind,
    ContributionDirectionsResponse,
    ExperimentPlan,
    FeasibilityReport,
    GenerateClaimsResponse,
    GenerateExperimentResponse,
)
from app.ports.llm import LlmCompleteError, LlmPort, LlmProviderError


def _raise_llm_operational(exc: Exception) -> None:
    if isinstance(exc, LlmProviderError):
        status_code = exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE
        if status_code == 429:
            raise OperationalErrorException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="llm_rate_limited",
                detail=str(exc),
            ) from exc
        raise OperationalErrorException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="llm_provider_error",
            detail=str(exc),
        ) from exc
    if isinstance(exc, LlmCompleteError):
        raise OperationalErrorException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="llm_complete_error",
            detail=str(exc),
        ) from exc
    raise exc


class _GeneratedDirection(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    mechanism: str = Field(min_length=12, max_length=200)
    gap_link: str = Field(min_length=12, max_length=320)
    novelty: str = Field(min_length=12, max_length=320)
    validation: str = Field(min_length=12, max_length=320)


logger = logging.getLogger(__name__)

_GENERIC_DIRECTION_PREFIXES = (
    "focus on",
    "place the contribution",
    "tập trung vào",
    "đặt đóng góp",
)

_CONTRIBUTION_RELATED_WORK_LIMIT = 8
_CONTRIBUTION_TEXT_LIMIT = 1_200


_VIETNAMESE_CHARACTERS = frozenset(
    "ăâđêôơưàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ"
)
_VIETNAMESE_ASCII_WORDS = frozenset(
    {
        "cac",
        "cho",
        "cua",
        "duoc",
        "khong",
        "la",
        "mot",
        "nghien",
        "nhung",
        "phuong",
        "trong",
        "va",
        "voi",
    }
)


def _confirmed_gap_statement(view: dict[str, Any]) -> str:
    statement = view.get("gap_statement")
    if isinstance(statement, str) and statement.strip():
        return statement.strip()
    return ""


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_text(value: Any, *, limit: int = _CONTRIBUTION_TEXT_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _compact_idea(upstream: dict[str, Any]) -> dict[str, Any]:
    interpretation = _dict_value(upstream.get(WorkflowNode.IDEA_INTERPRETATION.value))
    decomposition = _dict_value(upstream.get(WorkflowNode.IDEA_DECOMPOSITION.value))
    frame = _dict_value(_dict_value(interpretation.get("narrative")).get("frame"))
    idea = {
        key: _compact_text(frame.get(key))
        for key in ("intent", "problem", "research_question")
        if _compact_text(frame.get(key))
    }
    cards: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for node in (interpretation, decomposition):
        for item in _list_value(node.get("card_snapshot")):
            item = _dict_value(item)
            kind = str(item.get("kind") or "")
            if kind not in {
                "problem",
                "research_question",
                "constraint",
                "open_question",
            }:
                continue
            body = _dict_value(item.get("body"))
            text = _compact_text(
                body.get("text")
                or body.get("statement")
                or body.get(kind)
            )
            identity = (kind, text)
            if text and identity not in seen:
                cards.append({"kind": kind, "text": text})
                seen.add(identity)
    if cards:
        idea["cards"] = cards
    return idea


def _compact_related_work(upstream: dict[str, Any]) -> dict[str, Any]:
    node = _dict_value(upstream.get(WorkflowNode.RELATED_WORK.value))
    projected = _dict_value(node.get("projected"))
    citations_by_id: dict[str, dict[str, Any]] = {}
    for raw in _list_value(projected.get("citations")):
        citation = _dict_value(raw)
        identifier = str(citation.get("id") or "")
        if not identifier:
            continue
        citations_by_id[identifier] = {
            "citation_key": _compact_text(citation.get("citation_key"), limit=200),
            "title": _compact_text(citation.get("title"), limit=500),
            "year": citation.get("year"),
            "venue": _compact_text(citation.get("venue"), limit=300),
            "verification_status": citation.get("verification_status"),
        }

    studies: list[dict[str, Any]] = []
    for raw in _list_value(projected.get("related_work"))[
        :_CONTRIBUTION_RELATED_WORK_LIMIT
    ]:
        finding = _dict_value(raw)
        citation_id = str(finding.get("citation_id") or "")
        source = citations_by_id.get(citation_id, {})
        study = {
            "source": source,
            "what_was_done": _compact_text(finding.get("what_was_done")),
            "method_or_feedback": _compact_text(finding.get("method_or_feedback")),
            "limitation": _compact_text(finding.get("limitation")),
            "relevance": _compact_text(finding.get("relevance")),
            "grounding_status": finding.get("grounding_status"),
            "confidence": finding.get("confidence"),
        }
        studies.append(
            {
                key: value
                for key, value in study.items()
                if value not in ("", None, {})
            }
        )

    if not studies:
        for _identifier, source in list(citations_by_id.items())[
            :_CONTRIBUTION_RELATED_WORK_LIMIT
        ]:
            studies.append({"source": source})

    narrative = _dict_value(node.get("narrative"))
    coverage = {
        key: narrative.get(key)
        for key in (
            "candidate_count",
            "ranked_candidate_count",
            "selected_count",
            "skipped_inaccessible_count",
        )
        if narrative.get(key) is not None
    }
    return {"studies": studies, "coverage": coverage}


def _compact_gap(upstream: dict[str, Any]) -> dict[str, Any]:
    node = _dict_value(upstream.get(WorkflowNode.GAP.value))
    body: dict[str, Any] = {}
    for raw in _list_value(node.get("card_snapshot")):
        item = _dict_value(raw)
        if item.get("kind") == "gap":
            body = _dict_value(item.get("body"))
            break
    audit = _dict_value(body.get("search_audit"))
    evidence = _dict_value(body.get("evidence_check"))
    return {
        "statement": _compact_text(
            body.get("statement") or body.get("text"), limit=3_000
        ),
        "supporting_citation_keys": _list_value(body.get("supporting_citation_keys"))[:20],
        "status": body.get("status"),
        "counter_evidence_outcome": audit.get("counter_evidence_outcome"),
        "counter_evidence_assessment": _compact_text(
            audit.get("counter_evidence_assessment")
        ),
        "evidence_ready": evidence.get("ready"),
        "evidence_messages": [
            _compact_text(item, limit=500)
            for item in _list_value(evidence.get("messages"))[:10]
        ],
    }


def _related_work_from_prompt_view(context: dict[str, Any]) -> dict[str, Any]:
    raw = context.get("related_work")
    if isinstance(raw, dict):
        return {
            "studies": _list_value(raw.get("studies")),
            "coverage": _dict_value(raw.get("coverage")),
        }
    return {"studies": _list_value(raw), "coverage": {}}


def _spec_generate_system(node: WorkflowNode) -> str:
    ground = (
        "Ground every output only in the supplied Prompt View. "
        "Do not invent datasets, numeric gains, citations, or capabilities absent from the Prompt View. "
        "If a detail is missing, name the Account decision instead of fabricating it."
    )
    if node is WorkflowNode.CLAIMS:
        return (
            "You generate Claims and Evidence Cards for a Research Spec from the Prompt View. "
            "Each generated item becomes one Claim Card (claim, baseline, metric, rejection_condition) "
            "and one Evidence Card (expected evidence). "
            + ground
        )
    if node is WorkflowNode.EXPERIMENT_PLAN:
        return (
            "You generate an experiment plan from the Prompt View. "
            "For each Claim, emit one experiment with short claim, action, objective, "
            "and significance fields. Do not copy baseline, metric, evidence, or "
            "rejection_condition into the claim field. "
            + ground
        )
    return (
        "You assess Feasibility of the experiment_plan already present in the Prompt View. "
        "Return is_feasible, conclusion, required_resources, potential_bottlenecks, "
        "and mitigation_strategies. "
        + ground
    )


def _contribution_brief(context: dict[str, Any]) -> dict[str, Any]:
    if "upstream" not in context:
        cards = [
            item
            for item in _list_value(context.get("cards"))
            if isinstance(item, dict)
        ]
        idea_kinds = {"problem", "research_question", "constraint", "open_question"}
        return {
            "idea": {
                "cards": [item for item in cards if item.get("kind") in idea_kinds]
            },
            "research_inputs": {},
            "related_work": _related_work_from_prompt_view(context),
            "confirmed_gap": {
                "statement": _compact_text(context.get("gap_statement"), limit=3_000),
                "cards": [item for item in cards if item.get("kind") == "gap"],
            },
            "working_draft": _dict_value(context.get("working_draft")),
        }
    upstream = _dict_value(context.get("upstream"))
    research_inputs = _dict_value(
        _dict_value(upstream.get(WorkflowNode.RESEARCH_INPUTS.value)).get("narrative")
    )
    return {
        "idea": _compact_idea(upstream),
        "research_inputs": {
            "keywords": [
                _compact_text(item, limit=300)
                for item in _list_value(research_inputs.get("keywords"))[:20]
            ],
            "preferred_sources": _dict_value(
                research_inputs.get("preferred_sources")
            ),
        },
        "related_work": _compact_related_work(upstream),
        "confirmed_gap": _compact_gap(upstream),
    }


def _is_vietnamese(text: str) -> bool:
    normalized = text.casefold()
    if any(character in _VIETNAMESE_CHARACTERS for character in normalized):
        return True
    words = set(re.findall(r"[a-z]+", normalized))
    return len(words & _VIETNAMESE_ASCII_WORDS) >= 2


def _direction_description(
    direction: _GeneratedDirection, output_language: str
) -> str:
    if output_language == "Vietnamese":
        return (
            f"Cơ chế: {direction.mechanism} "
            f"Liên hệ Gap: {direction.gap_link} "
            f"Điểm mới: {direction.novelty} "
            f"Kiểm chứng: {direction.validation}"
        )
    return (
        f"Mechanism: {direction.mechanism} "
        f"Gap link: {direction.gap_link} "
        f"Novelty: {direction.novelty} "
        f"Validation: {direction.validation}"
    )


def _parse_generated_directions(
    raw: str,
    output_language: str,
    *,
    allow_truncated_recovery: bool = False,
) -> list[_GeneratedDirection]:
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE
    )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        payload = _recover_complete_direction_items(cleaned)
        if not payload or not allow_truncated_recovery:
            raise
    if isinstance(payload, dict):
        payload = payload.get("directions")
    if not isinstance(payload, list):
        raise TypeError("Expected a JSON object containing a directions array")
    if not 1 <= len(payload) <= 3:
        raise ValueError("Expected between one and three directions")
    proposed = [_GeneratedDirection.model_validate(item) for item in payload]
    normalized_titles = [item.title.strip().casefold() for item in proposed]
    if len(set(normalized_titles)) != len(normalized_titles):
        raise ValueError("Direction titles must be distinct")
    if any(
        title.startswith(prefix)
        for title in normalized_titles
        for prefix in _GENERIC_DIRECTION_PREFIXES
    ):
        raise ValueError("Direction titles must name a concrete proposal")
    generated_text = " ".join(
        f"{item.title} {item.mechanism} {item.gap_link} "
        f"{item.novelty} {item.validation}"
        for item in proposed
    )
    if _is_vietnamese(generated_text) != (output_language == "Vietnamese"):
        raise ValueError("Directions did not match the confirmed Gap language")
    return proposed


def _recover_complete_direction_items(raw: str) -> list[dict[str, Any]]:
    """Recover valid flat items before a token-truncated directions tail."""
    stripped = raw.rstrip()
    if stripped.endswith(("}", "]")):
        return []
    wrapper = re.search(r'"directions"\s*:\s*\[', raw)
    if wrapper is not None:
        position = wrapper.end()
    else:
        array = re.match(r"\s*\[", raw)
        if array is None:
            return []
        position = array.end()

    decoder = json.JSONDecoder()
    recovered: list[dict[str, Any]] = []
    while position < len(raw) and len(recovered) < 3:
        while position < len(raw) and raw[position] in " \t\r\n,":
            position += 1
        if position >= len(raw) or raw[position] == "]":
            break
        try:
            item, end = decoder.raw_decode(raw, position)
        except json.JSONDecodeError:
            break
        if not isinstance(item, dict):
            break
        recovered.append(item)
        position = end
    return recovered


class SpecService:
    def __init__(self, db: AsyncSession, *, llm: LlmPort) -> None:
        self._db = db
        self._llm = llm

    async def _ensure_node_ready(
        self,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        node: WorkflowNode,
    ) -> LoopSession:
        session = await self._db.scalar(
            select(LoopSession).where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
            )
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Loop Session not found"
            )
        if session.working_draft_node != node.value:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_working_draft_target",
                detail=f"This operation requires {node.value} to be the Working Draft",
            )
        heads = list(
            (
                await self._db.scalars(
                    select(NodeHead).where(NodeHead.session_id == session_id)
                )
            ).all()
        )
        status_by_node = {WorkflowNode(head.node): head.status for head in heads}
        if any(
            status_by_node[ancestor] != NodeHeadStatus.CURRENT.value
            for ancestor in ancestors(node)
        ):
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="upstream_not_current",
                detail="Upstream Workflow Nodes must be current",
            )
        return session

    async def _update_narrative(
        self,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        narrative: dict,
        session: LoopSession,
    ) -> int:
        saved_narratives = dict(session.working_draft_narratives)
        saved_narratives[session.working_draft_node] = narrative
        result = await self._db.execute(
            update(LoopSession)
            .where(
                LoopSession.id == session_id,
                LoopSession.account_id == account_id,
                LoopSession.version == expected_version,
            )
            .values(
                working_draft_narrative=narrative,
                working_draft_narratives=saved_narratives,
                version=LoopSession.version + 1,
            )
            .returning(LoopSession.version)
            .execution_options(synchronize_session=False)
        )
        row = result.one_or_none()
        if row is None:
            await self._db.refresh(session, attribute_names=["version"])
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="version_conflict",
                detail="Loop Session was changed by another request",
                current_version=session.version,
            )
        await self._db.execute(
            update(NodeHead)
            .where(
                NodeHead.session_id == session_id,
                NodeHead.node == session.working_draft_node,
            )
            .values(generated_since_prepare=True)
            .execution_options(synchronize_session=False)
        )
        await self._db.commit()
        return row.version

    async def generate_contribution_directions(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> ContributionDirectionsResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.CONTRIBUTION
        )

        view = await LoopService(self._db).project_prompt_view(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.CONTRIBUTION,
        )
        output_language = (
            "Vietnamese"
            if _is_vietnamese(_confirmed_gap_statement(view))
            else "English"
        )
        proposed = await self._propose_directions(view, output_language)
        directions = [
            ContributionDirection(
                id=f"direction-{chr(97 + index)}",
                title=item.title,
                description=_direction_description(item, output_language),
            )
            for index, item in enumerate(proposed[:3])
        ]
        fixed_directions = (
            [
                ContributionDirection(
                    id="combine",
                    title="Kết hợp các hướng",
                    description=(
                        "Chọn một đóng góp chính và một hoặc nhiều đóng góp hỗ trợ."
                    ),
                    kind=ContributionDirectionKind.COMBINE,
                ),
                ContributionDirection(
                    id="other",
                    title="Khác",
                    description="Viết một hướng đóng góp khác.",
                    kind=ContributionDirectionKind.OTHER,
                ),
            ]
            if output_language == "Vietnamese"
            else [
                ContributionDirection(
                    id="combine",
                    title="Combine directions",
                    description="Choose one primary contribution and one or more supporting contributions.",
                    kind=ContributionDirectionKind.COMBINE,
                ),
                ContributionDirection(
                    id="other",
                    title="Other",
                    description="Write a different contribution direction.",
                    kind=ContributionDirectionKind.OTHER,
                ),
            ]
        )
        directions.extend(fixed_directions)
        narrative = {
            "directions": [item.model_dump(mode="json") for item in directions]
        }

        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return ContributionDirectionsResponse(
            version=new_version, directions=directions
        )

    async def generate_claims(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> GenerateClaimsResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.CLAIMS
        )
        view = await LoopService(self._db).project_prompt_view(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.CLAIMS,
        )

        system = _spec_generate_system(WorkflowNode.CLAIMS)
        prompt = json.dumps(view, default=str, ensure_ascii=False)
        try:
            response_data = await self._llm.complete_structured(
                system=system, prompt=prompt, schema=GenerateClaimsResponse
            )
        except (LlmCompleteError, LlmProviderError) as exc:
            _raise_llm_operational(exc)

        narrative = {
            "cards": [card.model_dump(mode="json") for card in response_data.cards]
        }
        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return GenerateClaimsResponse(version=new_version, cards=response_data.cards)

    async def generate_experiment_plan(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
    ) -> GenerateExperimentResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.EXPERIMENT_PLAN
        )
        view = await LoopService(self._db).project_prompt_view(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.EXPERIMENT_PLAN,
        )

        system = _spec_generate_system(WorkflowNode.EXPERIMENT_PLAN)
        prompt = json.dumps(view, default=str, ensure_ascii=False)
        try:
            response_data = await self._llm.complete_structured(
                system=system,
                prompt=prompt,
                schema=ExperimentPlan
            )
        except (LlmCompleteError, LlmProviderError) as exc:
            _raise_llm_operational(exc)
        
        narrative = {
            "plan": response_data.model_dump(mode="json")
        }
        new_version = await self._update_narrative(session_id, account_id, expected_version, narrative, session)
        return GenerateExperimentResponse(version=new_version, plan=response_data)

    async def check_feasibility(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        plan: dict | None = None,
    ) -> CheckFeasibilityResponse:
        session = await self._ensure_node_ready(
            session_id, account_id, expected_version, WorkflowNode.FEASIBILITY
        )
        view = await LoopService(self._db).project_prompt_view(
            session_id=session_id,
            account_id=account_id,
            node=WorkflowNode.FEASIBILITY,
        )

        system = _spec_generate_system(WorkflowNode.FEASIBILITY)
        payload = dict(view)
        if plan:
            payload["experiment_plan"] = plan
        prompt = json.dumps(payload, default=str, ensure_ascii=False)
        try:
            report = await self._llm.complete_structured(
                system=system, prompt=prompt, schema=FeasibilityReport
            )
        except (LlmCompleteError, LlmProviderError) as exc:
            _raise_llm_operational(exc)

        narrative = {"feasibility_report": report.model_dump(mode="json")}
        new_version = await self._update_narrative(
            session_id, account_id, expected_version, narrative, session
        )
        return CheckFeasibilityResponse(version=new_version, report=report)

    async def _propose_directions(
        self, view: dict[str, Any], output_language: str
    ) -> list[_GeneratedDirection]:
        gap_statement = _confirmed_gap_statement(view)
        brief = _contribution_brief(view)
        system = (
            "spec-contribution-directions: propose one to three genuinely distinct, "
            "research-ready Contribution directions grounded only in the confirmed Idea, "
            "Related Work, and Gap in the supplied Contribution Brief. A direction is not a "
            "theme or category: it must state what artifact or mechanism would be introduced, "
            "which exact limitation it changes, why that differs from the closest Related Work, "
            "and how the difference could be falsified. Titles must name the proposed mechanism "
            "or artifact; never use generic titles such as 'Focus on ...' or 'Tập trung vào ...'. "
            "Do not invent datasets, numeric gains, citations, or capabilities absent from the "
            "context. If the context cannot support a detail, state the decision that the Account "
            "must resolve instead of fabricating it. Return only one JSON object with a single "
            "directions field containing an array. Every array item must contain exactly these "
            "string fields: title, mechanism, gap_link, novelty, validation. "
            "Generate exactly three distinct directions whenever the supplied evidence supports "
            "them. Keep title at no more than 100 characters. Keep mechanism to one short, direct "
            "sentence of no more than 140 characters. Keep gap_link, novelty, and validation to "
            "one sentence and no more than 220 characters each. Compact fields instead of "
            "dropping a grounded direction. "
            "Use gap_link to explicitly connect the mechanism to the confirmed Gap; use novelty "
            "to compare against the closest named Related Work; use validation to name a baseline, "
            "observable outcome, and rejection condition without made-up target values. "
            f"Write every field in {output_language}. Do not include Combine or Other."
        )
        prompt = json.dumps(
            {
                "required_output_language": output_language,
                "confirmed_gap_statement": gap_statement,
                "contribution_brief": brief,
            },
            default=str,
            ensure_ascii=False,
        )
        last_error: Exception | None = None
        previous_output = ""
        for attempt in range(2):
            try:
                if attempt == 0:
                    attempt_system = system
                    attempt_prompt = prompt
                else:
                    attempt_system = (
                        system
                        + " Your previous response failed the output contract. Repair it; do not "
                        "explain the repair and do not repeat generic wording. Shorten aggressively "
                        "to the stated character limits and return three complete directions when "
                        "the context supports them. Return fewer only when the evidence cannot "
                        "ground three genuinely distinct directions. Always close the JSON object."
                    )
                    attempt_prompt = json.dumps(
                        {
                            "input": json.loads(prompt),
                            "previous_output": previous_output,
                            "validation_error": str(last_error),
                        },
                        default=str,
                        ensure_ascii=False,
                    )
                previous_output = await self._llm.complete(
                    system=attempt_system,
                    prompt=attempt_prompt,
                )
                return _parse_generated_directions(
                    previous_output,
                    output_language,
                    allow_truncated_recovery=attempt == 1,
                )
            except Exception as error:  # noqa: BLE001 - retry provider/contract failures once
                last_error = error

        if isinstance(last_error, (LlmCompleteError, LlmProviderError)):
            _raise_llm_operational(last_error)
        logger.warning(
            "Contribution direction generation failed after repair attempt",
            exc_info=(type(last_error), last_error, last_error.__traceback__)
            if last_error is not None
            else None,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not generate specific contribution directions from the confirmed Gap. "
                "Please retry; no generic fallback was saved."
            ),
        )
