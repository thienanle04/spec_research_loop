"""Deterministic LLM port for research development and tests."""

import json
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import TypeAdapter


class FakeLlmPort:
    """Return schema-shaped JSON without network access or an API key."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        yield await self.complete(system=system, prompt=prompt, model=model)

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        self.calls.append({"system": system, "prompt": prompt, "model": model})
        for key, response in self.responses.items():
            if key in system:
                return response
        payload = _load_payload(prompt)
        if "research-rerank" in system:
            candidates = payload.get("candidates", [])
            count = max(len(candidates), 1)
            return json.dumps(
                {
                    "rankings": [
                        {
                            "result_key": item["result_key"],
                            "relevance_score": round((count - index) / count, 4),
                        }
                        for index, item in enumerate(candidates)
                        if item.get("result_key")
                    ]
                }
            )
        if "research-discovery" in system:
            keywords = [str(item) for item in payload.get("confirmed_keywords", [])]
            tool_keywords = [
                keyword
                for keyword in keywords
                if any(
                    term in keyword.casefold()
                    for term in (
                        "prompt",
                        "optimization",
                        "refinement",
                        "feedback",
                        "judge",
                        "evaluation",
                        "grading",
                        "evaluator",
                    )
                )
            ]
            tool_keyword_keys = {keyword.casefold() for keyword in tool_keywords}
            concept_text = " ".join(tool_keywords).casefold()
            tools: list[str] = []
            if any(
                term in concept_text
                for term in ("prompt", "optimization", "refinement", "feedback")
            ):
                tools.extend(["DSPy", "TextGrad", "OPRO", "ProTeGi"])
            if any(
                term in concept_text
                for term in ("judge", "evaluation", "grading", "evaluator")
            ):
                tools.extend(["G-Eval", "Prometheus"])
            return json.dumps(
                {
                    "tool_discovery_keywords": tool_keywords,
                    "supporting_context_keywords": [
                        keyword
                        for keyword in keywords
                        if keyword.casefold() not in tool_keyword_keys
                    ],
                    "tools_and_frameworks": list(dict.fromkeys(tools)),
                    "techniques": keywords[:8],
                    "candidate_work_titles": [],
                    "aliases": [],
                }
            )
        if "research-query" in system:
            inputs = payload.get("inputs", {})
            keywords = inputs.get("keywords") or ["related work"]
            query = " ".join(keywords[:4]).strip()
            base = query or "related work"
            return json.dumps(
                {
                    "queries": [
                        base,
                        f"{base} limitations",
                        f"{base} benchmark",
                        f"{base} survey",
                    ]
                }
            )
        if "research-counter-query" in system:
            prior_queries = payload.get("prior_queries") or [
                "scholarly evidence review"
            ]
            base = str(prior_queries[0])
            return json.dumps(
                {
                    "queries": [
                        f"{base} competing methods",
                        f"{base} equivalent approach",
                        f"{base} replication benchmark",
                    ]
                }
            )
        if "research-analysis" in system:
            citation = payload.get("citation", {})
            abstract = citation.get("abstract") or "No abstract was provided."
            evidence = {"passage": abstract[:500], "location": "Abstract"}
            return json.dumps(
                {
                    "study_name": (
                        (citation.get("metadata") or {}).get("research_work_name")
                        or str(citation.get("title", "Unnamed approach")).split(":", 1)[0]
                    ),
                    "what_was_done": f"Analyzes {citation.get('title', 'the source')}.",
                    "method_or_feedback": "Iterative model feedback",
                    "limitation": "The reported evaluation does not isolate claim-level evidence errors.",
                    "relevance": "Relevant to iterative optimization and verification.",
                    "supporting_passage": abstract[:500],
                    "evidence": {
                        "what_was_done": evidence,
                        "method_or_feedback": evidence,
                        "limitation": evidence,
                    },
                    "confidence": 0.8,
                }
            )
        if any(
            marker in system
            for marker in (
                "research-gap-claim-support-check",
                "research-gap-claim-support-repair",
                "research-gap-claim-support-item-check",
                "research-gap-claim-support-confirmation",
            )
        ):
            claim_candidates = payload.get("claim_candidates", [])
            if not claim_candidates and payload.get("claim_candidate"):
                claim_candidates = [payload["claim_candidate"]]
            return json.dumps(
                {
                    "assessments": [
                        {
                            "claim_id": item.get("claim_id"),
                            "support_status": (
                                "supported"
                                if item.get("supporting_evidence")
                                else "uncertain"
                            ),
                            "atomicity_status": (
                                "compound"
                                if ";" in str(item.get("statement") or "")
                                or "\n" in str(item.get("statement") or "")
                                else "atomic"
                            ),
                            "evidence_span": str(
                                (item.get("supporting_evidence") or [{}])[0].get(
                                    "passage", ""
                                )
                            ),
                            "unsupported_fragments": [],
                        }
                        for item in claim_candidates
                        if item.get("claim_id")
                    ]
                }
            )
        if "research-gap-analysis" in system:
            citations = payload.get("citations", [])
            related_work = payload.get("related_work", [])
            claim_candidates = payload.get("claim_candidates", [])
            keys = [item["citation_key"] for item in citations]
            return json.dumps(
                {
                    "prior_work": "Prior systems optimize outputs or prompts using aggregate feedback.",
                    "limitation": " ".join(
                        str(item.get("limitation") or "") for item in related_work
                    )
                    or "Aggregate scores do not localize unsupported claims.",
                    "importance": "Localized feedback can make optimization more reliable.",
                    "testability": "Compare unsupported-claim rates on held-out sources.",
                    "covered_citation_keys": keys,
                    "claims": claim_candidates,
                }
            )
        if "research-gap-synthesis" in system:
            return json.dumps(
                {
                    "statement": (
                        "Prior systems optimize outputs or prompts using aggregate scores "
                        "or textual feedback. It remains unclear whether decomposing outputs "
                        "into claims, checking evidence independently, and using claim-level "
                        "errors as feedback reduces unsupported claims under the same "
                        "inference budget."
                    )
                }
            )
        if any(
            marker in system
            for marker in (
                "research-counter-support-check",
                "research-counter-support-repair",
                "research-counter-support-item-check",
            )
        ):
            findings = payload.get("findings", [])
            if not findings and payload.get("finding"):
                findings = [payload["finding"]]
            return json.dumps(
                {
                    "assessments": [
                        {
                            "result_key": item.get("result_key"),
                            "support_status": (
                                "supported"
                                if item.get("source_text")
                                and item.get("supporting_passage")
                                else "uncertain"
                            ),
                        }
                        for item in findings
                        if item.get("result_key")
                    ]
                }
            )
        if "research-counter-source-analysis" in system:
            result = payload.get("counter_evidence_result", {})
            claims = payload.get("gap_claims", [])
            source_text = str(result.get("source_text") or "")
            impact = (
                "no_direct_counter_evidence" if source_text else "inconclusive"
            )
            return json.dumps(
                {
                    "result_key": result.get("result_key"),
                    "impact": impact,
                    "relevance_status": (
                        "relevant" if source_text else "uncertain"
                    ),
                    "rationale": (
                        "The supplied source content does not directly resolve the "
                        "provisional limitation."
                    ),
                    "supporting_passage": source_text[:300],
                    "source_location": result.get("source_location")
                    or "Metadata only",
                    "claim_findings": [
                        {
                            "claim_id": claim["claim_id"],
                            "impact": impact,
                            "rationale": (
                                "This source does not directly resolve the atomic claim."
                            ),
                            "revised_statement": None,
                        }
                        for claim in claims
                        if claim.get("claim_id")
                    ],
                }
            )
        if "research-counter-analysis" in system:
            results = payload.get("counter_evidence_results", [])
            claims = payload.get("gap_claims", [])
            claim_ids = [item["claim_id"] for item in claims if item.get("claim_id")]
            result_keys = [
                item["result_key"] for item in results if item.get("result_key")
            ]
            return json.dumps(
                {
                    "outcome": "no_direct_counter_evidence",
                    "statement": payload.get("provisional_gap_candidate")
                    or "The available sources support a testable Gap Candidate.",
                    "assessment": (
                        "The top counter-evidence results were reviewed, but none directly "
                        "resolved the source-grounded limitation. This does not prove novelty."
                    ),
                    "covered_result_keys": result_keys,
                    "findings": [
                        {
                            "result_key": item["result_key"],
                            "claim_ids": claim_ids,
                            "impact": (
                                "no_direct_counter_evidence"
                                if item.get("source_text")
                                else "inconclusive"
                            ),
                            "relevance_status": (
                                "relevant"
                                if item.get("source_text")
                                else "uncertain"
                            ),
                            "rationale": (
                                "The supplied source content does not directly resolve the "
                                "provisional limitation."
                            ),
                            "supporting_passage": str(item.get("source_text") or "")[
                                :300
                            ],
                            "source_location": item.get("source_location")
                            or "Metadata only",
                        }
                        for item in results
                        if item.get("result_key")
                    ],
                    "claim_assessments": [
                        {
                            "claim_id": claim_id,
                            "outcome": "no_direct_counter_evidence",
                            "assessment": (
                                "The grounded counter-evidence does not directly resolve "
                                "this atomic claim."
                            ),
                            "revised_statement": None,
                            "counter_evidence_result_keys": result_keys,
                        }
                        for claim_id in claim_ids
                    ],
                }
            )
        if "research-inputs" in system:
            return json.dumps(
                {
                    "keywords": ["claim verification", "prompt optimization"],
                    "preferred_sources": {
                        "peer_reviewed_papers": True,
                        "official_proceedings": True,
                        "author_materials": True,
                        "sourced_surveys": True,
                    },
                }
            )
        return "{}"

    async def complete_structured[T](
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        model: str | None = None,
    ) -> T:
        response = await self.complete(system=system, prompt=prompt, model=model)
        return TypeAdapter(schema).validate_json(response)


def _load_payload(prompt: str) -> dict[str, Any]:
    try:
        value = json.loads(prompt)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
