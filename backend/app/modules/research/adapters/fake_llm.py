"""Deterministic LLM port for research development and tests."""

import json
from typing import Any


class FakeLlmPort:
    """Return schema-shaped JSON without network access or an API key."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

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
        if "research-query" in system:
            inputs = payload.get("inputs", {})
            keywords = inputs.get("keywords") or ["related work"]
            query = " ".join(keywords[:4]).strip()
            return json.dumps({"queries": [query or "related work"]})
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


def _load_payload(prompt: str) -> dict[str, Any]:
    try:
        value = json.loads(prompt)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
