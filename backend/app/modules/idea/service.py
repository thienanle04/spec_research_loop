"""Idea generate: stream LLM, parse trailer, apply once via loop (ADR 0024, 0025)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm import get_llm_port
from app.core.errors import OperationalErrorException
from app.modules.idea.inflight import generate_lock
from app.modules.idea.prompts import system_prompt, user_prompt
from app.modules.idea.trailer import TrailerParseError, TrailerSplitter
from app.modules.loop.catalog import CardKind, WorkflowNode
from app.modules.loop.interpretation_turns import (
    append_answers_cluster,
    append_cluster_only,
    append_idea_cluster,
    append_note_cluster,
    empty_frame,
    frame_complete,
    has_idea,
    last_is_account,
    normalize_answers,
    parse_frame,
    turns_of,
    unanswered_cluster,
)
from app.modules.loop.schemas import LoopSessionResponse
from app.modules.loop.service import LoopService
from app.ports.llm import LlmCompleteError, LlmProviderError

_GRILLING = {WorkflowNode.IDEA_INTERPRETATION, WorkflowNode.IDEA_DECOMPOSITION}


def _sse(payload: dict[str, Any]) -> str:
    return f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _confirmed_idea_frame(context: dict[str, Any]) -> dict[str, str]:
    upstream = context.get("upstream")
    if not isinstance(upstream, dict):
        return parse_frame(None)
    interpretation = upstream.get(WorkflowNode.IDEA_INTERPRETATION.value)
    if not isinstance(interpretation, dict):
        return parse_frame(None)
    narrative = interpretation.get("narrative")
    if not isinstance(narrative, dict):
        return parse_frame(None)
    return parse_frame(narrative.get("frame"))


def _cards_from_confirmed_frame(
    context: dict[str, Any],
    cards: list[tuple[CardKind, str]],
) -> list[tuple[CardKind, str]]:
    frame = _confirmed_idea_frame(context)
    if not frame_complete(frame):
        raise OperationalErrorException(
            status_code=status.HTTP_409_CONFLICT,
            code="missing_idea_frame",
            detail="Decomposition requires a confirmed non-blank Idea Frame",
        )
    rest = [
        item
        for item in cards
        if item[0] not in {CardKind.PROBLEM, CardKind.RESEARCH_QUESTION}
    ]
    return [
        (CardKind.PROBLEM, frame["problem"]),
        (CardKind.RESEARCH_QUESTION, frame["research_question"]),
        *rest,
    ]


@dataclass
class GenerateRun:
    session: LoopSessionResponse
    context: dict[str, Any]
    message: str | None
    answers: list[dict[str, str]] | None
    note: str | None
    mode: str


class IdeaService:
    def __init__(self, db: AsyncSession) -> None:
        self._loop = LoopService(db)

    async def prepare_generate(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        message: str | None,
        answers: list[dict[str, str]] | None = None,
        note: str | None = None,
    ) -> GenerateRun:
        acquired = await generate_lock.acquire(session_id)
        if not acquired:
            raise OperationalErrorException(
                status_code=status.HTTP_409_CONFLICT,
                code="generate_in_flight",
                detail="A generate is already running for this Loop Session",
            )
        try:
            session = await self._loop.get_session(session_id=session_id, account_id=account_id)
            node = session.working_draft_node
            if node not in _GRILLING:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="invalid_generate_node",
                    detail="Generate requires the Working Draft to be a Grilling Workflow Node",
                )
            if session.version != expected_version:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="version_conflict",
                    detail="Loop Session was changed by another request",
                    current_version=session.version,
                )
            mode = "decomposition"
            normalized_answers: list[dict[str, str]] | None = None
            note_text = note.strip() if (note or "").strip() else None
            if node is WorkflowNode.IDEA_INTERPRETATION:
                turns = turns_of(dict(session.working_draft_narrative))
                cluster = unanswered_cluster(turns)
                has_message = bool((message or "").strip())
                has_answers = answers is not None
                has_note = note_text is not None
                if cluster is not None:
                    if has_message:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="unexpected_generate_message",
                            detail="Cluster Send uses answers and/or an Account note, not message",
                        )
                    if has_answers:
                        normalized_answers = normalize_answers(cluster, answers or [])
                        mode = "answers"
                    elif has_note:
                        mode = "note"
                    else:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="empty_generate_answers",
                            detail="Cluster Send requires answers or an Account note",
                        )
                elif not has_idea(turns):
                    if has_answers:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="unexpected_generate_answers",
                            detail="The first interpretation Send is the research idea",
                        )
                    if has_note:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="unexpected_generate_note",
                            detail="The first interpretation Send is the research idea",
                        )
                    if not has_message:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="empty_generate_message",
                            detail="Interpretation generate requires a message",
                        )
                    mode = "idea"
                elif last_is_account(turns):
                    if has_answers:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="unexpected_generate_answers",
                            detail="Re-generate the next cluster from the corrected turn list",
                        )
                    if has_message:
                        raise OperationalErrorException(
                            status_code=status.HTTP_409_CONFLICT,
                            code="unexpected_generate_payload",
                            detail="Re-generate the next cluster from the corrected turn list",
                        )
                    mode = "note" if has_note else "recluster"
                elif has_note and not has_answers and not has_message:
                    mode = "note"
                else:
                    raise OperationalErrorException(
                        status_code=status.HTTP_409_CONFLICT,
                        code="no_unanswered_cluster",
                        detail="There is no unanswered Grilling Question cluster to Send",
                    )
            elif answers is not None:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="unexpected_generate_answers",
                    detail="Decomposition generate does not take Grilling Option answers",
                )
            elif note_text:
                raise OperationalErrorException(
                    status_code=status.HTTP_409_CONFLICT,
                    code="unexpected_generate_note",
                    detail="Decomposition generate does not take an Account note",
                )
            context = await self._loop.project_context(
                session_id=session_id,
                account_id=account_id,
                node=node,
            )
            return GenerateRun(
                session=session,
                context=context,
                message=(message.strip() if (message or "").strip() else None),
                answers=normalized_answers,
                note=note_text,
                mode=mode,
            )
        except Exception:
            await generate_lock.release(session_id)
            raise

    async def stream_generate(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        run: GenerateRun,
        request: Request,
    ) -> AsyncIterator[str]:
        try:
            async for chunk in self._stream(
                session_id=session_id,
                account_id=account_id,
                expected_version=expected_version,
                run=run,
                request=request,
            ):
                yield chunk
        finally:
            await generate_lock.release(session_id)

    async def _stream(
        self,
        *,
        session_id: UUID,
        account_id: UUID,
        expected_version: int,
        run: GenerateRun,
        request: Request,
    ) -> AsyncIterator[str]:
        node = run.session.working_draft_node
        llm = get_llm_port(node.value)
        splitter = TrailerSplitter()
        yield _sse({"type": "progress", "message": "Generating…"})
        try:
            async with aclosing(
                llm.stream(
                    system=system_prompt(node),
                    prompt=user_prompt(
                        context=run.context,
                        message=run.message,
                        answers=run.answers,
                        note=run.note,
                    ),
                )
            ) as tokens:
                async for token in tokens:
                    if await request.is_disconnected():
                        return
                    visible = splitter.feed(token)
                    if visible:
                        yield _sse({"type": "token", "text": visible})
            prose, parsed = splitter.finish(
                interpretation=node is WorkflowNode.IDEA_INTERPRETATION,
            )
        except LlmCompleteError as exc:
            yield _sse({"type": "error", "code": "llm_complete_error", "detail": str(exc)})
            return
        except LlmProviderError as exc:
            code = "llm_rate_limited" if exc.status_code == 429 else "llm_provider_error"
            yield _sse({"type": "error", "code": code, "detail": str(exc)})
            return
        except TrailerParseError as exc:
            yield _sse({"type": "error", "code": "generate_parse_error", "detail": str(exc)})
            return

        if await request.is_disconnected():
            return

        exhausted = parsed["exhausted"] if node is WorkflowNode.IDEA_INTERPRETATION else False
        preamble = parsed["preamble"] if parsed.get("preamble") else prose
        questions = parsed["questions"] if node is WorkflowNode.IDEA_INTERPRETATION else []
        narrative = dict(run.session.working_draft_narrative)
        if node is WorkflowNode.IDEA_INTERPRETATION:
            frame = parsed.get("frame") or empty_frame()
            if run.mode == "idea":
                narrative = append_idea_cluster(
                    narrative,
                    idea=run.message or "",
                    preamble=preamble,
                    questions=questions,
                    exhausted=exhausted,
                    frame=frame,
                )
            elif run.mode == "answers":
                narrative = append_answers_cluster(
                    narrative,
                    answers=run.answers or [],
                    preamble=preamble,
                    questions=questions,
                    exhausted=exhausted,
                    frame=frame,
                    note=run.note,
                )
            elif run.mode == "note":
                narrative = append_note_cluster(
                    narrative,
                    note=run.note or "",
                    preamble=preamble,
                    questions=questions,
                    exhausted=exhausted,
                    frame=frame,
                )
            else:
                narrative = append_cluster_only(
                    narrative,
                    preamble=preamble,
                    questions=questions,
                    exhausted=exhausted,
                    frame=frame,
                )
        card_texts = parsed["cards"] if node is WorkflowNode.IDEA_DECOMPOSITION else None
        try:
            if card_texts is not None:
                card_texts = _cards_from_confirmed_frame(run.context, card_texts)
            applied: LoopSessionResponse = await self._loop.apply_idea_generate(
                session_id=session_id,
                account_id=account_id,
                expected_version=expected_version,
                narrative=narrative,
                card_texts=card_texts,
            )
        except OperationalErrorException as exc:
            payload: dict[str, Any] = {
                "type": "error",
                "code": exc.error.code,
                "detail": exc.error.detail,
            }
            if exc.error.current_version is not None:
                payload["current_version"] = exc.error.current_version
            yield _sse(payload)
            return

        result: dict[str, Any] = {"type": "result", "exhausted": exhausted, "preamble": preamble}
        if node is WorkflowNode.IDEA_INTERPRETATION:
            result["questions"] = questions
        else:
            result["prose"] = prose
        yield _sse(result)
        yield _sse({"type": "done", "version": applied.version})
