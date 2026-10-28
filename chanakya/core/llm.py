"""Thin OpenAI-compatible chat client with model roles. Tests inject ``chanakya.core.fakes.FakeLLM``."""

import asyncio
import json
import logging
import re
from typing import Any, Protocol, runtime_checkable

import httpx

from .config import Role, Settings

logger = logging.getLogger(__name__)
Message = dict[str, str]


class LLMError(RuntimeError):
    """A model call failed; the message never contains request bodies or credentials."""


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self, role: Role, messages: list[Message], *, json_mode: bool = False,
        temperature: float = 0.0, seed: int | None = None, max_tokens: int = 800,
    ) -> str: ...


def parse_json(text: str) -> dict[str, Any]:
    """Parse a model's JSON reply, tolerating a surrounding code fence."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise LLMError("Model did not return JSON") from None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            raise LLMError("Model did not return valid JSON") from None
    if not isinstance(value, dict):
        raise LLMError("Model JSON must be an object")
    return value


async def complete_json(client: LLMClient, role: Role, messages: list[Message], **kwargs) -> dict[str, Any]:
    """Ask ``client`` for a JSON object and parse it."""
    return parse_json(await client.complete(role, messages, json_mode=True, **kwargs))


def retry_delay(response: httpx.Response, attempt: int, cap: float = 20.0) -> float:
    """Seconds to wait before retrying: the provider's Retry-After when given, else exponential backoff."""
    try:
        return min(cap, max(0.0, float(response.headers.get("retry-after", ""))))
    except ValueError:
        return 0.5 * 2 ** attempt


class OpenAICompatibleLLM:
    """Calls ``/chat/completions`` on OpenRouter or Groq, chosen by ``Settings``."""

    def __init__(self, settings: Settings | None = None, http_client: httpx.AsyncClient | None = None):
        self.settings = settings or Settings.from_env()
        self._client = http_client
        self._owns_client = http_client is None

    def _http(self) -> httpx.AsyncClient:
        if not self.settings.llm_api_key:
            raise LLMError(f"Missing API key for LLM provider {self.settings.llm_provider}")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.llm_base_url,
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                timeout=self.settings.llm_timeout_seconds,
            )
        return self._client

    async def complete(
        self, role: Role, messages: list[Message], *, json_mode: bool = False,
        temperature: float = 0.0, seed: int | None = None, max_tokens: int = 800,
    ) -> str:
        """Return the assistant text for ``messages`` using the model configured for ``role``."""
        choice = self.settings.models[role]
        body: dict[str, Any] = {
            "model": choice.model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, **choice.extra,
        }
        if seed is not None:
            body["seed"] = seed
        if json_mode:
            body["response_format"] = {"type": "json_object"}
            # Groq rejects JSON mode unless the prompt itself mentions JSON.
            if not any("json" in message.get("content", "").lower() for message in messages):
                body["messages"] = [*messages, {"role": "system", "content": "Respond with one JSON object."}]
        client = self._http()
        for attempt in range(3):
            try:
                response = await client.post("chat/completions", json=body)
                if response.status_code in {429, 500, 502, 503} and attempt < 2:
                    await asyncio.sleep(retry_delay(response, attempt))
                    continue
                response.raise_for_status()
                content = response.json()["choices"][0]["message"].get("content") or ""
                return content.strip()
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
                if attempt == 2 or not isinstance(error, httpx.TransportError):
                    raise LLMError(f"LLM request failed for role {role} ({type(error).__name__})") from None
                await asyncio.sleep(0.5 * 2 ** attempt)
        raise LLMError(f"LLM request failed for role {role}")

    async def aclose(self) -> None:
        """Close the HTTP client if this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
