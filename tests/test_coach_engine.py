"""Coach mode on a recorded (fictional) human telecaller call."""

import asyncio
import json

from chanakya.brain.concern_bank import DATA
from chanakya.brain.contracts.fakes import InMemoryMissionStore, RecordingEventBus, sample_card
from chanakya.brain.contracts.schemas import Merchant, MoveType, TriggerType, Turn
from chanakya.brain.forest.forest import parse_move
from chanakya.humans.coach_engine import CoachEngine, reason_for

FIXTURE = DATA / "transcripts" / "human_call_fixture.json"


def recorded_call():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mission = data["metadata"]["mission"]
    trigger = TriggerType(mission["trigger"])
    from chanakya.brain.concern_bank import default_bank

    card = sample_card(trigger=trigger, starting_worries=default_bank().priors[trigger],
                       merchant=Merchant(merchant_id="coach_fixture", name="Recorded call (fictional)",
                                         business_type=mission["business_type"], city=mission["city"],
                                         language=mission["language"]))
    turns = [Turn(speaker=t["speaker"], text=t["text"], move=parse_move(t["move"]) if t.get("move") else None)
             for t in data["turns"]]
    return card, turns


def suggestions():
    card, turns = recorded_call()
    bus = RecordingEventBus(InMemoryMissionStore())
    engine = CoachEngine(card, bus=bus)

    async def collect():
        return [s async for s in engine.stream(turns)]

    return asyncio.run(collect()), bus, engine


def test_suggestions_stream_once_per_merchant_turn_with_a_reason():
    found, bus, _ = suggestions()
    _, turns = recorded_call()
    assert len(found) == sum(t.speaker == "merchant" for t in turns)
    assert all(s.reason and s.move for s in found)
    assert [e.kind for e in bus.published if e.kind == "CoachSuggestion"] == ["CoachSuggestion"] * len(found)


def test_suggestions_follow_the_call():
    found, _, _ = suggestions()
    moves = [s.move for s in found]
    assert any(m.type == MoveType.RESOLVE_CONCERN and m.concern == "competitor_qr" for m in moves[:2])
    assert any(m.type == MoveType.RESOLVE_CONCERN and m.concern in {"rental_cost", "hidden_charges"} for m in moves)
    assert moves[-1].type == MoveType.CONFIRM_CONSENT, "an unprompted yes should get a clear consent question"


def test_coach_never_speaks_or_acts_and_never_suggests_disclosure():
    found, _, engine = suggestions()
    assert all(m.type != MoveType.DISCLOSE_AND_GREET for m in (s.move for s in found))
    assert engine.state.actions == []
    assert not [t for t in engine.state.transcript.turns if t.speaker == "agent"]


def test_reasons_are_plain_one_liners():
    for suggestion in suggestions()[0]:
        assert "\n" not in suggestion.reason and len(suggestion.reason) < 120 and "—" not in suggestion.reason
    from chanakya.brain.contracts.schemas import Move

    assert "rental cost" in reason_for(Move(type=MoveType.RESOLVE_CONCERN, concern="rental_cost"), 0.7)
