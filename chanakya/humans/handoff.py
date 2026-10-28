"""Hand-off cards and the human queue (docs/IDEA.md 3.9)."""

from __future__ import annotations

import logging
import re

from chanakya.core.llm import LLM, Role
from chanakya.core.schemas import (
    ActionDecision,
    BeliefState,
    EventKind,
    HandoffCard,
    HandoffStatus,
    MissionEvent,
    MissionState,
    Speaker,
    Turn,
    Verdict,
)
from chanakya.missions.ledger import MissionLedger

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, status TEXT NOT NULL, urgent INTEGER NOT NULL,
    created_at TEXT NOT NULL, data TEXT NOT NULL
);
"""

SUMMARY_PROMPT = (
    "Write ONE short English sentence for a human sales agent taking over this call. "
    "Say what the merchant wants, what worries them and what is left to do. "
    "Use only the facts given. No em dash characters.\n\n{facts}"
)


def _belief(events: list[MissionEvent], fallback: dict[str, float]) -> dict[str, float]:
    updates = [e for e in events if e.kind == EventKind.BELIEF_UPDATED]
    probabilities = BeliefState.model_validate(updates[-1].payload).probabilities if updates else fallback
    return dict(sorted(probabilities.items(), key=lambda item: item[1], reverse=True)[:3])


def _tried_moves(events: list[MissionEvent]) -> list[str]:
    moves: list[str] = []
    for event in events:
        if event.kind != EventKind.TURN_COMPLETED:
            continue
        turn = Turn.model_validate(event.payload)
        if turn.speaker == Speaker.AGENT and turn.move is not None:
            label = turn.move.type.value + (f"({turn.move.concern_id})" if turn.move.concern_id else "")
            if label not in moves:
                moves.append(label)
    return moves


def _actions(events: list[MissionEvent]) -> list[str]:
    actions = []
    for event in events:
        if event.kind == EventKind.ACTION_DECISION:
            decision = ActionDecision.model_validate(event.payload)
            if decision.verdict in (Verdict.EXECUTED, Verdict.FAILED):
                actions.append(f"{decision.call.tool}: {decision.verdict.value}")
    return actions


def _last_merchant_words(events: list[MissionEvent]) -> str | None:
    for event in reversed(events):
        if event.kind == EventKind.TURN_COMPLETED and event.payload.get("speaker") == Speaker.MERCHANT.value:
            return event.payload.get("text")
    return None


async def build_card(ledger: MissionLedger, mission_id: str, reason: str, urgent: bool = False,
                     llm: LLM | None = None) -> HandoffCard:
    """Everything a human needs so the merchant never repeats themselves."""
    mission = ledger.store.get(mission_id)
    if mission is None:
        raise LookupError(f"unknown mission {mission_id}")
    events = ledger.store.events(mission_id)
    concerns = _belief(events, mission.card.starting_worries)
    moves, actions, last_words = _tried_moves(events), _actions(events), _last_merchant_words(events)
    top = ", ".join(f"{name} {p:.0%}" for name, p in concerns.items()) or "unknown"
    summary = (f"{mission.card.merchant_name}: {mission.card.goal}. Escalated because: {reason}. "
               f"Likely worries: {top}. Done so far: {', '.join(actions) or 'nothing'}.")
    if llm is not None:
        facts = (f"{summary}\nWhy now: {mission.card.why_now}\nMoves tried: {', '.join(moves) or 'none'}\n"
                 f"Merchant's last words: {last_words or 'none'}")
        try:
            text = await llm.complete(Role.MAIN, [{"role": "user", "content": SUMMARY_PROMPT.format(facts=facts)}],
                                      max_tokens=120, temperature=0.2)
            summary = re.sub(r"\s*—\s*", ", ", text).strip() or summary
        except Exception:
            logger.warning("Hand-off summary failed for %s; using the built-in summary", mission_id, exc_info=True)
    return HandoffCard(
        mission_id=mission_id, merchant_name=mission.card.merchant_name, language=mission.card.language,
        reason=reason, summary=summary, open_concerns=concerns, tried_moves=moves, actions=actions, urgent=urgent,
    )


class HandoffQueue:
    """Hand-off cards stored next to the ledger; claim and resolve are recorded as mission events."""

    def __init__(self, ledger: MissionLedger, llm: LLM | None = None):
        self.ledger = ledger
        self.llm = llm
        self.conn = ledger.store.conn
        self.conn.executescript(SCHEMA)

    async def escalate(self, mission_id: str, reason: str, urgent: bool = False) -> HandoffCard:
        """Build a card, move the mission to ESCALATED and put the card in the queue."""
        card = await build_card(self.ledger, mission_id, reason, urgent=urgent, llm=self.llm)
        await self.ledger.advance(mission_id, MissionState.ESCALATED, reason=reason, outcome="handed to a human")
        self._save(card)
        await self.ledger.record(mission_id, EventKind.HANDOFF_CREATED, card)
        return card

    async def claim(self, handoff_id: str, agent: str) -> HandoffCard:
        """A human takes the hand-off."""
        card = self._require(handoff_id, HandoffStatus.OPEN)
        card = card.model_copy(update={"status": HandoffStatus.CLAIMED, "claimed_by": agent})
        self._save(card)
        await self.ledger.record(card.mission_id, EventKind.HANDOFF_CLAIMED, {"handoff_id": handoff_id, "agent": agent})
        return card

    async def resolve(self, handoff_id: str, resolution: str) -> HandoffCard:
        """The human closes the hand-off with what happened."""
        card = self._require(handoff_id, HandoffStatus.CLAIMED)
        card = card.model_copy(update={"status": HandoffStatus.RESOLVED, "resolution": resolution})
        self._save(card)
        await self.ledger.record(card.mission_id, EventKind.HANDOFF_RESOLVED,
                                 {"handoff_id": handoff_id, "resolution": resolution})
        return card

    def get(self, handoff_id: str) -> HandoffCard | None:
        """One card by id."""
        row = self.conn.execute("SELECT data FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        return HandoffCard.model_validate_json(row[0]) if row else None

    def list(self, status: HandoffStatus | None = None) -> list[HandoffCard]:
        """Cards, urgent first, then oldest first."""
        rows = self.conn.execute("SELECT data FROM handoffs ORDER BY urgent DESC, created_at").fetchall()
        cards = [HandoffCard.model_validate_json(row[0]) for row in rows]
        return [c for c in cards if status is None or c.status == status]

    def _require(self, handoff_id: str, status: HandoffStatus) -> HandoffCard:
        card = self.get(handoff_id)
        if card is None:
            raise LookupError(f"unknown hand-off {handoff_id}")
        if card.status != status:
            raise ValueError(f"hand-off is {card.status}, expected {status}")
        return card

    def _save(self, card: HandoffCard) -> None:
        with self.conn:
            self.conn.execute("REPLACE INTO handoffs VALUES (?, ?, ?, ?, ?, ?)",
                              (card.id, card.mission_id, card.status.value, int(card.urgent),
                               card.created_at.isoformat(), card.model_dump_json()))
