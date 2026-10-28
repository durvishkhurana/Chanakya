import asyncio
from datetime import UTC, datetime, timedelta

from chanakya.actions.gate import ActionGate, merchant_from_db
from chanakya.actions.registry import MockToolRegistry
from chanakya.actions.systems.db import FailurePolicy, MockDB
from chanakya.actions.systems.seed import seed
from chanakya.actions.systems.tools import complete_onboarding
from chanakya.core.schemas import (
    Door,
    EventKind,
    MerchantSignal,
    MissionState,
    SignalKind,
    ToolCall,
    Verdict,
)
from chanakya.missions.intake import MissionIntake
from chanakya.missions.ledger import MissionLedger, SQLiteMissionStore
from chanakya.missions.queue import MissionQueue
from chanakya.missions.scheduler import Scheduler, SimClock
from chanakya.missions.verifier import OnboardingVerifier

S = MissionState
START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata


def run(coro):
    return asyncio.run(coro)


class Rig:
    """A sales mission up to the moment the onboarding link is sent, on a simulated clock."""

    def __init__(self, consent_tools=("send_onboarding_link", "send_summary")):
        self.clock = SimClock(START)
        self.db = MockDB()
        seed(self.db)
        registry = MockToolRegistry(self.db)
        self.ledger = MissionLedger(SQLiteMissionStore())
        self.gate = ActionGate(registry, self.ledger, clock=self.clock)
        self.scheduler = Scheduler(self.ledger, self.clock)
        self.verifier = OnboardingVerifier(self.ledger, self.gate, self.scheduler)
        intake = MissionIntake(self.ledger, lambda merchant_id: merchant_from_db(registry, merchant_id))
        self.mission, _ = run(intake.ingest(MerchantSignal(
            merchant_id="mer_ramesh", kind=SignalKind.CALLBACK_REQUEST, door=Door.MERCHANT, source="mock product page")))
        mid = self.mission.id

        async def converse():
            await self.ledger.advance(mid, S.CONTACTING)
            await self.ledger.advance(mid, S.IN_CONVERSATION)
            await self.ledger.record(mid, EventKind.AI_DISCLOSED, {"text": "Main Chanakya hoon, ek AI assistant"})
            await self.ledger.record(mid, EventKind.CONSENT_GIVEN,
                                     {"tools": list(consent_tools), "utterance": "Haan, link bhej do"})
            await self.ledger.advance(mid, S.ACTION_PENDING)
            decision = await self.gate.submit(ToolCall(mission_id=mid, tool="send_onboarding_link", args={
                "merchant_id": "mer_ramesh", "product": "soundbox", "channel": "sms", "language": "hi-IN"}))
            assert decision.verdict == Verdict.EXECUTED
            await self.verifier.expect_onboarding(mid, decision.result.data["session_id"], decision.result.data["link"])
            return decision.result.data["session_id"]

        self.session_id = run(converse())

    def tick(self, **delta):
        self.clock.advance(timedelta(**delta))
        return run(self.verifier.run_due())

    @property
    def state(self):
        return self.ledger.store.get(self.mission.id).state

    def outbox(self):
        return self.db.all("SELECT body FROM outbox WHERE mission_id = ? ORDER BY rowid", self.mission.id)


def test_link_sent_reminder_then_onboarding_completes_and_mission_is_done():
    rig = Rig()
    assert rig.state == S.AWAITING_CONFIRMATION
    assert rig.tick(minutes=30) == []  # not due yet

    rig.tick(hours=2)  # first check: still pending
    assert rig.state == S.AWAITING_CONFIRMATION

    rig.tick(days=1)  # reminder goes out on WhatsApp
    assert "yaad dila rahe hain" in rig.outbox()[-1]["body"]

    complete_onboarding(rig.db, rig.session_id)  # the merchant finishes on their phone
    rig.tick(hours=2)
    mission = rig.ledger.store.get(rig.mission.id)
    assert mission.state == S.DONE and "verified" in mission.outcome
    assert rig.scheduler.pending(rig.mission.id) == []

    checks = [e.payload["status"] for e in rig.ledger.store.events(rig.mission.id) if e.kind == EventKind.VERIFICATION_CHECKED]
    assert checks == ["pending", "completed"]
    assert rig.ledger.replay(rig.mission.id).state == S.DONE


def test_never_done_without_confirmation():
    rig = Rig()
    for _ in range(10):
        rig.tick(days=1)
    assert rig.state != S.DONE


def test_after_two_reminders_it_goes_back_to_the_queue_for_a_call():
    rig = Rig()
    # day 1 check, day 2 reminder, day 3 check, day 4 reminder, then the last check 3 hours later
    for _ in range(4):
        rig.tick(days=1)
    rig.tick(hours=3)
    assert rig.state == S.SCHEDULED
    reminders = [m for m in rig.outbox() if "yaad dila" in m["body"]]
    assert len(reminders) == 2
    assert rig.scheduler.pending(rig.mission.id) == []

    queue = MissionQueue(rig.ledger, clock=rig.clock)
    entry = next(e for e in queue.entries() if e.mission.id == rig.mission.id)
    assert not entry.ready and entry.reason.startswith("callback due at")
    rig.clock.advance(timedelta(hours=1))
    entry = next(e for e in queue.entries() if e.mission.id == rig.mission.id)
    assert entry.ready and entry.reason == "callback is due"


def test_onboarding_page_triggers_an_immediate_check():
    rig = Rig()
    complete_onboarding(rig.db, rig.session_id)
    assert run(rig.verifier.check_now(rig.session_id)) == [rig.mission.id]
    assert rig.state == S.DONE
    assert run(rig.verifier.check_now(rig.session_id)) == []


def test_reminder_at_night_waits_for_calling_hours():
    rig = Rig()
    rig.tick(hours=2)  # 17:00 IST check, reminder due tomorrow 17:00 IST
    rig.clock.advance(timedelta(hours=29))  # 22:00 IST next day: reminder is late and now outside hours
    run(rig.verifier.run_due())
    assert not [m for m in rig.outbox() if "yaad dila" in m["body"]]
    nudge = next(j for j in rig.scheduler.pending(rig.mission.id) if j.kind == "nudge")
    assert nudge.due_at.astimezone(UTC).hour == 3 and nudge.due_at.astimezone(UTC).minute == 30  # 09:00 IST


def test_no_reminders_without_consent_and_stop_means_stop():
    rig = Rig(consent_tools=("send_onboarding_link",))
    rig.tick(hours=2)
    rig.tick(days=1)
    assert not [m for m in rig.outbox() if "yaad dila" in m["body"]]

    stopped = Rig()
    run(stopped.ledger.record(stopped.mission.id, EventKind.CONSENT_DECLINED, {"utterance": "Aur message mat bhejna"}))
    for _ in range(4):
        stopped.tick(days=1)
    mission = stopped.ledger.store.get(stopped.mission.id)
    assert mission.state == S.CLOSED_NOT_INTERESTED and "no more reminders" in mission.outcome
    assert not [m for m in stopped.outbox() if "yaad dila" in m["body"]]


def test_broken_messaging_does_not_retry_forever():
    rig = Rig()
    rig.db.failures["messaging"] = FailurePolicy(rate=1.0)
    for _ in range(8):
        rig.tick(days=1)
    assert rig.state == S.SCHEDULED
