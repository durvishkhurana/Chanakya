"""Follow-up jobs on a clock that tests and demos can fast-forward."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from chanakya.core.schemas import EventKind, new_id, utcnow
from chanakya.missions.ledger import MissionLedger

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, kind TEXT NOT NULL, due_at TEXT NOT NULL,
    status TEXT NOT NULL, payload TEXT NOT NULL
);
"""


class SimClock:
    """A clock that only moves when told to. ``advance`` is the demo's fast-forward button."""

    def __init__(self, start: datetime | None = None):
        self._now = start or utcnow()

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        """Move time forward and return the new now."""
        self._now += delta
        return self._now


class RealClock:
    """Wall-clock time; ``advance`` adds an offset so demos can still fast-forward."""

    def __init__(self) -> None:
        self.offset = timedelta()

    def __call__(self) -> datetime:
        return utcnow() + self.offset

    def advance(self, delta: timedelta) -> datetime:
        """Shift this clock forward and return the new now."""
        self.offset += delta
        return self()


@dataclass(frozen=True)
class Job:
    id: str
    mission_id: str
    kind: str
    due_at: datetime
    status: str
    payload: dict[str, Any]


class Scheduler:
    """Pending jobs stored next to the ledger; scheduling is recorded as a mission event."""

    def __init__(self, ledger: MissionLedger, clock):
        self.ledger = ledger
        self.clock = clock
        self.conn = ledger.store.conn
        self.conn.executescript(SCHEMA)

    async def schedule(self, mission_id: str, kind: str, due_at: datetime, **payload: Any) -> Job:
        """Add a job and record a FOLLOWUP_SCHEDULED event."""
        due_at = due_at.astimezone(UTC)  # one timezone, so text order in SQLite is time order
        job = Job(new_id("job"), mission_id, kind, due_at, "pending", payload)
        with self.conn:
            self.conn.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
                              (job.id, mission_id, kind, due_at.isoformat(), "pending", json.dumps(payload)))
        await self.ledger.record(mission_id, EventKind.FOLLOWUP_SCHEDULED,
                                 {"job_id": job.id, "kind": kind, "due_at": due_at.isoformat(), **payload})
        return job

    def due(self) -> list[Job]:
        """Pending jobs whose time has come, oldest first."""
        return [j for j in self.pending() if j.due_at <= self.clock()]

    def pending(self, mission_id: str | None = None) -> list[Job]:
        """All pending jobs, optionally for one mission, oldest first."""
        rows = self.conn.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY due_at, rowid").fetchall()
        jobs = [Job(r[0], r[1], r[2], datetime.fromisoformat(r[3]), r[4], json.loads(r[5])) for r in rows]
        return [j for j in jobs if mission_id is None or j.mission_id == mission_id]

    def finish(self, job: Job, status: str = "done") -> None:
        """Mark a job done or cancelled."""
        with self.conn:
            self.conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job.id))

    def cancel_all(self, mission_id: str) -> None:
        """Cancel every pending job of a mission, for example once it is DONE."""
        with self.conn:
            self.conn.execute("UPDATE jobs SET status = 'cancelled' WHERE mission_id = ? AND status = 'pending'",
                              (mission_id,))

    def later(self, delta: timedelta) -> datetime:
        """Now plus ``delta`` on this scheduler's clock."""
        return self.clock() + delta
