"""Thin LLM client with model roles. All model calls go through here so tests can fake them."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

import httpx

from chanakya.core.config import PROVIDER_URLS, Settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUSES = {429, 500, 502, 503}


class Role(StrEnum):
    MAIN = "main"
    ROLLOUT = "rollout"
    TWIN_A = "twin_a"
    TWIN_B = "twin_b"
    JUDGE = "judge"


Message = dict[str, str]


@runtime_checkable
class LLM(Protocol):
    async def complete(self, role: Role, messages: Sequence[Message], *, max_tokens: int = 300,
                       temperature: float = 0.4, json_mode: bool = False, seed: int | None = None) -> str:
        """Return the model's text reply. ``json_mode`` asks for one JSON object."""
        ...


def reasoning_options(model: str, provider: str = "openrouter") -> dict:
    """Per-family settings measured on 2026-10-29: reasoning off keeps short answers correct and fast."""
    if provider == "groq":
        # Groq's gpt-oss models cannot turn reasoning off; "low" is the fastest. Qwen supports "none".
        if model.startswith("openai/gpt-oss"):
            return {"reasoning_effort": "low"}
        if model.startswith("qwen/"):
            return {"reasoning_effort": "none"}
        return {}
    if model.startswith("deepseek/"):
        return {"reasoning": {"enabled": False}}
    if model.startswith("openai/"):
        return {"reasoning": {"effort": "none"}}
    return {}


def retry_delay(response: httpx.Response, attempt: int, cap: float = 20.0) -> float:
    """Seconds before retrying: the provider's Retry-After when given, else exponential backoff."""
    try:
        return min(cap, max(0.0, float(response.headers.get("retry-after", ""))))
    except ValueError:
        return 0.5 * 2 ** attempt


class OpenRouterLLM:
    """Chat completions on the configured OpenAI-compatible provider (OpenRouter, or Groq), one model per role."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, timeout: float = 20.0,
                 retries: int = 2):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.retries = retries

    @property
    def url(self) -> str:
        """The chat-completions endpoint of the configured provider."""
        if self.settings.llm_provider == "openrouter":
            return OPENROUTER_URL
        return PROVIDER_URLS[self.settings.llm_provider] + "/chat/completions"

    async def complete(self, role: Role, messages: Sequence[Message], *, max_tokens: int = 300,
                       temperature: float = 0.4, json_mode: bool = False, seed: int | None = None) -> str:
        """Call the role's model and return the reply text; rate limits are retried after the hinted delay."""
        model = self.settings.models[Role(role).value]
        messages = list(messages)
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                **reasoning_options(model, self.settings.llm_provider)}
        if seed is not None:
            body["seed"] = seed
        if json_mode:
            body["response_format"] = {"type": "json_object"}
            # Groq rejects JSON mode unless the prompt itself mentions JSON.
            if not any("json" in message.get("content", "").lower() for message in messages):
                body["messages"] = [*messages, {"role": "system", "content": "Respond with one JSON object."}]
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        for attempt in range(self.retries + 1):
            response = await self.client.post(self.url, json=body, headers=headers)
            if response.status_code in RETRY_STATUSES and attempt < self.retries:
                await asyncio.sleep(retry_delay(response, attempt))
                continue
            response.raise_for_status()
            content = response.json()["choices"][0]["message"].get("content") or ""
            return content.strip()
        raise RuntimeError("unreachable")

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


class FakeLLM:
    """Deterministic stand-in: a fixed reply per role, or a function of the messages."""

    def __init__(self, replies: dict[Role, str] | Callable[[Role, Sequence[Message]], str] | None = None):
        self.replies = replies or {}
        self.calls: list[tuple[Role, list[Message]]] = []

    async def complete(self, role: Role, messages: Sequence[Message], *, max_tokens: int = 300,
                       temperature: float = 0.4, json_mode: bool = False, seed: int | None = None) -> str:
        """Record the call and return the scripted reply."""
        self.calls.append((Role(role), list(messages)))
        if callable(self.replies):
            return self.replies(Role(role), messages)
        return self.replies.get(Role(role), "")
