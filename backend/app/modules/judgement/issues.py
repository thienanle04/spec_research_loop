"""Normalize LLM Judge output against the Finding Kind catalog and floors."""

from uuid import UUID

from app.modules.judgement.catalog import (
    SEVERITY_RANK,
    FindingKind,
    apply_floor,
    parse_finding_kind,
    parse_severity,
)
from app.modules.judgement.schemas import JudgeIssueDraft


def normalize_llm_issues(raw_issues: list[JudgeIssueDraft]) -> list[JudgeIssueDraft]:
    normalized: list[JudgeIssueDraft] = []
    seen: set[tuple[FindingKind, UUID | None]] = set()
    for item in raw_issues:
        kind = parse_finding_kind(item.finding_kind)
        severity = parse_severity(item.severity)
        if kind is None or severity is None:
            continue
        floored = apply_floor(kind, severity)
        key = (kind, item.target_card_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            JudgeIssueDraft(
                finding_kind=kind.value,
                severity=floored.value,
                reason=item.reason,
                suggestion=item.suggestion,
                target_card_id=item.target_card_id,
            )
        )
    return normalized


def merge_issues(
    llm_issues: list[JudgeIssueDraft],
    verifier_issues: list[JudgeIssueDraft],
) -> list[JudgeIssueDraft]:
    rank = {severity.value: index for severity, index in SEVERITY_RANK.items()}
    by_key: dict[tuple[str, UUID | None], JudgeIssueDraft] = {
        (item.finding_kind, item.target_card_id): item for item in llm_issues
    }
    for issue in verifier_issues:
        key = (issue.finding_kind, issue.target_card_id)
        existing = by_key.get(key)
        if existing is None and issue.target_card_id is not None:
            existing = by_key.pop((issue.finding_kind, None), None)
        if existing is None or rank[existing.severity] < rank[issue.severity]:
            by_key[key] = issue
            continue
        by_key[key] = existing.model_copy(update={"target_card_id": issue.target_card_id})
    return list(by_key.values())
