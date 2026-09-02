"""Deterministic paper projection from a Spec Version document (no LLM)."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from fpdf import FPDF
from markdown_it import MarkdownIt

PAPER_SECTIONS: tuple[tuple[str, str], ...] = (
    ("problem_statement", "Problem Statement"),
    ("research_question", "Research Question"),
    ("related_work", "Related Work"),
    ("research_gap", "Research Gap"),
    ("contribution", "Proposed Approach & Contribution"),
    ("claims", "Claims and Evidence"),
    ("experiment_plan", "Experiment Plan"),
    ("constraints", "Constraints"),
    ("required_resources", "Required Resources"),
    ("potential_bottlenecks", "Potential Bottlenecks"),
    ("mitigation_strategies", "Mitigation Strategies"),
    ("open_issues", "Open Issues"),
)
PAPER_SECTION_IDS: tuple[str, ...] = tuple(section_id for section_id, _ in PAPER_SECTIONS)

VALIDITY_BANNER = "This file is not the Valid Spec Version. Readiness did not pass."

_FENCE_OR_INLINE_CODE = re.compile(r"```[\s\S]*?```|`[^`]*`")
_BLOCK_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_INLINE_MATH = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)


def clarification_review_from_spec(spec_document: dict[str, Any] | None) -> dict[str, Any]:
    nodes = _dict(spec_document).get("nodes")
    nodes = nodes if isinstance(nodes, dict) else {}
    cards = _all_cards(nodes)
    original_idea = ""
    turns = _list(_dict(_dict(nodes.get("idea_interpretation")).get("narrative")).get("turns"))
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "account" and turn.get("kind") == "idea":
            text = turn.get("text")
            if isinstance(text, str):
                original_idea = text
            break
    return {
        "original_idea": original_idea,
        "gap": _card_texts(cards, "gap"),
        "contribution": _card_texts(cards, "contribution"),
        "claims": _card_text_list(cards, "claim"),
    }


def project_paper_sections(spec_document: dict[str, Any] | None) -> list[dict[str, str]]:
    nodes = _dict(spec_document).get("nodes")
    nodes = nodes if isinstance(nodes, dict) else {}
    cards = _all_cards(nodes)
    bodies = {
        "problem_statement": _card_texts(cards, "problem"),
        "research_question": _card_texts(cards, "research_question"),
        "related_work": _related_work_body(nodes),
        "research_gap": _card_texts(cards, "gap"),
        "contribution": _card_texts(cards, "contribution"),
        "claims": _claims_and_evidence_body(cards),
        "experiment_plan": _experiment_plan_body(nodes),
        "constraints": _card_texts(cards, "constraint"),
        "required_resources": _feasibility_list(nodes, "required_resources"),
        "potential_bottlenecks": _feasibility_list(nodes, "potential_bottlenecks"),
        "mitigation_strategies": _feasibility_list(nodes, "mitigation_strategies"),
        "open_issues": _card_texts(cards, "open_question"),
    }
    return [
        {"id": section_id, "title": title, "body": bodies[section_id]}
        for section_id, title in PAPER_SECTIONS
    ]


def assemble_markdown_from_sections(
    *,
    spec_version_id: Any,
    sections: list[dict[str, Any]],
    include_validity_banner: bool,
) -> str:
    lines = [f"Source Spec Version: {spec_version_id}"]
    if include_validity_banner:
        lines.append(VALIDITY_BANNER)
    lines.append("")
    by_id = {
        item["id"]: item
        for item in sections
        if isinstance(item, dict) and "id" in item
    }
    for index, (section_id, title) in enumerate(PAPER_SECTIONS, start=1):
        lines.append(f"## {index}. {title}")
        body = _paper_section_body(by_id, section_id)
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def project_export_scratch_document(
    spec_document: dict[str, Any] | None,
    *,
    spec_version_id: Any,
    spec_version_is_valid: bool,
    readiness_blocked: bool,
) -> dict[str, str]:
    return {
        "markdown": assemble_markdown_from_sections(
            spec_version_id=spec_version_id,
            sections=project_paper_sections(spec_document),
            include_validity_banner=(not spec_version_is_valid) or readiness_blocked,
        )
    }


def migrate_sections_document(
    document: dict[str, Any] | None,
    *,
    spec_version_id: Any,
) -> dict[str, str]:
    """Legacy `{ sections }` → markdown. Never stamp a live Readiness banner."""
    return {
        "markdown": assemble_markdown_from_sections(
            spec_version_id=spec_version_id,
            sections=_list(_dict(document).get("sections")),
            include_validity_banner=False,
        )
    }


def normalize_export_scratch_document(
    document: dict[str, Any] | None,
    *,
    spec_version_id: Any,
) -> dict[str, str]:
    payload = _dict(document)
    markdown = payload.get("markdown")
    if isinstance(markdown, str):
        return {"markdown": markdown}
    if "sections" in payload:
        return migrate_sections_document(payload, spec_version_id=spec_version_id)
    return {"markdown": ""}


def document_markdown(
    document: dict[str, Any] | None,
    *,
    spec_version_id: Any,
) -> str:
    return normalize_export_scratch_document(
        document, spec_version_id=spec_version_id
    )["markdown"]


def markdown_document_diff(
    current: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    *,
    spec_version_id: Any,
) -> tuple[str, str]:
    before = document_markdown(baseline, spec_version_id=spec_version_id)
    after = document_markdown(current, spec_version_id=spec_version_id)
    if before == after:
        return "", ""
    return before, after


_DEJAVU_SANS = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
_MD = MarkdownIt("commonmark").enable("table").enable("strikethrough")


def _hold_code(markdown: str) -> tuple[str, list[str]]:
    slots: list[str] = []

    def _keep(match: re.Match[str]) -> str:
        slots.append(match.group(0))
        return f"\x00CODE{len(slots) - 1}\x00"

    return _FENCE_OR_INLINE_CODE.sub(_keep, markdown), slots


def _restore_code(markdown: str, slots: list[str]) -> str:
    restored = markdown
    for index, snippet in enumerate(slots):
        restored = restored.replace(f"\x00CODE{index}\x00", snippet)
    return restored


def _math_html(tex: str, *, display: bool) -> str:
    inner = html.escape(tex.strip())
    if display:
        return f'<p class="math-display"><em>{inner}</em></p>'
    return f"<em class=\"math-inline\">{inner}</em>"


def markdown_to_html(markdown: str) -> str:
    held, slots = _hold_code(markdown)
    held = _BLOCK_MATH.sub(lambda match: _math_html(match.group(1), display=True), held)
    held = _INLINE_MATH.sub(lambda match: _math_html(match.group(1), display=False), held)
    held = _restore_code(held, slots)
    return _MD.render(held)


def render_export_scratch_pdf(markdown: str) -> bytes:
    body = markdown_to_html(markdown or "")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("DejaVu", fname=str(_DEJAVU_SANS))
    pdf.add_font("DejaVu", style="B", fname=str(_DEJAVU_SANS))
    pdf.add_font("DejaVu", style="I", fname=str(_DEJAVU_SANS))
    pdf.set_font("DejaVu", size=11)
    pdf.write_html(body or "<p></p>", font_family="DejaVu")
    return bytes(pdf.output())


def copy_paper_document(document: dict[str, Any] | None) -> dict[str, Any]:
    payload = document if isinstance(document, dict) else {"markdown": ""}
    return json.loads(json.dumps(payload))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _all_cards(nodes: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for block in nodes.values():
        if not isinstance(block, dict):
            continue
        for item in _list(block.get("card_snapshot")):
            if isinstance(item, dict):
                cards.append(item)
    return cards


def _card_text(item: dict[str, Any]) -> str:
    body = _dict(item.get("body"))
    for key in ("text", "statement"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _card_text_list(cards: list[dict[str, Any]], kind: str) -> list[str]:
    seen: set[str] = set()
    texts: list[str] = []
    for item in cards:
        if item.get("kind") != kind:
            continue
        text = _card_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts


def _card_texts(cards: list[dict[str, Any]], kind: str) -> str:
    return "\n\n".join(_card_text_list(cards, kind))


def _paper_section_body(by_id: dict[str, Any], section_id: str) -> str:
    body = str(_dict(by_id.get(section_id)).get("body") or "").strip()
    if section_id != "claims":
        return body
    extra = str(_dict(by_id.get("evidence")).get("body") or "").strip()
    return "\n\n".join(part for part in (body, extra) if part)


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    return _dict(_dict(item.get("body")).get("metadata"))


def _meta_text(meta: dict[str, Any], key: str) -> str:
    value = meta.get(key)
    return value.strip() if isinstance(value, str) else ""


def _labeled_field(label: str, value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return f"**{label}:**\n{text}"


def _h3_block(title: str, fields: list[str]) -> str:
    parts: list[str] = []
    heading = title.strip()
    if heading:
        parts.append(f"### {heading}")
    parts.extend(field for field in fields if field)
    return "\n\n".join(parts)


def _claim_title(item: dict[str, Any]) -> str:
    titled = _meta_text(_metadata(item), "claim")
    return titled or _card_text(item)


def _claim_pair_id(item: dict[str, Any]) -> str:
    raw = _metadata(item).get("id")
    if raw is None:
        return ""
    return str(raw).strip()


def _evidence_source_id(item: dict[str, Any]) -> str:
    raw = _metadata(item).get("source_claim_id")
    if raw is None:
        return ""
    return str(raw).strip()


def _claims_and_evidence_body(cards: list[dict[str, Any]]) -> str:
    claims = [item for item in cards if item.get("kind") == "claim"]
    evidences = [item for item in cards if item.get("kind") == "evidence"]
    used: set[int] = set()
    blocks: list[str] = []
    for claim in claims:
        pair_id = _claim_pair_id(claim)
        matched: list[str] = []
        if pair_id:
            for index, evidence in enumerate(evidences):
                if index in used:
                    continue
                if _evidence_source_id(evidence) != pair_id:
                    continue
                text = _card_text(evidence)
                if text:
                    matched.append(text)
                used.add(index)
        meta = _metadata(claim)
        block = _h3_block(
            _claim_title(claim),
            [
                _labeled_field("Baseline", _meta_text(meta, "baseline")),
                _labeled_field("Metric", _meta_text(meta, "metric")),
                _labeled_field("Expected Evidence", "\n\n".join(matched)),
                _labeled_field(
                    "Rejection Condition",
                    _meta_text(meta, "rejection_condition"),
                ),
            ],
        )
        if block:
            blocks.append(block)
    unpaired = [
        _card_text(evidence)
        for index, evidence in enumerate(evidences)
        if index not in used
    ]
    unpaired = [text for text in unpaired if text]
    if unpaired:
        blocks.append("### Unpaired evidence\n\n" + "\n\n".join(unpaired))
    return "\n\n".join(blocks)


def _related_work_body(nodes: dict[str, Any]) -> str:
    block = _dict(nodes.get("related_work"))
    projection = _dict(block.get("projection"))
    findings = _list(projection.get("related_work"))
    parts: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        what = finding.get("what_was_done")
        if isinstance(what, str) and what.strip():
            parts.append(what.strip())
            continue
        evidence = _dict(finding.get("evidence"))
        nested = _dict(evidence.get("what_was_done")).get("passage")
        if isinstance(nested, str) and nested.strip():
            parts.append(nested.strip())
    if parts:
        return "\n\n".join(parts)
    titles: list[str] = []
    for citation in _list(projection.get("citations")):
        if not isinstance(citation, dict):
            continue
        title = citation.get("title")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return "\n\n".join(titles)


def _experiment_plan_body(nodes: dict[str, Any]) -> str:
    narrative = _dict(_dict(nodes.get("experiment_plan")).get("narrative"))
    plan = _dict(narrative.get("plan"))
    experiments = _list(plan.get("experiments"))
    blocks: list[str] = []
    for item in experiments:
        if not isinstance(item, dict):
            continue

        block = _h3_block(
            _meta_text(item, "claim"),
            [
                _labeled_field("Action", _meta_text(item, "action")),
                _labeled_field("Objective", _meta_text(item, "objective")),
                _labeled_field("Significance", _meta_text(item, "significance")),
            ],
        )
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def _feasibility_list(nodes: dict[str, Any], field: str) -> str:
    narrative = _dict(_dict(nodes.get("feasibility")).get("narrative"))
    report = _dict(narrative.get("feasibility_report"))
    items = [
        item.strip()
        for item in _list(report.get(field))
        if isinstance(item, str) and item.strip()
    ]
    return "\n".join(items)
