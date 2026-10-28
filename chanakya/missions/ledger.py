"""Mission store on SQLite (append-only events) and the mission API on top of it."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from pydantic import BaseModel

from chanakya.core.events import InProcessEventBus
from chanakya.core.interfaces import EventBus
from chanakya.core.schemas import (
    TERMINAL_STATES,
    ActionDecision,
    EventKind,
    Mission,
    MissionCard,
    MissionEvent,
    MissionState,
    Turn,
    utcnow,
)
from chanakya.missions.state import check_transition

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY, data TEXT NOT NULL, state TEXT NOT NULL, merchant_id TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mission_events (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL,
    payload TEXT NOT NULL, at TEXT NOT NULL, UNIQUE (mission_id, seq)
);
CREATE INDEX IF NOT EXISTS mission_events_order ON mission_events (at, mission_id, seq);
"""


class SQLiteMissionStore:
    """MissionStore on SQLite. Events are only ever inserted, never updated or deleted."""

    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def create(self, mission: Mission) -> Mission:
        """Persist a new mission."""
        with self._lock, self.conn:
            self.conn.execute("INSERT INTO missions VALUES (?, ?, ?, ?, ?)", self._row(mission))
        return mission

    def get(self, mission_id: str) -> Mission | None:
        """Current state of one mission."""
        row = self.conn.execute("SELECT data FROM missions WHERE id = ?", (mission_id,)).fetchone()
        return Mission.model_validate_json(row[0]) if row else None

    def list(self, states: set[MissionState] | None = None) -> list[Mission]:
        """Missions, newest update first, optionally filtered by state."""
        rows = self.conn.execute("SELECT data FROM missions ORDER BY updated_at DESC").fetchall()
        missions = [Mission.model_validate_json(row[0]) for row in rows]
        return [m for m in missions if states is None or m.state in states]

    def save(self, mission: Mission) -> Mission:
        """Overwrite a mission's card, state or outcome."""
        mission = mission.model_copy(update={"updated_at": utcnow()})
        with self._lock, self.conn:
            self.conn.execute("REPLACE INTO missions VALUES (?, ?, ?, ?, ?)", self._row(mission))
        return mission

    def append(self, event: MissionEvent) -> MissionEvent:
        """Insert an event with the next sequence number for its mission."""
        with self._lock, self.conn:
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM mission_events WHERE mission_id = ?", (event.mission_id,)
            ).fetchone()[0]
            stored = event.model_copy(update={"seq": seq})
            self.conn.execute(
                "INSERT INTO mission_events VALUES (?, ?, ?, ?, ?, ?)",
                (stored.id, stored.mission_id, seq, stored.kind.value, json.dumps(stored.payload), stored.at.isoformat()),
            )
        return stored

    def events(self, mission_id: str | None = None, after_seq: int = 0) -> list[MissionEvent]:
        """Events in order, for one mission (after ``after_seq``) or all missions."""
        if mission_id is None:
            rows = self.conn.execute("SELECT * FROM mission_events ORDER BY at, rowid").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? AND seq > ? ORDER BY seq", (mission_id, after_seq)
            ).fetchall()
        return [
            MissionEvent(id=r[0], mission_id=r[1], seq=r[2], kind=r[3], payload=json.loads(r[4]), at=r[5])
            for r in rows
        ]

    @staticmethod
    def _row(mission: Mission) -> tuple:
        return (mission.id, mission.model_dump_json(), mission.state.value, mission.card.merchant_id,
                mission.updated_at.isoformat())


class MissionLedger:
    """Mission API: every change is checked by the state machine and written to the ledger as an event."""

    def __init__(self, store: SQLiteMissionStore, bus: EventBus | None = None):
        self.store = store
        self.bus = bus or InProcessEventBus(store)

    async def record(self, mission_id: str, kind: EventKind, data: BaseModel | dict | None = None) -> MissionEvent:
        """Append any event to a mission's ledger and broadcast it."""
        return await self.bus.publish(MissionEvent.of(mission_id, kind, data))

    async def create(self, card: MissionCard) -> Mission:
        """Open a mission from a card."""
        mission = self.store.create(Mission(card=card))
        await self.record(mission.id, EventKind.MISSION_CREATED, {"card": card.model_dump(mode="json")})
        return mission

    async def update_card(self, mission_id: str, card: MissionCard, reason: str) -> Mission:
        """Replace a mission's card, for example when a repeated trigger refreshes it."""
        mission = self.store.save(self._get(mission_id).model_copy(update={"card": card}))
        await self.record(mission_id, EventKind.MISSION_UPDATED, {"card": card.model_dump(mode="json"), "reason": reason})
        return mission

    async def advance(self, mission_id: str, target: MissionState, reason: str = "", outcome: str | None = None) -> Mission:
        """Move a mission to ``target``; raises IllegalTransitionError when not allowed."""
        mission = self._get(mission_id)
        previous = mission.state
        check_transition(previous, target)
        update = {"state": target} | ({"outcome": outcome} if outcome is not None else {})
        mission = self.store.save(mission.model_copy(update=update))
        await self.record(mission_id, EventKind.STATE_CHANGED,
                          {"from": previous.value, "to": target.value, "reason": reason, "outcome": outcome})
        return mission

    async def attach_turn(self, mission_id: str, turn: Turn) -> MissionEvent:
        """Record one conversation turn."""
        return await self.record(mission_id, EventKind.TURN_COMPLETED, turn)

    async def attach_action(self, mission_id: str, decision: ActionDecision) -> MissionEvent:
        """Record one action decision (executed, blocked, failed or rejected)."""
        return await self.record(mission_id, EventKind.ACTION_DECISION, decision)

    async def close(self, mission_id: str, target: MissionState, outcome: str) -> Mission:
        """Move a mission to a terminal state with an outcome."""
        if target not in TERMINAL_STATES:
            raise ValueError(f"{target} is not a terminal state")
        return await self.advance(mission_id, target, reason="closed", outcome=outcome)

    def replay(self, mission_id: str) -> Mission:
        """Rebuild a mission from its events alone."""
        mission: Mission | None = None
        for event in self.store.events(mission_id):
            if event.kind == EventKind.MISSION_CREATED:
                mission = Mission(id=mission_id, card=MissionCard.model_validate(event.payload["card"]), created_at=event.at)
            elif mission is None:
                continue
            elif event.kind == EventKind.MISSION_UPDATED:
                mission = mission.model_copy(update={"card": MissionCard.model_validate(event.payload["card"])})
            elif event.kind == EventKind.STATE_CHANGED:
                update = {"state": MissionState(event.payload["to"]), "updated_at": event.at}
                if event.payload.get("outcome") is not None:
                    update["outcome"] = event.payload["outcome"]
                mission = mission.model_copy(update=update)
        if mission is None:
            raise LookupError(f"no events for mission {mission_id}")
        return mission

    def _get(self, mission_id: str) -> Mission:
        mission = self.store.get(mission_id)
        if mission is None:
            raise LookupError(f"unknown mission {mission_id}")
        return mission
