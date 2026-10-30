"""Manager insights computed from the mission ledger (task B12). Pure functions over missions, events and hand-offs.

Every number is counted from ledger events, never estimated:
- the worry a call found is the top of its last ``belief_updated`` event;
- a mission reached a funnel stage if its events show it (state changes, an explicit consent, an executed write);
- a move "addressed" a worry when Chanakya probed or answered that worry on the call.
Reasons for leaving come from ``chanakya.missions.churn.leaving_reasons``, which win-back calls already record.
"""

from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from chanakya.core.schemas import EventKind, HandoffCard, Mission, MissionEvent, MissionState

# Track B's intake names a few worries differently from the Concern Bank (see chanakya/brain/core_adapters.py).
ALIASES = {"swipe_charges": "per_swipe_charges", "device_reliability": "device_issue", "cash_flow": "rental_cost"}
ANSWERING_MOVES = ("PROBE_CONCERN", "RESOLVE_CONCERN")
STAGES = (("opened", "Mission opened"), ("called", "Merchant called"), ("talked", "Merchant talked"),
          ("consent", "Gave a clear yes"), ("action", "Action done"), ("done", "Verified done"))


def worry_id(name: str | None) -> str | None:
    return ALIASES.get(name, name) if name else None


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


class CallFacts:
    """What one mission's events say about its call."""

    def __init__(self, mission: Mission, events: list[MissionEvent]):
        self.mission = mission
        beliefs = [e.payload.get("probabilities") or {} for e in events if e.kind == EventKind.BELIEF_UPDATED]
        last = beliefs[-1] if beliefs else {}
        self.found = worry_id(max(last, key=last.get)) if last else None
        start = mission.card.starting_worries
        self.started = worry_id(max(start, key=start.get)) if start else None
        states = {e.payload.get("to") for e in events if e.kind == EventKind.STATE_CHANGED}
        self.called = bool(states & {"CONTACTING", "IN_CONVERSATION"})
        self.talked = "IN_CONVERSATION" in states or any(
            e.kind == EventKind.TURN_COMPLETED and e.payload.get("speaker") == "merchant" for e in events)
        self.consent = any(e.kind == EventKind.CONSENT_GIVEN for e in events)
        self.action = any(e.kind == EventKind.ACTION_DECISION and e.payload.get("verdict") == "executed"
                          and not ((e.payload.get("call") or {}).get("tool") or "").startswith("get_") for e in events)
        self.done = mission.state == MissionState.DONE
        moves = [(e.payload.get("move") or {}) for e in events
                 if e.kind == EventKind.TURN_COMPLETED and e.payload.get("speaker") == "agent"]
        self.agent_turns = len(moves)
        self.addressed = {(m.get("type"), worry_id(m.get("concern_id"))) for m in moves
                          if m.get("type") in ANSWERING_MOVES and m.get("concern_id")}
        self.day = mission.created_at.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()


def facts(missions: list[Mission], events: list[MissionEvent]) -> list[CallFacts]:
    by_mission: dict[str, list[MissionEvent]] = defaultdict(list)
    for event in events:
        by_mission[event.mission_id].append(event)
    return [CallFacts(m, by_mission[m.id]) for m in missions]


def worries(calls: list[CallFacts]) -> dict:
    """The worry each call found, overall and by product, language and day; and how often it was not the card's guess."""
    found = [c for c in calls if c.found]
    by = {"product": defaultdict(Counter), "language": defaultdict(Counter), "day": defaultdict(Counter)}
    for c in found:
        by["product"][c.mission.card.product or "unknown"][c.found] += 1
        by["language"][c.mission.card.language][c.found] += 1
        by["day"][c.day][c.found] += 1
    guessed = [c for c in found if c.started]
    return {
        "calls": len(found),
        "overall": dict(Counter(c.found for c in found).most_common()),
        "by_product": {k: dict(v.most_common()) for k, v in sorted(by["product"].items())},
        "by_language": {k: dict(v.most_common()) for k, v in sorted(by["language"].items())},
        "by_day": [{"day": day, "counts": dict(v.most_common())} for day, v in sorted(by["day"].items())],
        "differs_from_card": _rate(sum(c.found != c.started for c in guessed), len(guessed)),
    }


