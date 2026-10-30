"""Churn detection for win-back missions (behind WINBACK_ENABLED). Reads the mock systems; fictional data only.

A merchant counts as former when the CRM says so, a device was returned, or no device took a payment for over
60 days. Each eligible former merchant gets exactly one of:
- a win-back mission card (``MERCHANT_CHURNED`` through the data door), which the queue calls like any other;
- a hand-off card for a person, when they have an unresolved complaint ticket: they are owed an answer first;
- the holdout group: 20% of eligible merchants, picked by a seeded hash of the merchant id, are never called and
  the decision is written to the ledger, so the win-back rate can be compared with doing nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from chanakya.actions.systems.db import MockDB
from chanakya.core.schemas import Door, EventKind, MerchantSignal, MissionType, SignalKind
from chanakya.humans.handoff import HandoffQueue
from chanakya.missions.intake import MissionIntake
from chanakya.missions.ledger import MissionLedger

DEMO_SEED = 2027  # fixed so the demo always holds out the same merchant
HOLDOUT_SHARE = 20  # percent
CHURN_MIN = timedelta(days=14)
CHURN_MAX = timedelta(days=180)
IDLE_AFTER = timedelta(days=60)
RECENT_WINBACK = timedelta(days=90)
ACTIVE_DEVICE = frozenset({"online", "active"})


def holdout_mission_id(merchant_id: str) -> str:
    """Ledger key for a holdout decision; holdout merchants never get a mission."""
    return f"holdout_{merchant_id}"


def in_holdout(merchant_id: str, seed: int = DEMO_SEED, share: int = HOLDOUT_SHARE) -> bool:
    """Deterministic holdout pick: the same merchant and seed always land in the same group."""
    bucket = int(hashlib.sha256(f"{seed}:{merchant_id}".encode()).hexdigest()[:8], 16) % 100
    return bucket < share


@dataclass(frozen=True)
class ChurnDecision:
    merchant_id: str
    decision: str  # "call", "handoff", "holdout" or "skip"
    reason: str
    mission_id: str | None = None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ChurnDetector:
    """Finds former merchants in the mock tables and routes each one to a call, a person or the holdout."""

    def __init__(self, db: MockDB, ledger: MissionLedger, intake: MissionIntake, handoffs: HandoffQueue,
                 clock: Callable[[], datetime], seed: int = DEMO_SEED):
        self.db = db
        self.ledger = ledger
        self.intake = intake
        self.handoffs = handoffs
        self.clock = clock
        self.seed = seed

    def former(self) -> list[dict]:
        """Every merchant who stopped using the product, with when they stopped and which product it was."""
        now = self.clock()
        found = []
        for merchant in self.db.all("SELECT * FROM merchants ORDER BY id"):
            devices = self.db.all("SELECT * FROM devices WHERE merchant_id = ?", merchant["id"])
            returned = [d for d in devices if d["status"] == "returned"]
            payments = [p for p in (_parse(d["last_payment_at"]) for d in devices) if p is not None]
            idle = bool(payments) and now - max(payments) > IDLE_AFTER
            if merchant["relationship"] != "former" and not returned and not idle:
                continue
            churned_at = _parse(merchant["churned_at"]) or (max(payments) if payments else None)
            product = (returned or devices or [{"kind": "soundbox"}])[0]["kind"]
            found.append({"merchant": merchant, "churned_at": churned_at, "product": product})
        return found

    def _recent_winback(self, merchant_id: str) -> bool:
        now = self.clock()
        for mission in self.ledger.store.list():
            if (mission.card.merchant_id == merchant_id and mission.card.mission_type == MissionType.WIN_BACK
                    and now - mission.created_at <= RECENT_WINBACK):
                return True
        held = [e for e in self.ledger.store.events(holdout_mission_id(merchant_id))
                if e.kind == EventKind.HOLDOUT_ASSIGNED]
        return any(now - e.at <= RECENT_WINBACK for e in held)

    def _open_complaint(self, merchant_id: str) -> dict | None:
        return self.db.one("SELECT * FROM tickets WHERE merchant_id = ? AND status != 'resolved' "
                           "ORDER BY created_at LIMIT 1", merchant_id)

    def check(self, entry: dict) -> str | None:
        """Why this former merchant is not eligible right now, or None when they are."""
        merchant, churned_at = entry["merchant"], entry["churned_at"]
        if merchant["do_not_call"]:
            return "on do-not-call"
        if churned_at is None:
            return "no churn date"
        since = self.clock() - churned_at
        if since < CHURN_MIN:
            return "churned under 14 days ago"
        if since > CHURN_MAX:
            return "churned over 180 days ago"
        if self._recent_winback(merchant["id"]):
            return "win-back contact in the last 90 days"
        return None

    async def scan(self) -> list[ChurnDecision]:
        """Route every former merchant once; running it again changes nothing for merchants already routed."""
        decisions = []
        for entry in self.former():
            merchant = entry["merchant"]
            problem = self.check(entry)
            if problem:
                decisions.append(ChurnDecision(merchant["id"], "skip", problem))
                continue
            days = (self.clock() - entry["churned_at"]).days
            complaint = self._open_complaint(merchant["id"])
            if complaint is None and in_holdout(merchant["id"], self.seed):
                await self.ledger.record(holdout_mission_id(merchant["id"]), EventKind.HOLDOUT_ASSIGNED, {
                    "merchant_id": merchant["id"], "merchant_name": merchant["name"], "city": merchant["city"],
                    "product": entry["product"], "churned_at": entry["churned_at"].isoformat(), "days": days,
                    "seed": self.seed, "share": HOLDOUT_SHARE})
                decisions.append(ChurnDecision(merchant["id"], "holdout", "holdout (not called)"))
                continue
            signal = MerchantSignal(merchant_id=merchant["id"], kind=SignalKind.MERCHANT_CHURNED, door=Door.DATA,
                                    source="churn detector", details={"days": days, "product": entry["product"]})
            mission, _ = await self.intake.ingest(signal)
            if complaint is not None:
                reason = (f"open {complaint['category']} complaint {complaint['id']}: a person answers it before "
                          "any win-back call")
                await self.handoffs.escalate(mission.id, reason=reason)
                decisions.append(ChurnDecision(merchant["id"], "handoff", reason, mission.id))
            else:
                decisions.append(ChurnDecision(merchant["id"], "call", f"stopped {days} days ago", mission.id))
        return decisions


def holdouts(ledger: MissionLedger) -> list[dict]:
    """Every holdout decision in the ledger, newest first."""
    events = [e for e in ledger.store.events() if e.kind == EventKind.HOLDOUT_ASSIGNED]
    return [e.payload | {"at": e.at.isoformat()} for e in reversed(events)]


def leaving_reasons(ledger: MissionLedger) -> dict:
    """Counts of recorded reasons for leaving, by reason, city and product. B12 (manager insights) should reuse this."""
    counts: dict[str, dict[str, int]] = {"reason": {}, "city": {}, "product": {}}
    total = 0
    for event in ledger.store.events():
        if event.kind != EventKind.LEAVING_REASON_RECORDED:
            continue
        total += 1
        for key, tally in counts.items():
            value = event.payload.get(key) or "unknown"
            tally[value] = tally.get(value, 0) + 1
    return {"total": total, **{f"by_{key}": dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))
                               for key, c in counts.items()}}
