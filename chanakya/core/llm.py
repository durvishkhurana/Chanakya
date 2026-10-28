"""Thin LLM client with model roles. All model calls go through here so tests can fake them."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

import httpx

from chanakya.core.config import Settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


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
                       temperature: float = 0.4) -> str:
        """Return the model's text reply."""
        ...


def reasoning_options(model: str) -> dict:
    """Per-family settings measured on 2026-10-29: reasoning off keeps short answers correct and fast."""
    if model.startswith("deepseek/"):
        return {"reasoning": {"enabled": False}}
    if model.startswith("openai/"):
        return {"reasoning": {"effort": "none"}}
    return {}


class OpenRouterLLM:
    """OpenRouter chat completions, one model per role."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, timeout: float = 20.0):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def complete(self, role: Role, messages: Sequence[Message], *, max_tokens: int = 300,
                       temperature: float = 0.4) -> str:
        """Call the role's model and return the reply text."""
        model = self.settings.models[Role(role).value]
        body = {"model": model, "messages": list(messages), "max_tokens": max_tokens,
                "temperature": temperature, **reasoning_options(model)}
        response = await self.client.post(
            OPENROUTER_URL, json=body,
            headers={"Authorization": f"Bearer {self.settings.openrouter_api_key}"},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content") or ""
        return content.strip()

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


class FakeLLM:
    """Deterministic stand-in: a fixed reply per role, or a function of the messages."""

    def __init__(self, replies: dict[Role, str] | Callable[[Role, Sequence[Message]], str] | None = None):
        self.replies = replies or {}
        self.calls: list[tuple[Role, list[Message]]] = []

    async def complete(self, role: Role, messages: Sequence[Message], *, max_tokens: int = 300,
                       temperature: float = 0.4) -> str:
        """Record the call and return the scripted reply."""
        self.calls.append((Role(role), list(messages)))
        if callable(self.replies):
            return self.replies(Role(role), messages)
        return self.replies.get(Role(role), "")
