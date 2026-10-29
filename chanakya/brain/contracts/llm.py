"""Track A helpers over the core LLM client: JSON replies and one error type that never leaks request data."""

import json
import re
from typing import Any

import httpx

from chanakya.core.config import Settings
from chanakya.core.llm import LLM as LLMClient
from chanakya.core.llm import Message, OpenRouterLLM

__all__ = ["LLMClient", "LLMError", "Message", "complete_json", "default_llm", "parse_json"]


class LLMError(RuntimeError):
    """A model call failed; the message never contains request bodies or credentials."""


def parse_json(text: str) -> dict[str, Any]:
    """Parse a model's JSON reply, tolerating a surrounding code fence or chatter."""
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


async def complete_json(client, role, messages: list[Message], **kwargs) -> dict[str, Any]:
    """Ask ``client`` (any core ``LLM``) for one JSON object and parse it."""
    try:
        text = await client.complete(role, messages, json_mode=True, **kwargs)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
        raise LLMError(f"LLM request failed for role {role} ({type(error).__name__})") from None
    return parse_json(text)


def default_llm(settings: Settings | None = None) -> OpenRouterLLM:
    """The core client for the configured provider (OpenRouter, or Groq while OpenRouter is unavailable)."""
    return OpenRouterLLM(settings or Settings.from_env())
