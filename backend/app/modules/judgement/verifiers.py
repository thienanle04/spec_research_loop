"""Rule-based Judge Issue verifiers. Read Prompt View only."""

from __future__ import annotations

import re
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


def _view_related_work_passages(view: dict[str, Any]) -> list[dict[str, Any]]:
    raw = view.get("related_work")
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        passages = raw.get("passages")
        items = passages if isinstance(passages, list) else []
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


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
    for item in _view_related_work_passages(view):
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


def _parse_card_id(raw: Any) -> UUID | None:
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return UUID(raw)
        except ValueError:
            return None
    return None


def _passage_entails_claim(claim: str, passage: str) -> bool:
    if not claim.strip() or not passage.strip():
        return False
    tokens = [token for token in re.findall(r"[a-z0-9]+", claim.casefold()) if len(token) > 3]
    if not tokens:
        return False
    haystack = passage.casefold()
    return all(token in haystack for token in tokens)


def unsupported_citation(view: dict[str, Any]) -> list[JudgeIssueDraft]:
    grouped: dict[UUID | None, list[tuple[str, str]]] = {}
    for item in view.get("claim_citation_passages") or []:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            continue
        passage = item.get("passage")
        passage_text = passage.strip() if isinstance(passage, str) else ""
        key = _parse_card_id(item.get("claim_id"))
        grouped.setdefault(key, []).append((claim.strip(), passage_text))
    issues: list[JudgeIssueDraft] = []
    for card_id, items in grouped.items():
        if any(_passage_entails_claim(claim, passage) for claim, passage in items):
            continue
        issues.append(
            JudgeIssueDraft(
                finding_kind=FindingKind.UNSUPPORTED_CITATION.value,
                severity=Severity.CRITICAL.value,
                reason="The cited passage does not entail the claim.",
                suggestion="Cite a passage that entails the claim or revise the claim.",
                target_card_id=card_id,
            )
        )
    return issues
