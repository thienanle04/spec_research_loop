"""Rule-based Judge Issue verifiers. Read Prompt View only."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.modules.judgement.catalog import FindingKind, Severity
from app.modules.judgement.schemas import JudgeIssueDraft
from app.modules.loop.catalog import CardKind


def _gap_card(view: dict[str, Any]) -> dict[str, Any] | None:
    for card in view.get("cards") or []:
        if isinstance(card, dict) and card.get("kind") == CardKind.GAP.value:
            return card
    return None


def _gap_card_id(card: dict[str, Any] | None) -> UUID | None:
    if card is None:
        return None
    raw = card.get("id")
    if isinstance(raw, str) and raw:
        try:
            return UUID(raw)
        except ValueError:
            return None
    return None


def _supporting_citation_keys(card: dict[str, Any] | None) -> list[str]:
    if card is None:
        return []
    keys = card.get("supporting_citation_keys")
    if not isinstance(keys, list):
        return []
    return [key.strip() for key in keys if isinstance(key, str) and key.strip()]


def gap_unsupported_by_sources(view: dict[str, Any]) -> list[JudgeIssueDraft]:
    card = _gap_card(view)
    cited_keys = set(_supporting_citation_keys(card))
    passage_keys: set[str] = set()
    for item in view.get("related_work") or []:
        if not isinstance(item, dict):
            continue
        passage = item.get("supporting_passage")
        if not isinstance(passage, str) or not passage.strip():
            continue
        key = item.get("citation_key")
        if isinstance(key, str) and key.strip():
            passage_keys.add(key.strip())
    statement = view.get("gap_statement")
    has_statement = isinstance(statement, str) and bool(statement.strip())
    cited_with_passage = bool(cited_keys and (cited_keys & passage_keys))
    if has_statement and cited_with_passage:
        return []
    if not has_statement:
        reason = "The gap statement is missing, so no cited passage can support it."
    elif not cited_keys:
        reason = "The gap statement has no supporting Citations, so no cited passage supports it."
    else:
        reason = "No cited passage among the gap's supporting Citations supports the gap statement."
    return [
        JudgeIssueDraft(
            finding_kind=FindingKind.GAP_UNSUPPORTED_BY_SOURCES.value,
            severity=Severity.CRITICAL.value,
            reason=reason,
            suggestion="Cite a supporting passage or revise the gap statement.",
            target_card_id=_gap_card_id(card),
        )
    ]
