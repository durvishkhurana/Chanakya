"""REST API for coach mode (task B11): the A11 coach engine follows a human telecaller's call turn by turn.

The engine never speaks and takes no actions. Each merchant turn returns the suggested next move, how to
answer the worry with sourced facts, the updated worries, and a hand-off draft once it says to escalate.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chanakya.brain.concern_bank import DATA, default_bank
from chanakya.brain.contracts.schemas import Door, Merchant, MissionCard, MissionKind, MoveType, TriggerType, Turn
from chanakya.brain.forest.forest import parse_move
from chanakya.humans.coach_engine import CoachEngine

router = APIRouter(prefix="/api/coach", tags=["coach"])

FIXTURE = DATA / "transcripts" / "human_call_fixture.json"
MAX_SESSIONS = 50


class StartRequest(BaseModel):
    merchant_name: str = Field(default="Kirana merchant (fictional)", min_length=1, max_length=80)
    business_type: str = Field(default="kirana", max_length=40)
    city: str = Field(default="Jaipur", max_length=40)
    language: str = Field(default="hi-IN", max_length=10)
    trigger: TriggerType = TriggerType.UPI_RISING_NO_SOUNDBOX
    recorded: bool = Field(default=False, description="Replaying the recorded call: pin the planner's seed so replays match")


class TurnRequest(BaseModel):
    speaker: Literal["merchant", "human_agent"]
    text: str = Field(min_length=1, max_length=1000)
    move: str | None = Field(default=None, max_length=80, description="The telecaller's move key, e.g. RECOMMEND(soundbox)")


class Session:
    """One coached call: the engine, the merchant's card and the hand-off draft once there is one."""

    def __init__(self, engine: CoachEngine):
        self.id = uuid4().hex[:12]
        self.engine = engine
        self.starting = dict(engine.state.belief.probabilities)
        self.suggestions = 0
        self.handoff: dict | None = None

    def view(self) -> dict:
        card = self.engine.state.card
        return {"session_id": self.id, "merchant": card.merchant.model_dump(mode="json"),
                "trigger": card.trigger, "why_now": card.why_now, "starting_worries": self.starting,
                "worries": self.engine.state.belief.probabilities, "turns": len(self.engine.state.transcript.turns),
                "suggestions": self.suggestions, "handoff": self.handoff,
                "evidence": self.engine.tracker.last_evidence, "scorer": self.engine.tracker.scorer_name}


_sessions: dict[str, Session] = {}  # ponytail: in memory, lost on restart; a store if coach calls must survive one