def funnel(calls: list[CallFacts]) -> dict:
    """How many missions reached each stage, overall and per mission type, and where the rest ended."""
    def count(group):
        return [{"stage": key, "label": label, "missions": sum(1 for c in group if key == "opened" or getattr(c, key))}
                for key, label in STAGES]

    types = defaultdict(list)
    for c in calls:
        types[c.mission.card.mission_type.value].append(c)
    open_or_closed = Counter(c.mission.state.value for c in calls if not c.done)
    return {"overall": count(calls), "by_type": {k: count(v) for k, v in sorted(types.items())},
            "not_done": dict(open_or_closed.most_common())}


def moves(calls: list[CallFacts]) -> list[dict]:
    """Per worry found: the consent rate when Chanakya addressed that worry on the call, and when it did not."""
    rows = []
    for worry, group in sorted(_group(c for c in calls if c.found and c.talked).items()):
        addressed = [c for c in group if any(w == worry for _, w in c.addressed)]
        skipped = [c for c in group if c not in addressed]
        per_move = []
        for move in ANSWERING_MOVES:
            used = [c for c in group if (move, worry) in c.addressed]
            if used:
                per_move.append({"move": move, "missions": len(used), "consent_rate": _rate(sum(c.consent for c in used), len(used))})
        rows.append({"worry": worry, "missions": len(group), "consent_rate": _rate(sum(c.consent for c in group), len(group)),
                     "addressed": {"missions": len(addressed), "consent_rate": _rate(sum(c.consent for c in addressed), len(addressed))},
                     "not_addressed": {"missions": len(skipped), "consent_rate": _rate(sum(c.consent for c in skipped), len(skipped))},
                     "moves": per_move})
    return sorted(rows, key=lambda r: -r["missions"])


def _group(calls) -> dict[str, list[CallFacts]]:
    groups = defaultdict(list)
    for c in calls:
        groups[c.found].append(c)
    return groups


def escalations(handoffs: list[HandoffCard]) -> dict:
    """Hand-offs to people: why, how many were urgent, and where they stand."""
    reasons = Counter(_reason(h.reason) for h in handoffs)
    return {"total": len(handoffs), "urgent": sum(h.urgent for h in handoffs),
            "by_reason": dict(reasons.most_common()), "by_status": dict(Counter(h.status.value for h in handoffs).most_common())}


def _reason(text: str) -> str:
    """Group free-text hand-off reasons: 'open device complaint t_12: ...' and 'distress' become short labels."""
    lowered = text.lower()
    if lowered.startswith("open ") and "complaint" in lowered:
        return "open complaint"
    return lowered.split(":")[0].strip() or "unknown"


def headline(calls: list[CallFacts], handoffs: list[HandoffCard]) -> dict:
    talked = [c for c in calls if c.talked]
    turns = sorted(c.agent_turns for c in talked)
    return {"missions": len(calls), "talked": len(talked),
            "consent_rate": _rate(sum(c.consent for c in talked), len(talked)),
            "done": sum(c.done for c in calls), "done_rate": _rate(sum(c.done for c in calls), len(calls)),
            "escalated": len(handoffs), "median_agent_turns": turns[len(turns) // 2] if turns else None}


def summarise(missions: list[Mission], events: list[MissionEvent], handoffs: list[HandoffCard], leaving: dict,
              now: datetime | None = None) -> dict:
    """Everything the insights screen shows, from one pass over the ledger."""
    calls = facts(missions, events)
    return {"generated_at": (now or datetime.now(ZoneInfo("UTC"))).isoformat(), "headline": headline(calls, handoffs),
            "worries": worries(calls), "funnel": funnel(calls), "moves": moves(calls),
            "escalations": escalations(handoffs), "leaving": leaving}
