"""Settings from the environment. Every feature flag defaults to off."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODELS = {
    "main": "openai/gpt-6-luna",
    "rollout": "deepseek/deepseek-v4-flash",
    "twin_a": "deepseek/deepseek-v4-flash",
    # Twin-B must be a different model family from Twin-A (docs/IDEA.md 3.5).
    "twin_b": "openai/gpt-6-luna",
    "judge": "deepseek/deepseek-v4-flash",
}
# Used while OpenRouter credits are arranged; measured on Groq on 2026-10-29.
GROQ_MODELS = {
    "main": "openai/gpt-oss-120b",
    "rollout": "openai/gpt-oss-20b",
    "twin_a": "openai/gpt-oss-20b",
    "twin_b": "qwen/qwen3.8-27b",
    "judge": "openai/gpt-oss-120b",
}
# Which evidence scorer the belief tracker uses (task N1): keywords, an LLM call per turn, or the e5 embedding head.
WORRY_SCORERS = ("lexical", "llm", "embedding")
PLANNER_VALUES = ("formula", "network")
PLANNER_MEMORIES = ("forest", "neural")
PROVIDER_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _planner_value() -> str:
    """``PLANNER_VALUE`` if set, else ``formula`` (the planner's horizon guess, ``0.8 x consent_chance``)."""
    chosen = os.getenv("PLANNER_VALUE", "").strip().lower() or "formula"
    if chosen not in PLANNER_VALUES:
        raise ValueError(f"PLANNER_VALUE must be one of {', '.join(PLANNER_VALUES)}")
def _planner_memory() -> str:
    """``PLANNER_MEMORY`` if set, else ``forest`` (the Strategy Forest's trigram clusters)."""
    chosen = os.getenv("PLANNER_MEMORY", "").strip().lower() or "forest"
    if chosen not in PLANNER_MEMORIES:
        raise ValueError(f"PLANNER_MEMORY must be one of {', '.join(PLANNER_MEMORIES)}")
    return chosen


def _worry_scorer() -> str:
    """``WORRY_SCORER`` if set, else ``lexical``."""
    chosen = os.getenv("WORRY_SCORER", "").strip().lower() or "lexical"
    if chosen not in WORRY_SCORERS:
        raise ValueError(f"WORRY_SCORER must be one of {', '.join(WORRY_SCORERS)}")
    return chosen


def _provider() -> str:
    """``LLM_PROVIDER`` if set; otherwise OpenRouter, or Groq when only a Groq key is configured."""
    chosen = os.getenv("LLM_PROVIDER", "").strip().lower()
    if chosen:
        if chosen not in PROVIDER_URLS:
            raise ValueError("LLM_PROVIDER must be 'openrouter' or 'groq'")
        return chosen
    only_groq = os.getenv("GROQ_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip()
    return "groq" if only_groq else "openrouter"


@dataclass(frozen=True)
class Settings:
    planner_enabled: bool = False
    actions_enabled: bool = False
    missions_enabled: bool = False
    coach_enabled: bool = False
    winback_enabled: bool = False
    permission_first_enabled: bool = False
    db_path: Path = REPO_ROOT / ".state" / "chanakya.db"
    timezone: str = "Asia/Kolkata"
    calling_hours: tuple[int, int] = (9, 21)
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    openrouter_api_key: str = field(default="", repr=False)
    llm_provider: str = "openrouter"
    groq_api_key: str = field(default="", repr=False)
    worry_scorer: str = "lexical"
    planner_value: str = "formula"
    approval_tools: tuple[str, ...] = ()  # write tools that wait for a person's approval (B10); empty means none
    approval_timeout_minutes: int = 30
    planner_memory: str = "forest"

    @property
    def llm_base_url(self) -> str:
        """Base URL of the configured OpenAI-compatible provider."""
        return PROVIDER_URLS[self.llm_provider]

    @property
    def llm_api_key(self) -> str:
        """API key for the configured provider."""
        return self.groq_api_key if self.llm_provider == "groq" else self.openrouter_api_key

    @classmethod
    def from_env(cls) -> Settings:
        """Read settings from environment variables."""
        provider = _provider()
        defaults = GROQ_MODELS if provider == "groq" else DEFAULT_MODELS
        models = {role: os.getenv(f"MODEL_{role.upper()}", model) for role, model in defaults.items()}
        start, end = (int(part) for part in os.getenv("CALLING_HOURS", "9-21").split("-"))
        return cls(
            planner_enabled=_flag("PLANNER_ENABLED"),
            actions_enabled=_flag("ACTIONS_ENABLED"),
            missions_enabled=_flag("MISSIONS_ENABLED"),
            coach_enabled=_flag("COACH_ENABLED"),
            winback_enabled=_flag("WINBACK_ENABLED"),
            permission_first_enabled=_flag("PERMISSION_FIRST_ENABLED"),
            db_path=Path(os.getenv("CHANAKYA_DB_PATH", str(REPO_ROOT / ".state" / "chanakya.db"))),
            timezone=os.getenv("CHANAKYA_TIMEZONE", "Asia/Kolkata"),
            calling_hours=(start, end),
            models=models,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            llm_provider=provider,
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            worry_scorer=_worry_scorer(),
            planner_value=_planner_value(),
            approval_tools=tuple(t.strip() for t in os.getenv("APPROVAL_TOOLS", "").split(",") if t.strip()),
            approval_timeout_minutes=int(os.getenv("APPROVAL_TIMEOUT_MINUTES", "30")),
            planner_memory=_planner_memory(),
        )
