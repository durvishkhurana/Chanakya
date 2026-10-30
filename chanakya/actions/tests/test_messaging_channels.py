import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from chanakya.actions.systems.messaging_channels import classify, receive_reply, render, thread
from chanakya.actions.systems.tools import complete_onboarding
from chanakya.core.config import Settings
from chanakya.core.schemas import Door, EventKind, MerchantSignal, MissionState, SignalKind, ToolCall, Verdict
from chanakya.missions.runtime import Runtime
from chanakya.missions.scheduler import SimClock

S = MissionState
START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata, inside calling hours


@pytest.fixture
def runtime(tmp_path):
    return Runtime.build(Settings(db_path=tmp_path / "ledger.db"), clock=SimClock(START))


def link_sent(runtime, channel="whatsapp") -> str:
    """A sales mission for Ramesh that has just sent the onboarding link on ``channel``."""
    async def go():
        mission, _ = await runtime.intake.ingest(MerchantSignal(
            merchant_id="mer_ramesh", kind=SignalKind.CALLBACK_REQUEST, door=Door.MERCHANT, source="mock product page"))
        ledger = runtime.ledger
        for state in (S.CONTACTING, S.IN_CONVERSATION):
            await ledger.advance(mission.id, state)
        await ledger.record(mission.id, EventKind.AI_DISCLOSED, {"text": "Main Chanakya hoon, ek AI assistant"})
        await ledger.record(mission.id, EventKind.CONSENT_GIVEN,
                            {"tools": ["send_onboarding_link", "send_onboarding_reminder"], "utterance": "Haan, bhej do"})
        await ledger.advance(mission.id, S.ACTION_PENDING)
        decision = await runtime.submit(ToolCall(mission_id=mission.id, tool="send_onboarding_link", args={
            "merchant_id": "mer_ramesh", "product": "soundbox", "channel": channel, "language": "hi-IN"}))
        assert decision.verdict == Verdict.EXECUTED
        return mission.id

    return asyncio.run(go())


def test_templates_differ_by_channel_and_language_and_never_carry_prices():
    whatsapp = render("link", "whatsapp", "hi-IN", name="Ramesh", product="soundbox", link="/demo/onboard/x")
    sms = render("link", "sms", "hi-IN", name="Ramesh", product="soundbox", link="/demo/onboard/x")
    punjabi = render("reminder", "sms", "pa-IN", name="Gurpreet", product="qr", link="/l")
    assert "\n" in whatsapp and "*soundbox*" in whatsapp and "\n" not in sms and "STOP" in sms
    assert punjabi.startswith("Sat Sri Akal Gurpreet")
    assert render("link", "sms", "ta-IN", name="A", product="qr", link="/l").startswith("Hello A")
    for text in (whatsapp, sms, punjabi):
        assert "₹" not in text and "rs" not in text.lower().split()


@pytest.mark.parametrize(("body", "intent"), [
    ("STOP", "stop"), ("ab message mat bhejo", "stop"), ("nahi chahiye", "stop"), ("ho gaya ji", "done"),
    ("call me in the evening", "callback"), ("main bahut pareshan hoon", "human"), ("kitne din lagenge?", "other"),
])
def test_replies_are_read_with_stop_winning(body, intent):
    assert classify(body) == intent


def test_a_mission_continues_after_a_whatsapp_reply_saying_done(runtime):
    mission_id = link_sent(runtime)
    session = runtime.db.one("SELECT id FROM onboarding_sessions WHERE mission_id = ?", mission_id)["id"]
    complete_onboarding(runtime.db, session)

    result = asyncio.run(receive_reply(runtime, "mer_ramesh", "whatsapp", "Ho gaya ji"))

    assert result["mission_id"] == mission_id and result["intent"] == "done"
    assert runtime.ledger.store.get(mission_id).state == S.DONE  # the onboarding system confirmed it, not the words
    kinds = [e.kind for e in runtime.ledger.store.events(mission_id)]
    assert EventKind.TURN_COMPLETED in kinds and EventKind.VERIFICATION_CHECKED in kinds
    assert [m["direction"] for m in thread(runtime.db, "mer_ramesh")] == ["out", "in"]


def test_done_without_onboarding_keeps_the_mission_waiting(runtime):
    mission_id = link_sent(runtime)
    asyncio.run(receive_reply(runtime, "mer_ramesh", "whatsapp", "ho gaya"))
    assert runtime.ledger.store.get(mission_id).state == S.AWAITING_CONFIRMATION


def test_stop_blocks_every_later_message_and_the_mission_closes(runtime):
    mission_id = link_sent(runtime)
    asyncio.run(receive_reply(runtime, "mer_ramesh", "whatsapp", "STOP"))

    async def follow_ups():
        for _ in range(4):
            await runtime.fast_forward(timedelta(days=1))

    asyncio.run(follow_ups())
    decisions = [e.payload for e in runtime.ledger.store.events(mission_id) if e.kind == EventKind.ACTION_DECISION]
    reminders = [d for d in decisions if d["call"]["tool"] == "send_onboarding_reminder"]
    assert reminders and all(d["verdict"] == "blocked" and d["reason"] == "merchant declined" for d in reminders)
    assert runtime.ledger.store.get(mission_id).state == S.CLOSED_NOT_INTERESTED


def test_a_request_for_a_call_puts_the_mission_back_in_the_queue(runtime):
    mission_id = link_sent(runtime, channel="sms")
    result = asyncio.run(receive_reply(runtime, "mer_ramesh", "sms", "please call me"))
    assert result["state"] == "SCHEDULED" and runtime.scheduler.pending(mission_id) == []
    entry = next(e for e in runtime.queue.entries() if e.mission.id == mission_id)
    assert entry.ready and entry.reason == "callback is due"


def test_a_reply_with_no_open_mission_stays_in_the_inbox(runtime):
    result = asyncio.run(receive_reply(runtime, "mer_ramesh", "whatsapp", "hello?"))
    assert result["mission_id"] is None and thread(runtime.db, "mer_ramesh")[-1]["body"] == "hello?"
    with pytest.raises(LookupError):
        asyncio.run(receive_reply(runtime, "mer_nobody", "sms", "hi"))
