"""FIT@HCMUS WebUI OpenAI-compatible chat-completions adapter."""

from typing import Any

import httpx

from app.ports.llm import LlmProviderError


class FitWebUiLlmPort:
    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        base_url: str = "https://ai-fit.hcmus.edu.vn/openai",
        timeout_seconds: float = 300.0,
        max_tokens: int = 2_000,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A FIT WebUI API key is required")
        self._api_key = api_key
        self._default_model = default_model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_tokens = max_tokens

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        model: str | None = None,
    ) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model or self._default_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": self._max_tokens,
                        "stream": False,
                    },
                )
        except httpx.TimeoutException as exc:
            raise LlmProviderError(
                "FIT WebUI request timed out; retry later",
                provider="fit_webui",
                code="timeout",
            ) from exc
        except httpx.RequestError as exc:
            raise LlmProviderError(
                "FIT WebUI could not be reached",
                provider="fit_webui",
                code="connection_error",
            ) from exc
        _raise_for_status(response)
        return _response_text(response.json())


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code: str | None = None
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict) and error.get("code"):
                code = str(error["code"])
        except (TypeError, ValueError):
            pass

        if response.status_code in {401, 403}:
            message = "FIT WebUI rejected the configured API key"
        elif response.status_code == 429:
            message = "FIT WebUI quota or rate limit was reached"
        elif response.status_code >= 500:
            message = "FIT WebUI is temporarily unavailable"
        else:
            message = "FIT WebUI rejected the generation request"
        raise LlmProviderError(
            message,
            provider="fit_webui",
            status_code=response.status_code,
            code=code,
        ) from exc


def _response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message", {})
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"]).strip()
    raise ValueError("FIT WebUI response did not contain output text")
