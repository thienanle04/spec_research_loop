"""Idea generate user prompt must fit the vendor context window."""

from app.modules.idea.prompts import user_prompt
from app.modules.loop.catalog import WorkflowNode

# Vendor: 65536 context, 2000 completion → ~63536 input tokens. ~4 chars/token.
_INPUT_CHAR_BUDGET = 63_000 * 4
_DUMP = "RELATED_WORK_ABSTRACT_SHOULD_NOT_REACH_MODEL " * 8_000


def _fat_idea_context() -> dict:
    return {
        "node": WorkflowNode.IDEA_INTERPRETATION.value,
        "projected": {},
        "upstream": {
            WorkflowNode.IDEA_INTERPRETATION.value: {
                "narrative": {
                    "frame": {
                        "intent": "confirmed intent",
                        "problem": "confirmed problem",
                        "research_question": "confirmed rq",
                    }
                },
                "card_snapshot": [],
                "projected": {},
            },
            WorkflowNode.RELATED_WORK.value: {
                "narrative": {},
                "card_snapshot": [],
                "projected": {
                    "citations": [
                        {
                            "id": "cite-1",
                            "title": "Paper",
                            "abstract": _DUMP,
                            "text_object_key": "s3://blob",
                        }
                    ]
                },
            }
        },
        "working_draft": {
            "node": WorkflowNode.IDEA_INTERPRETATION.value,
            "narrative": {
                "turns": [{"role": "account", "text": "short idea"}],
                "frame": {
                    "intent": "i",
                    "problem": "p",
                    "research_question": "rq",
                },
            },
            "card_snapshot": [],
        },
        "valid_spec_version": {"id": "spec-1", "document": {"nodes": {}}},
    }


def test_idea_user_prompt_drops_related_work_dumps_and_fits_context_window() -> None:
    prompt = user_prompt(context=_fat_idea_context(), message="hello")
    assert "RELATED_WORK_ABSTRACT_SHOULD_NOT_REACH_MODEL" not in prompt
    assert "text_object_key" not in prompt
    assert "valid_spec_version" not in prompt
    assert "short idea" in prompt
    assert "confirmed intent" in prompt
    assert len(prompt) < _INPUT_CHAR_BUDGET
