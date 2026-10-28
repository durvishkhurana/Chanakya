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


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    planner_enabled: bool = False
    actions_enabled: bool = False
    missions_enabled: bool = False
    coach_enabled: bool = False
    db_path: Path = REPO_ROOT / ".state" / "chanakya.db"
    timezone: str = "Asia/Kolkata"
    calling_hours: tuple[int, int] = (9, 21)
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    openrouter_api_key: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        """Read settings from environment variables."""
        models = {role: os.getenv(f"MODEL_{role.upper()}", model) for role, model in DEFAULT_MODELS.items()}
        start, end = (int(part) for part in os.getenv("CALLING_HOURS", "9-21").split("-"))
        return cls(
            planner_enabled=_flag("PLANNER_ENABLED"),
            actions_enabled=_flag("ACTIONS_ENABLED"),
            missions_enabled=_flag("MISSIONS_ENABLED"),
            coach_enabled=_flag("COACH_ENABLED"),
            db_path=Path(os.getenv("CHANAKYA_DB_PATH", str(REPO_ROOT / ".state" / "chanakya.db"))),
            timezone=os.getenv("CHANAKYA_TIMEZONE", "Asia/Kolkata"),
            calling_hours=(start, end),
            models=models,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        )
