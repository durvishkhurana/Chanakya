import asyncio

import pytest

from chanakya.core.interfaces import IllegalTransitionError
from chanakya.core.llm import FakeLLM, Role
from chanakya.core.schemas import (
    ActionDecision,
    BeliefState,
    Door,
    EventKind,
    HandoffStatus,
    MissionCard,
    MissionState,
    MissionType,
    Move,
    MoveType,
    SignalKind,
    Speaker,
    ToolCall,
    Turn,
    Verdict,
)
from chanakya.humans.handoff import HandoffQueue, build_card
from chanakya.missions.ledger import MissionLedger, SQLiteMissionStore


def run(coro):
    return asyncio.run(coro)


def recorded_mission(ledger: MissionLedger) -> str:
    """A settlement call where the merchant gets upset, recorded the way the brain will record it."""
    card = MissionCard(merchant_id="mer_lakshmi", merchant_name="Lakshmi Tailors", language="en-IN",
                       door=Door.DATA, signal_kind=SignalKind.RENTAL_MISSED, signal_id="sig_1",
                       mission_type=MissionType.RETENTION, goal="Keep the Soundbox subscription",
                       why_now="Rental payment missed", starting_worries={"rental_cost": 0.6, "cash_flow": 0.4})

    async def scenario():
        mission = await ledger.create(card)
        for state in (MissionState.CONTACTING, MissionState.IN_CONVERSATION):
            await ledger.advance(mission.id, state)
        await ledger.attach_turn(mission.id, Turn(speaker=Speaker.AGENT, text="...",
                                                  move=Move(type=MoveType.PROBE_CONCERN, concern_id="rental_cost")))
        await ledger.attach_turn(mission.id, Turn(speaker=Speaker.MERCHANT,
                                                  text="My settlement is stuck for two days and you call about rental?"))
        await ledger.record(mission.id, EventKind.BELIEF_UPDATED,
                            BeliefState(probabilities={"settlement_delay": 0.7, "rental_cost": 0.2, "trust": 0.1}))
        call = ToolCall(mission_id=mission.id, tool="get_settlement_status", args={"merchant_id": "mer_lakshmi"})
        await ledger.attach_action(mission.id, ActionDecision(call=call, verdict=Verdict.EXECUTED, reason="ok"))
        await ledger.attach_action(mission.id, ActionDecision(call=call.model_copy(update={"tool": "send_summary"}),
                                                              verdict=Verdict.BLOCKED, reason="no consent"))
        return mission.id

    return run(scenario())


def test_card_carries_concerns_moves_actions_and_summary():
    ledger = MissionLedger(SQLiteMissionStore())
    mission_id = recorded_mission(ledger)
    card = run(build_card(ledger, mission_id, reason="merchant distressed about a settlement", urgent=True))
    assert list(card.open_concerns) == ["settlement_delay", "rental_cost", "trust"]
    assert card.tried_moves == ["PROBE_CONCERN(rental_cost)"]
    assert card.actions == ["get_settlement_status: executed"]  # blocked attempts are not "done"
    assert "Lakshmi Tailors" in card.summary and "settlement_delay 70%" in card.summary
    assert card.urgent and card.language == "en-IN"


def test_llm_summary_is_used_and_cleaned_but_failure_falls_back():
    ledger = MissionLedger(SQLiteMissionStore())
    mission_id = recorded_mission(ledger)
    llm = FakeLLM({Role.MAIN: "Upset about a delayed settlement — check it before discussing rental."})
    card = run(build_card(ledger, mission_id, reason="distress", llm=llm))
    assert card.summary == "Upset about a delayed settlement, check it before discussing rental."
    assert "My settlement is stuck" in llm.calls[0][1][0]["content"]

    def broken(role, messages):
        raise RuntimeError("provider down")

    card = run(build_card(ledger, mission_id, reason="distress", llm=FakeLLM(broken)))
    assert card.summary.startswith("Lakshmi Tailors:")


def test_queue_escalates_then_claim_and_resolve_are_recorded():
    ledger = MissionLedger(SQLiteMissionStore())
    queue = HandoffQueue(ledger)
    mission_id = recorded_mission(ledger)
    card = run(queue.escalate(mission_id, reason="distress", urgent=True))
    assert ledger.store.get(mission_id).state == MissionState.ESCALATED
    assert [c.id for c in queue.list(HandoffStatus.OPEN)] == [card.id]

    with pytest.raises(ValueError):
        run(queue.resolve(card.id, "too early"))
    run(queue.claim(card.id, "Sunita"))
    with pytest.raises(ValueError):
        run(queue.claim(card.id, "someone else"))
    done = run(queue.resolve(card.id, "Settlement released; merchant keeps the Soundbox"))
    assert done.status == HandoffStatus.RESOLVED and done.claimed_by == "Sunita"

    kinds = [e.kind for e in ledger.store.events(mission_id)]
    assert kinds[-3:] == [EventKind.HANDOFF_CREATED, EventKind.HANDOFF_CLAIMED, EventKind.HANDOFF_RESOLVED]


def test_urgent_cards_come_first_and_unknown_ids_fail():
    ledger = MissionLedger(SQLiteMissionStore())
    queue = HandoffQueue(ledger)
    calm = run(queue.escalate(recorded_mission(ledger), reason="asked for a human"))
    upset = run(queue.escalate(recorded_mission(ledger), reason="distress", urgent=True))
    assert [c.id for c in queue.list()] == [upset.id, calm.id]
    with pytest.raises(LookupError):
        run(queue.claim("ho_missing", "Sunita"))


def test_cannot_escalate_a_closed_mission():
    ledger = MissionLedger(SQLiteMissionStore())
    queue = HandoffQueue(ledger)
    mission_id = recorded_mission(ledger)
    run(ledger.close(mission_id, MissionState.CLOSED_NOT_INTERESTED, outcome="said no"))
    with pytest.raises(IllegalTransitionError):
        run(queue.escalate(mission_id, reason="late"))
    assert queue.list() == []