@lru_cache(maxsize=1)
def _sources() -> dict[str, dict]:
    """Every knowledge node's title, source URL and review date, by node id."""
    found: dict[str, dict] = {}

    def walk(nodes):
        for node in nodes:
            text = node.get("text", "")
            url = re.search(r"Source[^:.]*:\s*(https://[^\s,]+?)\.?(?:\s|,|$)", text)
            reviewed = re.search(r"Reviewed (\d{4}-\d{2}-\d{2})", text)
            if node.get("node_id"):
                found[node["node_id"]] = {"title": node.get("title", ""), "url": url.group(1) if url else None,
                                          "reviewed": reviewed.group(1) if reviewed else None}
            walk(node.get("nodes", []))

    for path in sorted((DATA / "knowledge").glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")).get("tree", {}).get("result", []))
    return found


def guide(engine: CoachEngine, concern_id: str | None) -> dict | None:
    """How the Concern Bank says to answer this worry, with the sourced pages behind it."""
    concern = engine.bank.concerns.get(concern_id) if concern_id else None
    if concern is None or not concern.resolve_conditions:
        return None
    condition = concern.resolve_conditions[0]
    sources = [_sources()[node] for node in condition.knowledge_node_ids if node in _sources()]
    return {"how": condition.description, "sources": sources}


def _handoff(session: Session, reason: str) -> dict:
    state = session.engine.state
    merchant = state.card.merchant
    said = next((t.text for t in reversed(state.transcript.turns) if t.speaker == "merchant"), "")
    worries = dict(sorted(state.belief.probabilities.items(), key=lambda kv: -kv[1])[:3])
    return {"merchant_name": merchant.name, "reason": reason, "merchant_said": said, "open_concerns": worries,
            "summary": f"{merchant.name}, {merchant.business_type} in {merchant.city}, needs a senior colleague. "
                       f"Turn {len(state.transcript.turns)} of a telecaller call. Last words: “{said}”"}


def _session(session_id: str) -> Session:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Coach session not found. Start a new one.")
    return _sessions[session_id]


@router.get("/recorded")
async def recorded() -> dict:
    """The recorded (fictional, scripted) telecaller call that coach mode is tested with."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def value_estimate(plan, move) -> dict:
    """The look-ahead's value for the suggested move (chance of a yes) and the best alternatives, for the screen."""
    if plan is None or not plan.candidates:
        return {"value": None, "alternatives": []}
    chosen = next((c.score for c in plan.candidates if c.move.key() == move.key()), None)
    others = sorted((c for c in plan.candidates if c.move.key() != move.key()), key=lambda c: -c.score)[:2]
    return {"value": round(chosen, 3) if chosen is not None else None,
            "alternatives": [{"key": c.move.key(), "value": round(c.score, 3)} for c in others]}


@router.post("/sessions")
async def start(request: StartRequest) -> dict:
    """Start following a call. The engine starts from the trigger's prior worries."""
    if len(_sessions) >= MAX_SESSIONS:
        _sessions.pop(next(iter(_sessions)))
    # The planner seeds from the mission id, so a fixed id makes the recorded call replay the same way every time.
    pinned = {"mission_id": "coach_recorded"} if request.recorded else {}
    from chanakya.brain.memory.memory import configured_memory
    from chanakya.brain.planner_nrpa import NRPAPlanner
    from chanakya.brain.value.network import configured_leaf_value
    from chanakya.core.config import Settings
    from chanakya.neural.scorer import configured_worry_scorer, select_scorer

    settings = Settings.from_env()  # PLANNER_MEMORY and PLANNER_VALUE apply to coached calls too (N4)

    engine = CoachEngine(MissionCard(
        **pinned,
        merchant=Merchant(merchant_id="coach_merchant", name=request.merchant_name, business_type=request.business_type,
                          city=request.city, language=request.language),
        kind=MissionKind.SALES, goal="Coach a telecaller's call", door=Door.HUMAN, trigger=request.trigger,
        why_now="A telecaller is on the call; Chanakya coaches silently",
        starting_worries=default_bank().priors[request.trigger]),
        scorer=select_scorer(configured_worry_scorer(), default_bank()),
        # Coach mode never used the forest, so only PLANNER_MEMORY=neural adds a memory and the default is unchanged.
        planner=NRPAPlanner(default_bank(),
                            forest=configured_memory("neural") if settings.planner_memory == "neural" else None,
                            leaf_value=configured_leaf_value(settings.planner_value)))
    session = Session(engine)
    _sessions[session.id] = session
    return session.view()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """The coached call so far."""
    return _session(session_id).view()


@router.post("/sessions/{session_id}/turns")
async def add_turn(session_id: str, request: TurnRequest) -> dict:
    """Fold in one turn. After a merchant turn, return the suggestion for the telecaller."""
    session = _session(session_id)
    try:
        move = parse_move(request.move) if request.move else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Unknown move: {request.move}") from error
    suggestion = await session.engine.observe(Turn(speaker=request.speaker, text=request.text, move=move))
    body = None
    if suggestion is not None:
        session.suggestions += 1
        concern = suggestion.move.concern
        body = {"move": suggestion.move.model_dump(mode="json"), "key": suggestion.move.key(), "reason": suggestion.reason,
                "likelihood": session.engine.state.belief.probabilities.get(concern) if concern else None,
                "guide": guide(session.engine, concern), **value_estimate(session.engine.last_plan, suggestion.move)}
        if suggestion.move.type == MoveType.ESCALATE and session.handoff is None:
            session.handoff = _handoff(session, suggestion.reason)
    return {**session.view(), "suggestion": body}
