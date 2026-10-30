"""One SQLite database holding every mock system, plus failure injection."""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, business_type TEXT NOT NULL, city TEXT NOT NULL,
    language TEXT NOT NULL, start_hour INTEGER NOT NULL, end_hour INTEGER NOT NULL,
    do_not_call INTEGER NOT NULL DEFAULT 0, has_soundbox INTEGER NOT NULL DEFAULT 0,
    has_card_machine INTEGER NOT NULL DEFAULT 0, phone_last4 TEXT,
    relationship TEXT NOT NULL DEFAULT 'customer', churned_at TEXT
);
CREATE TABLE IF NOT EXISTS callback_requests (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, product TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, product TEXT NOT NULL, stage TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, summary TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, channel TEXT NOT NULL,
    body TEXT NOT NULL, link TEXT, status TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS onboarding_sessions (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, product TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS field_visits (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, purpose TEXT NOT NULL,
    slot TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS callbacks (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, due_at TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
    last_payment_at TEXT, rental_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_orders (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, product TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, category TEXT NOT NULL,
    description TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, amount_inr INTEGER NOT NULL, status TEXT NOT NULL,
    expected_on TEXT NOT NULL, note TEXT
);
"""
# Columns added after the first release; databases created before them get them on open.
MIGRATIONS = {
    "merchants": {"relationship": "TEXT NOT NULL DEFAULT 'customer'", "churned_at": "TEXT"},
}


class MockSystemError(RuntimeError):
    """A simulated outage or timeout in a mock system."""


@dataclass
class FailurePolicy:
    """Chance that a call to a system fails, and an optional delay; seeded for reproducibility."""

    rate: float = 0.0
    delay_ms: int = 0


def now_iso() -> str:
    """Current UTC time as an ISO string."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class MockDB:
    """Connection plus per-system failure policies shared by every mock system."""

    def __init__(self, path: str | Path = ":memory:", seed: int = 0,
                 failures: dict[str, FailurePolicy] | None = None):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()  # the connection is shared across threads; see SQLiteMissionStore.lock
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.failures = failures or {}
        self.random = random.Random(seed)

    def _migrate(self) -> None:
        with self.conn:
            for table, columns in MIGRATIONS.items():
                existing = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}  # names from a fixed map
                for column, spec in columns.items():
                    if column not in existing:
                        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")

    def maybe_fail(self, system: str) -> None:
        """Apply the system's delay, then raise MockSystemError with its configured probability."""
        policy = self.failures.get(system)
        if policy is None:
            return
        if policy.delay_ms:
            time.sleep(policy.delay_ms / 1000)
        if self.random.random() < policy.rate:
            raise MockSystemError(f"mock {system} system is unavailable")

    def one(self, sql: str, *args) -> dict | None:
        """First row as a dict, or None."""
        with self.lock:
            row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, *args) -> list[dict]:
        """All rows as dicts."""
        with self.lock:
            return [dict(row) for row in self.conn.execute(sql, args).fetchall()]

    def write(self, sql: str, *args) -> None:
        """Execute and commit one statement."""
        with self.lock, self.conn:
            self.conn.execute(sql, args)
