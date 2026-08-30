"""Judgement dependency bindings kept local to the module."""

from app.adapters.llm import get_llm_port
from app.modules.judgement.schemas import JudgementNode
from app.ports.llm import LlmPort


def get_judgement_node_llm(node: JudgementNode) -> LlmPort:
    return get_llm_port(node.value)
