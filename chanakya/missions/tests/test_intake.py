import asyncio
from datetime import UTC, datetime

import pytest

from chanakya.actions.gate import merchant_from_db
from chanakya.actions.registry import MockToolRegistry
from chanakya.actions.systems.db import MockDB
from chanakya.actions.systems.seed import seed
from chanakya.core.schemas import (
    Door,
    EventKind,
    Merchant,
    MerchantSignal,
    MissionState,
    MissionType,
    SignalKind,
)
from chanakya.missions.intake import RULES, MissionIntake, build_card
from chanakya.missions.ledger import MissionLedger, SQLiteMissionStore
from chanakya.missions.queue import MissionQueue
from chanakya.missions.signals import demo_feed

RAMESH = Merchant(id="mer_ramesh", name="Ramesh Kirana Store", business_type="kirana", city="Patiala",
                  contact_window={"start_hour": 14, "end_hour": 17})


def run(coro):
    return asyncio.run(coro)


def rig():
    db = MockDB()
    seed(db)
    registry = MockToolRegistry(db)
    ledger = MissionLedger(SQLiteMissionStore())
    return ledger, MissionIntake(ledger, lambda merchant_id: merchant_from_db(registry, merchant_id))


def callback(merchant_id="mer_ramesh", product="soundbox") -> MerchantSignal:
    return MerchantSignal(merchant_id=merchant_id, kind=SignalKind.CALLBACK_REQUEST, door=Door.MERCHANT,
                          source="mock product page", details={"product": product})


def test_every_signal_kind_has_a_rule():
    assert set(RULES) == set(SignalKind)


@pytest.mark.parametrize("kind", list(SignalKind))
def test_every_kind_builds_a_complete_card(kind):
    signal = MerchantSignal(merchant_id="mer_ramesh", kind=kind, door=RULES[kind].door, source="test")
    card = build_card(signal, RAMESH)
    assert card.why_now and card.goal and "{" not in card.why_now + card.goal
    assert abs(sum(card.starting_worries.values()) - 1) < 1e-9
    assert card.priority > 0 and card.contact_window == RAMESH.contact_window


def test_callback_card_matches_the_idea_example():
    card = build_card(callback(), RAMESH)
    assert card.goal == "Sell soundbox -> verified onboarding"
    assert card.why_now == "Requested a callback on the soundbox page"
    assert card.starting_worries == {"hidden_charges": 0.5, "competitor_qr": 0.3, "just_busy": 0.2}
    assert card.door == Door.MERCHANT and card.mission_type == MissionType.SALES


def test_signal_details_fill_the_why_now():
    signal = MerchantSignal(merchant_id="mer_ramesh", kind=SignalKind.SOUNDBOX_UNUSED, door=Door.DATA,
                            source="telemetry", details={"days": 8})
    card = build_card(signal, RAMESH)
    assert card.why_now == "Soundbox has not taken a payment for 8 days"
    assert card.mission_type == MissionType.RETENTION


def test_wrong_door_is_rejected():
    with pytest.raises(ValueError):
        build_card(MerchantSignal(merchant_id="mer_ramesh", kind=SignalKind.CALLBACK_REQUEST, door=Door.DATA,
                                  source="x"), RAMESH)


def test_ingest_creates_mission_and_records_the_signal():
    ledger, intake = rig()
    mission, created = run(intake.ingest(callback()))
    assert created and mission.state == MissionState.CREATED
    assert [e.kind for e in ledger.store.events(mission.id)] == [EventKind.MISSION_CREATED, EventKind.SIGNAL_RECEIVED]


def test_repeat_trigger_refreshes_instead_of_duplicating():
    ledger, intake = rig()
    first, _ = run(intake.ingest(MerchantSignal(merchant_id="mer_sharma", kind=SignalKind.UPI_RISING_NO_SOUNDBOX,
                                                door=Door.DATA, source="trends", details={"growth_pct": 64})))
    second, created = run(intake.ingest(MerchantSignal(merchant_id="mer_sharma", kind=SignalKind.LEAD_LIST_ASSIGNED,
                                                       door=Door.HUMAN, source="Sunita", details={"assigned_by": "Sunita"})))
    assert not created and second.id == first.id
    assert second.card.why_now == "From Sunita's lead list; earlier: UPI payments up 64% this month, no Soundbox"
    assert second.card.priority == max(first.card.priority, second.card.priority)
    assert len(ledger.store.list()) == 1


def test_different_goal_opens_a_new_mission():
    ledger, intake = rig()
    run(intake.ingest(callback(product="soundbox")))
    _, created = run(intake.ingest(callback(product="card_machine")))
    assert created and len(ledger.store.list()) == 2


def test_closed_mission_does_not_absorb_a_new_signal():
    ledger, intake = rig()
    mission, _ = run(intake.ingest(callback()))
    run(ledger.close(mission.id, MissionState.CLOSED_NOT_INTERESTED, outcome="said no"))
    again, created = run(intake.ingest(callback()))
    assert created and again.id != mission.id


def test_do_not_call_merchants_are_closed_immediately():
    _, intake = rig()
    mission, _ = run(intake.ingest(MerchantSignal(merchant_id="mer_baldev", kind=SignalKind.LEAD_LIST_ASSIGNED,
                                                  door=Door.HUMAN, source="Sunita")))
    assert mission.state == MissionState.CLOSED_NOT_INTERESTED and mission.outcome == "do-not-call"


def test_unknown_merchant_fails():
    _, intake = rig()
    with pytest.raises(LookupError):
        run(intake.ingest(callback(merchant_id="mer_nobody")))


def test_demo_feed_opens_expected_missions_and_is_idempotent():
    ledger, intake = rig()
    for _ in range(2):
        for signal in demo_feed():
            run(intake.ingest(signal))
    missions = ledger.store.list()
    assert len(missions) == 6  # Sharma's two signals share one mission
    assert {m.card.door for m in missions} == {Door.MERCHANT, Door.DATA, Door.HUMAN}
    assert sum(m.state == MissionState.CLOSED_NOT_INTERESTED for m in missions) == 1  # Baldev, do-not-call


def queue_at(utc_hour: int, minute: int = 0):
    ledger, intake = rig()
    for signal in demo_feed():
        run(intake.ingest(signal))
    run(intake.ingest(callback()))
    return MissionQueue(ledger, clock=lambda: datetime(2026, 10, 29, utc_hour, minute, tzinfo=UTC))


def test_queue_puts_callbacks_first_and_respects_windows():
    queue = queue_at(5, 30)  # 11:00 in Asia/Kolkata
    entries = queue.entries()
    assert entries[0].mission.card.signal_kind == SignalKind.CALLBACK_REQUEST and entries[0].ready
    by_merchant = {e.mission.card.merchant_id: e for e in entries}
    assert by_merchant["mer_gurpreet"].ready  # prefers 10-13
    assert not by_merchant["mer_imran"].ready and by_merchant["mer_imran"].reason == "prefers 12:00-20:00"
    assert "mer_baldev" not in by_merchant  # closed, never queued
    ready = [e for e in entries if e.ready]
    assert [e.mission.card.priority for e in ready] == sorted((e.mission.card.priority for e in ready), reverse=True)
    assert queue.next_ready().card.signal_kind == SignalKind.CALLBACK_REQUEST


def test_nothing_is_ready_at_night():
    queue = queue_at(17, 30)  # 23:00 in Asia/Kolkata
    assert queue.next_ready() is None
    assert {e.reason for e in queue.entries()} == {"outside calling hours"}
