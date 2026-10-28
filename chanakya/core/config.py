"""Settings read from the environment. Every feature flag defaults to off until integrated."""

import os
from typing import Any, Literal

from pydantic import Field

from .schemas import Contract

Role = Literal["main", "rollout", "twin_a", "twin_b", "judge"]
ROLES: tuple[Role, ...] = ("main", "rollout", "twin_a", "twin_b", "judge")


class ModelChoice(Contract):
    """A model for one role plus provider-specific request fields."""

    model: str
    extra: dict[str, Any] = Field(default_factory=dict)


# Twin-B uses a different model family from Twin-A so the planner cannot game its own simulator.
PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "models": {
            "main": ModelChoice(model="openai/gpt-6-luna", extra={"reasoning_effort": "none"}),
            "rollout": ModelChoice(model="deepseek/deepseek-v4-flash", extra={"reasoning": {"enabled": False}}),
            "twin_a": ModelChoice(model="deepseek/deepseek-v4-flash", extra={"reasoning": {"enabled": False}}),
            "twin_b": ModelChoice(model="openai/gpt-6-luna", extra={"reasoning_effort": "none"}),
            "judge": ModelChoice(model="openai/gpt-6-luna", extra={"reasoning_effort": "none"}),
        },
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "models": {
            "main": ModelChoice(model="openai/gpt-oss-120b", extra={"reasoning_effort": "low"}),
            "rollout": ModelChoice(model="openai/gpt-oss-20b", extra={"reasoning_effort": "low"}),
            "twin_a": ModelChoice(model="openai/gpt-oss-20b", extra={"reasoning_effort": "low"}),
            "twin_b": ModelChoice(model="qwen/qwen3.8-27b", extra={"reasoning_effort": "none"}),
            "judge": ModelChoice(model="openai/gpt-oss-120b", extra={"reasoning_effort": "low"}),
        },
    },
}


def _flag(name: str, environ) -> bool:
    return environ.get(name, "false").strip().lower() in {"1", "true", "yes", "on"}


class Settings(Contract):
    """Feature flags and LLM provider settings."""

    planner_enabled: bool = False
    actions_enabled: bool = False
    missions_enabled: bool = False
    coach_enabled: bool = False
    llm_provider: Literal["openrouter", "groq"] = "openrouter"
    llm_base_url: str = PROVIDERS["openrouter"]["base_url"]
    llm_api_key: str = ""
    llm_timeout_seconds: float = 20.0
    models: dict[str, ModelChoice] = Field(default_factory=dict)

    def __repr__(self) -> str:  # Keep the API key out of logs and tracebacks.
        return f"Settings(provider={self.llm_provider!r}, planner={self.planner_enabled})"

    __str__ = __repr__

    @classmethod
    def from_env(cls, environ=None) -> "Settings":
        """Build settings from ``environ`` (defaults to ``os.environ``).

        ``LLM_PROVIDER`` picks ``openrouter`` or ``groq``; without it, OpenRouter is used when its key
        is set, otherwise Groq when its key is set. ``LLM_MODEL_<ROLE>`` overrides a role's model.
        """
        environ = os.environ if environ is None else environ
        provider = environ.get("LLM_PROVIDER", "").strip().lower()
        if not provider:
            provider = "groq" if not environ.get("OPENROUTER_API_KEY", "").strip() and environ.get(
                "GROQ_API_KEY", "").strip() else "openrouter"
        if provider not in PROVIDERS:
            raise ValueError("LLM_PROVIDER must be 'openrouter' or 'groq'")
        preset = PROVIDERS[provider]
        models = {}
        for role in ROLES:
            choice = preset["models"][role]
            override = environ.get(f"LLM_MODEL_{role.upper()}", "").strip()
            models[role] = ModelChoice(model=override, extra={}) if override else choice
        return cls(
            planner_enabled=_flag("PLANNER_ENABLED", environ),
            actions_enabled=_flag("ACTIONS_ENABLED", environ),
            missions_enabled=_flag("MISSIONS_ENABLED", environ),
            coach_enabled=_flag("COACH_ENABLED", environ),
            llm_provider=provider,
            llm_base_url=environ.get("LLM_BASE_URL", "").strip() or preset["base_url"],
            llm_api_key=environ.get(preset["key_env"], "").strip(),
            llm_timeout_seconds=float(environ.get("LLM_TIMEOUT_SECONDS", "20")),
            models=models,
        )
