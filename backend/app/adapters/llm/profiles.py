"""LLM Provider / ModelRef / Profile composition (ADR 0034)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from app.adapters.llm.fake import FakeLlm
from app.adapters.llm.langchain_chat import DEFAULT_MAX_TOKENS, LangChainChatAdapter
from app.core.config import Settings
from app.modules.loop.catalog import WorkflowNode
from app.ports.llm import LlmPort

ProviderKind = Literal["langchain", "fake"]

DEFAULT_NODE_PROFILE_MAP: dict[str, str] = {
    WorkflowNode.IDEA_INTERPRETATION.value: "creative",
    WorkflowNode.IDEA_DECOMPOSITION.value: "creative",
    WorkflowNode.RESEARCH_INPUTS.value: "research",
    WorkflowNode.RELATED_WORK.value: "research",
    WorkflowNode.GAP.value: "research",
    WorkflowNode.CONTRIBUTION.value: "structured",
    WorkflowNode.CLAIMS.value: "structured",
    WorkflowNode.EVIDENCE.value: "structured",
    WorkflowNode.EXPERIMENT_PLAN.value: "structured",
    WorkflowNode.FEASIBILITY.value: "structured",
    WorkflowNode.GAP_JUDGE.value: "judge",
    WorkflowNode.CONTRIBUTION_JUDGE.value: "judge",
    WorkflowNode.EVIDENCE_JUDGE.value: "judge",
    WorkflowNode.EXPERIMENT_JUDGE.value: "judge",
    WorkflowNode.CONFERENCE_JUDGE.value: "judge",
    WorkflowNode.AGGREGATOR.value: "judge",
}


@dataclass(frozen=True)
class Provider:
    id: str
    kind: ProviderKind
    api_key_env: str | None = None
    base_url: str | None = None
    timeout_seconds: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class ModelRef:
    provider_id: str
    model: str


@dataclass(frozen=True)
class Profile:
    name: str
    model_ref: ModelRef


def _parse_json_object(raw: str, *, field: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{field} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{field} must be a JSON object")
    return value


def _provider_from_dict(provider_id: str, raw: dict[str, Any]) -> Provider:
    kind = str(raw.get("kind", "")).casefold()
    if kind not in {"langchain", "fake"}:
        raise RuntimeError(f"Unsupported LLM provider kind for {provider_id!r}: {kind!r}")
    return Provider(
        id=provider_id,
        kind=kind,  # type: ignore[arg-type]
        api_key_env=raw.get("api_key_env"),
        base_url=raw.get("base_url"),
        timeout_seconds=float(raw["timeout_seconds"])
        if raw.get("timeout_seconds") is not None
        else None,
        max_tokens=int(raw["max_tokens"]) if raw.get("max_tokens") is not None else None,
    )


def _profile_from_dict(name: str, raw: dict[str, Any]) -> Profile:
    provider_id = raw.get("provider_id")
    model = raw.get("model")
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise RuntimeError(f"LLM profile {name!r} requires provider_id")
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError(f"LLM profile {name!r} requires model")
    return Profile(name=name, model_ref=ModelRef(provider_id=provider_id, model=model))


def default_providers(settings: Settings) -> dict[str, Provider]:
    return {
        "fake": Provider(id="fake", kind="fake"),
        "ai-fit": Provider(
            id="ai-fit",
            kind="langchain",
            api_key_env="LLM_API_KEY",
            base_url=settings.llm_base_url,
            max_tokens=DEFAULT_MAX_TOKENS,
        ),
    }


def default_profiles(settings: Settings) -> dict[str, Profile]:
    model = settings.llm_default_model or "Qwen3.6-27B"
    shared = ModelRef(provider_id="ai-fit", model=model)
    return {
        "creative": Profile(name="creative", model_ref=shared),
        "research": Profile(name="research", model_ref=shared),
        "structured": Profile(name="structured", model_ref=shared),
        "judge": Profile(name="judge", model_ref=shared),
    }


def load_providers(settings: Settings) -> dict[str, Provider]:
    raw = _parse_json_object(settings.llm_providers, field="LLM_PROVIDERS")
    if not raw:
        return default_providers(settings)
    return {
        provider_id: _provider_from_dict(provider_id, body)
        for provider_id, body in raw.items()
        if isinstance(body, dict)
    }


def load_profiles(settings: Settings) -> dict[str, Profile]:
    raw = _parse_json_object(settings.llm_profiles, field="LLM_PROFILES")
    if not raw:
        return default_profiles(settings)
    return {
        name: _profile_from_dict(name, body)
        for name, body in raw.items()
        if isinstance(body, dict)
    }


def node_profile_map(settings: Settings) -> dict[str, str]:
    mapping = dict(DEFAULT_NODE_PROFILE_MAP)
    overrides = _parse_json_object(
        settings.llm_node_profile_overrides, field="LLM_NODE_PROFILE_OVERRIDES"
    )
    for node, profile in overrides.items():
        if not isinstance(profile, str) or not profile.strip():
            raise RuntimeError(
                f"LLM_NODE_PROFILE_OVERRIDES[{node!r}] must be a profile name"
            )
        mapping[str(node)] = profile.strip()
    return mapping


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is not None and value.strip():
        return value.strip()
    return None


def _api_key(provider: Provider, settings: Settings) -> str | None:
    if not provider.api_key_env:
        return None
    value = _env_value(provider.api_key_env)
    if value:
        return value
    # Settings may hold LLM_API_KEY when load_dotenv did not run yet / tests patch Settings.
    if provider.api_key_env == "LLM_API_KEY" and settings.llm_api_key:
        return settings.llm_api_key.strip()
    return None


def _base_url(provider: Provider, settings: Settings) -> str | None:
    raw = provider.base_url
    if not raw:
        return settings.llm_base_url
    # Literal URL.
    if "://" in raw:
        return raw
    # Env var name (common mistake/convenience: "base_url":"LLM_BASE_URL").
    resolved = _env_value(raw)
    if resolved:
        return resolved
    if raw == "LLM_BASE_URL" and settings.llm_base_url:
        return settings.llm_base_url
    return None


def build_port_for_profile(
    profile: Profile,
    *,
    providers: dict[str, Provider],
    settings: Settings,
) -> LlmPort:
    try:
        provider = providers[profile.model_ref.provider_id]
    except KeyError as exc:
        raise RuntimeError(
            f"LLM profile {profile.name!r} references unknown provider "
            f"{profile.model_ref.provider_id!r}"
        ) from exc
    model = profile.model_ref.model
    if provider.kind == "fake":
        return FakeLlm(response="fake-completion")
    if provider.kind == "langchain":
        return LangChainChatAdapter(
            api_key=_api_key(provider, settings),
            api_key_env=provider.api_key_env or "LLM_API_KEY",
            base_url=_base_url(provider, settings),
            default_model=model,
            max_tokens=provider.max_tokens,
        )
    raise RuntimeError(f"Unsupported provider kind: {provider.kind}")


def build_llm_ports(settings: Settings) -> dict[str, LlmPort]:
    providers = load_providers(settings)
    profiles = load_profiles(settings)
    mapping = node_profile_map(settings)
    ports: dict[str, LlmPort] = {}
    cache: dict[tuple[object, ...], LlmPort] = {}
    for node, profile_name in mapping.items():
        if profile_name not in profiles:
            raise RuntimeError(
                f"No LLM profile {profile_name!r} for workflow node {node!r}"
            )
        profile = profiles[profile_name]
        try:
            provider = providers[profile.model_ref.provider_id]
        except KeyError as exc:
            raise RuntimeError(
                f"LLM profile {profile.name!r} references unknown provider "
                f"{profile.model_ref.provider_id!r}"
            ) from exc
        cache_key = (
            provider.kind,
            provider.id,
            provider.api_key_env,
            provider.base_url,
            provider.timeout_seconds,
            provider.max_tokens,
            profile.model_ref.model,
        )
        if cache_key not in cache:
            cache[cache_key] = build_port_for_profile(
                profile,
                providers=providers,
                settings=settings,
            )
        ports[node] = cache[cache_key]
    return ports
