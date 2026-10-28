"""Audit trail of action decisions, read back from the mission ledger."""

from __future__ import annotations

from chanakya.core.interfaces import MissionStore
from chanakya.core.schemas import ActionDecision, EventKind


def audit_trail(store: MissionStore, mission_id: str) -> list[ActionDecision]:
    """Every attempted, blocked, failed and executed action for a mission, in order."""
    return [
        ActionDecision.model_validate(event.payload)
        for event in store.events(mission_id)
        if event.kind == EventKind.ACTION_DECISION
    ]
