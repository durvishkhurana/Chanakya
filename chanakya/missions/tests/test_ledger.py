import asyncio

import pytest

from chanakya.core.interfaces import IllegalTransitionError, MissionStore
from chanakya.core.schemas import (
    TERMINAL_STATES,
    ActionDecision,
    Door,
    EventKind,
    Mission,
    MissionCard,
    MissionState,
    MissionType,
    SignalKind,
    Speaker,
    ToolCall,
    Turn,
    Verdict,
)
from chanakya.missions.ledger import MissionLedger, SQLiteMissionStore
from chanakya.missions.state import ALLOWED, check_transition

S = MissionState
HAPPY_PATH = [S.CONTACTING, S.IN_CONVERSATION, S.ACTION_PENDING, S.AWAITING_CONFIRMATION, S.VERIFYING, S.DONE]


def card(why_now="Requested a callback") -> MissionCard:
    return MissionCard(
        merchant_id="mer_ramesh", merchant_name="Ramesh Kirana Store", door=Door.MERCHANT,
        signal_kind=SignalKind.CALLBACK_REQUEST, signal_id="sig_1", mission_type=MissionType.SALES,
        goal="Sell Soundbox", product="soundbox", why_now=why_now, starting_worries={"hidden_charges": 1},
    )


def run(coro):
    return asyncio.run(coro)


def test_store_satisfies_protocol():
    assert isinstance(SQLiteMissionStore(), MissionStore)


def test_every_state_has_rules_and_terminal_states_have_no_exits():
    assert set(ALLOWED) == set(MissionState)
    assert all(not ALLOWED[state] for state in TERMINAL_STATES)


def test_illegal_transitions_raise():
    with pytest.raises(IllegalTransitionError):
        check_transition(S.CREATED, S.DONE)
    with pytest.raises(IllegalTransitionError):
        check_transition(S.DONE, S.CONTACTING)
    check_transition(S.VERIFYING, S.DONE)


def test_full_mission_is_recorded_and_replayable(tmp_path):
    store = SQLiteMissionStore(tmp_path / "ledger.db")
    ledger = MissionLedger(store)

    async def scenario():
        mission = await ledger.create(card())
        for state in HAPPY_PATH[:2]:
            await ledger.advance(mission.id, state, reason="test")
        await ledger.attach_turn(mission.id, Turn(speaker=Speaker.MERCHANT, text="Kitna katega?"))
        call = ToolCall(mission_id=mission.id, tool="send_onboarding_link")
        await ledger.attach_action(mission.id, ActionDecision(call=call, verdict=Verdict.EXECUTED, reason="ok"))
        await ledger.update_card(mission.id, card("Requested a callback twice"), reason="repeat trigger")
        for state in HAPPY_PATH[2:-1]:
            await ledger.advance(mission.id, state)
        await ledger.close(mission.id, S.DONE, outcome="onboarding completed")
        return mission.id

    mission_id = run(scenario())
    stored = store.get(mission_id)
    assert stored.state == S.DONE and stored.outcome == "onboarding completed"

    reopened = MissionLedger(SQLiteMissionStore(tmp_path / "ledger.db"))
    replayed = reopened.replay(mission_id)
    assert (replayed.state, replayed.outcome, replayed.card) == (stored.state, stored.outcome, stored.card)
    assert replayed.card.why_now == "Requested a callback twice"

    events = reopened.store.events(mission_id)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert [e.kind for e in events].count(EventKind.STATE_CHANGED) == len(HAPPY_PATH)
    assert events[-1].payload == {"from": "VERIFYING", "to": "DONE", "reason": "closed", "outcome": "onboarding completed"}


def test_illegal_advance_leaves_mission_untouched():
    ledger = MissionLedger(SQLiteMissionStore())

    async def scenario():
        mission = await ledger.create(card())
        with pytest.raises(IllegalTransitionError):
            await ledger.advance(mission.id, S.DONE)
        return mission.id

    mission_id = run(scenario())
    assert ledger.store.get(mission_id).state == S.CREATED
    assert [e.kind for e in ledger.store.events(mission_id)] == [EventKind.MISSION_CREATED]


def test_close_requires_terminal_state_and_unknown_mission_fails():
    ledger = MissionLedger(SQLiteMissionStore())
    mission = run(ledger.create(card()))
    with pytest.raises(ValueError):
        run(ledger.close(mission.id, S.CONTACTING, outcome="x"))
    with pytest.raises(LookupError):
        run(ledger.advance("m_missing", S.CONTACTING))
    with pytest.raises(LookupError):
        ledger.replay("m_missing")


def test_list_filters_by_state_and_events_span_missions():
    ledger = MissionLedger(SQLiteMissionStore())
    first = run(ledger.create(card()))
    run(ledger.create(card()))
    run(ledger.advance(first.id, S.CONTACTING))
    assert [m.id for m in ledger.store.list({S.CONTACTING})] == [first.id]
    assert len(ledger.store.list()) == 2
    assert len(ledger.store.events()) == 3
    assert [e.seq for e in ledger.store.events(first.id, after_seq=1)] == [2]


def test_subscribers_see_ledger_events_live():
    ledger = MissionLedger(SQLiteMissionStore())

    async def scenario():
        stream = ledger.bus.subscribe()
        first = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        mission = await ledger.create(card())
        event = await first
        await stream.aclose()
        return mission, event

    mission, event = run(scenario())
    assert event.mission_id == mission.id and event.kind == EventKind.MISSION_CREATED and event.seq == 1


def test_missions_and_events_take_their_time_from_the_runtime_clock():
    from datetime import UTC, datetime, timedelta

    from chanakya.missions.scheduler import SimClock

    clock = SimClock(datetime(2026, 10, 1, 4, 0, tzinfo=UTC))
    ledger = MissionLedger(SQLiteMissionStore(), clock=clock)
    mission = run(ledger.create(card()))
    clock.advance(timedelta(days=2))
    run(ledger.advance(mission.id, MissionState.CONTACTING))
    created, moved = ledger.store.events(mission.id)
    assert mission.created_at == created.at == datetime(2026, 10, 1, 4, 0, tzinfo=UTC)
    assert moved.at == datetime(2026, 10, 3, 4, 0, tzinfo=UTC)


def test_the_store_survives_threads_reading_while_others_write(tmp_path):
    import threading

    store = SQLiteMissionStore(tmp_path / "ledger.db")
    missions = [store.create(Mission(card=card())) for _ in range(4)]
    errors = []

    def churn(mission):
        try:
            for _ in range(300):
                store.save(mission)
                assert store.get(mission.id).id == mission.id
                store.list()
        except Exception as error:  # noqa: BLE001 - any failure in a thread fails the test
            errors.append(error)

    threads = [threading.Thread(target=churn, args=(m,)) for m in missions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
