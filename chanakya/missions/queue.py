"""Priority queue of missions waiting for first contact."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from chanakya.core.config import Settings
from chanakya.core.schemas import EventKind, Mission, MissionState, SignalKind, utcnow
from chanakya.missions.ledger import MissionLedger

WAITING = {MissionState.CREATED, MissionState.SCHEDULED}


@dataclass(frozen=True)
class QueueEntry:
    mission: Mission
    ready: bool
    reason: str


class MissionQueue:
    """Ranks waiting missions by priority (chance of success x value) and checks they may be contacted now."""

    def __init__(self, ledger: MissionLedger, settings: Settings | None = None,
                 clock: Callable[[], datetime] = utcnow):
        self.ledger = ledger
        self.settings = settings or Settings()
        self.clock = clock

    def entries(self) -> list[QueueEntry]:
        """Waiting missions, highest priority first, each marked ready or not with the reason."""
        hour = self.clock().astimezone(ZoneInfo(self.settings.timezone)).hour
        start, end = self.settings.calling_hours
        entries = []
        for mission in self.ledger.store.list(WAITING):
            callback_at = self._callback_due(mission)
            if not start <= hour < end:
                entries.append(QueueEntry(mission, False, "outside calling hours"))
            elif callback_at is not None and callback_at > self.clock():
                entries.append(QueueEntry(mission, False, f"callback due at {callback_at.isoformat(timespec='minutes')}"))
            elif callback_at is not None:
                entries.append(QueueEntry(mission, True, "callback is due"))
            elif mission.card.signal_kind == SignalKind.CALLBACK_REQUEST:
                # The merchant asked for this call; their usual window does not apply.
                entries.append(QueueEntry(mission, True, "merchant asked for a callback"))
            elif mission.card.contact_window.contains(hour):
                entries.append(QueueEntry(mission, True, "inside the merchant's preferred window"))
            else:
                window = mission.card.contact_window
                entries.append(QueueEntry(mission, False, f"prefers {window.start_hour}:00-{window.end_hour}:00"))
        return sorted(entries, key=lambda e: (e.ready, e.mission.card.priority, -e.mission.created_at.timestamp()),
                      reverse=True)

    def _callback_due(self, mission: Mission) -> datetime | None:
        if mission.state != MissionState.SCHEDULED:
            return None
        callbacks = [e for e in self.ledger.store.events(mission.id)
                     if e.kind == EventKind.FOLLOWUP_SCHEDULED and e.payload.get("kind") == "callback"]
        return datetime.fromisoformat(callbacks[-1].payload["due_at"]) if callbacks else None

    def next_ready(self) -> Mission | None:
        """The highest-priority mission that may be contacted now, if any."""
        return next((e.mission for e in self.entries() if e.ready), None)
