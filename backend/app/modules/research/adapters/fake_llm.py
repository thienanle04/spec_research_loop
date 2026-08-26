"""Deterministic LLM port for research development and tests."""

import json
from collections.abc import AsyncIterator
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
    ) -> AsyncIterator[str]:
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
        if "research-gap-analysis" in system:
            citations = payload.get("citations", [])
            related_work = payload.get("related_work", [])
            keys = [item["citation_key"] for item in citations]
            counter_keys = payload.get("required_counter_evidence_keys", [])
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
                    "addressed_counter_evidence_keys": counter_keys,
                }
            )
        if "research-gap-synthesis" in system:
            return json.dumps(
                {
                    "statement": (
                        "Prior systems optimize outputs or prompts using aggregate "
                        "feedback, but it remains unclear whether claim-level evidence "
                        "feedback reduces unsupported claims under the same inference budget."
                    )
                }
            )
        if "research-counter-analysis" in system:
            results = payload.get("counter_evidence_results", [])
            return json.dumps(
                {
                    "outcome": "no_direct_counter_evidence",
                    "statement": payload.get("provisional_gap_candidate")
                    or "The available sources support a testable Gap Candidate.",
                    "assessment": (
                        "The top counter-evidence results were reviewed, but none directly "
                        "resolved the source-grounded limitation. This does not prove novelty."
                    ),
                    "covered_result_keys": [
                        item["result_key"] for item in results if item.get("result_key")
                    ],
                    "findings": [
                        {
                            "result_key": item["result_key"],
                            "impact": "no_direct_counter_evidence",
                            "rationale": (
                                "The supplied metadata does not directly resolve the "
                                "provisional limitation."
                            ),
                        }
                        for item in results
                        if item.get("result_key")
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
