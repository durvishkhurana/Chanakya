import asyncio
from datetime import UTC, datetime

import pytest

from chanakya.actions.audit import audit_trail
from chanakya.actions.gate import ActionGate
from chanakya.actions.registry import MockToolRegistry
from chanakya.actions.systems.db import FailurePolicy, MockDB
from chanakya.actions.systems.seed import seed
from chanakya.core.fakes import FakePlanner
from chanakya.core.interfaces import SafetyGate
from chanakya.core.schemas import (
    Door,
    EventKind,
    MissionCard,
    MissionState,
    MissionType,
    SignalKind,
    ToolCall,
    Verdict,
)
from chanakya.missions.ledger import MissionLedger, SQLiteMissionStore

AFTERNOON_IST = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata
NIGHT_IST = datetime(2026, 10, 29, 17, 30, tzinfo=UTC)  # 23:00 in Asia/Kolkata


def run(coro):
    return asyncio.run(coro)


class Rig:
    def __init__(self, merchant_id="mer_ramesh", product="soundbox", clock=AFTERNOON_IST, planner=None):
        self.db = MockDB()
        seed(self.db)
        self.registry = MockToolRegistry(self.db)
        self.ledger = MissionLedger(SQLiteMissionStore())
        self.gate = ActionGate(self.registry, self.ledger, planner=planner, clock=lambda: clock)
        card = MissionCard(merchant_id=merchant_id, merchant_name="x", door=Door.MERCHANT,
                           signal_kind=SignalKind.CALLBACK_REQUEST, signal_id="sig", mission_type=MissionType.SALES,
                           goal="Sell", product=product, why_now="callback")
        self.mission = run(self.ledger.create(card))
        self.merchant_id = merchant_id

    def disclose(self):
        run(self.ledger.record(self.mission.id, EventKind.AI_DISCLOSED, {"text": "Main ek AI assistant hoon"}))

    def consent(self, tool, given=True):
        kind = EventKind.CONSENT_GIVEN if given else EventKind.CONSENT_DECLINED
        run(self.ledger.record(self.mission.id, kind, {"tool": tool, "utterance": "Haan, bhej do link"}))

    def submit(self, tool, **args):
        args.setdefault("merchant_id", self.merchant_id)
        return run(self.gate.submit(ToolCall(mission_id=self.mission.id, tool=tool, args=args)))


def link_args(**extra):
    return {"product": "soundbox", "channel": "sms", "language": "hi-IN"} | extra


def test_gate_satisfies_protocol():
    assert isinstance(Rig().gate, SafetyGate)


def test_reads_run_without_consent():
    decision = Rig().submit("get_device_status")
    assert decision.verdict == Verdict.EXECUTED and decision.result.ok


def test_write_needs_disclosure_then_consent():
    rig = Rig()
    assert rig.submit("send_onboarding_link", **link_args()).reason == "AI disclosure not recorded"
    rig.disclose()
    assert rig.submit("send_onboarding_link", **link_args()).reason == "no explicit consent for this action"
    rig.consent("send_onboarding_link")
    decision = rig.submit("send_onboarding_link", **link_args())
    assert decision.verdict == Verdict.EXECUTED and decision.result.data["link"].startswith("/demo/onboard/")


def test_consent_is_per_tool_and_can_be_withdrawn():
    rig = Rig()
    rig.disclose()
    rig.consent("book_callback")
    assert rig.submit("send_onboarding_link", **link_args()).verdict == Verdict.BLOCKED
    rig.consent("send_onboarding_link")
    rig.consent("send_onboarding_link", given=False)
    assert rig.submit("send_onboarding_link", **link_args()).reason == "merchant declined"


def test_one_consent_can_cover_named_tools_and_a_blanket_decline_covers_all():
    rig = Rig()
    rig.disclose()
    run(rig.ledger.record(rig.mission.id, EventKind.CONSENT_GIVEN,
                          {"tools": ["send_onboarding_link", "send_summary"], "utterance": "Haan, bhejo aur yaad dila dena"}))
    assert rig.submit("send_onboarding_link", **link_args()).verdict == Verdict.EXECUTED
    assert rig.submit("send_summary", text="Reminder").verdict == Verdict.EXECUTED
    assert rig.submit("book_callback", due_at="2026-10-30T10:00:00+00:00").reason == "no explicit consent for this action"
    run(rig.ledger.record(rig.mission.id, EventKind.CONSENT_DECLINED, {"utterance": "Ab mat bhejna kuch"}))
    assert rig.submit("send_summary", text="Reminder").reason == "merchant declined"


def test_calling_hours_and_do_not_call_block_contact():
    night = Rig(clock=NIGHT_IST)
    night.disclose()
    night.consent("send_onboarding_link")
    assert "outside calling hours" in night.submit("send_onboarding_link", **link_args()).reason

    dnc = Rig(merchant_id="mer_baldev")
    dnc.disclose()
    dnc.consent("send_onboarding_link")
    assert dnc.submit("send_onboarding_link", **link_args()).reason == "merchant is on do-not-call"


def test_suitability_blocks_selling_a_device_the_merchant_has():
    rig = Rig(merchant_id="mer_gurpreet")
    rig.disclose()
    rig.consent("send_onboarding_link")
    assert rig.submit("send_onboarding_link", **link_args()).reason == "merchant already has a soundbox"


def test_actions_cannot_touch_another_merchant():
    rig = Rig()
    assert rig.submit("get_device_status", merchant_id="mer_anita").reason == "merchant does not match the mission"


def test_sensitive_data_is_blocked():
    rig = Rig()
    rig.disclose()
    rig.consent("send_summary")
    blocked = rig.submit("send_summary", text="Kripya apna OTP batayein")
    assert blocked.reason == "arguments mention sensitive data"
    blocked = rig.submit("send_summary", text="Card 4111111111111111 se payment")
    assert blocked.verdict == Verdict.BLOCKED
    assert rig.submit("send_summary", text="Dhanyavaad, link bhej diya hai").verdict == Verdict.EXECUTED


def test_unknown_tools_bad_arguments_and_unknown_missions_are_rejected():
    rig = Rig()
    assert rig.submit("give_free_rental").verdict == Verdict.REJECTED
    assert rig.submit("create_lead", product="loan").verdict == Verdict.REJECTED
    orphan = run(rig.gate.submit(ToolCall(mission_id="m_nowhere", tool="get_device_status",
                                          args={"merchant_id": "mer_ramesh"})))
    assert orphan.reason == "unknown mission"


def test_closed_missions_take_no_actions():
    rig = Rig()
    run(rig.ledger.close(rig.mission.id, MissionState.CLOSED_NOT_INTERESTED, outcome="said no"))
    assert rig.submit("get_device_status").reason == "mission is CLOSED_NOT_INTERESTED"


@pytest.mark.parametrize(("allow", "verdict"), [(True, Verdict.EXECUTED), (False, Verdict.BLOCKED)])
def test_irreversible_writes_get_a_second_look(allow, verdict):
    rig = Rig(planner=FakePlanner(allow_writes=allow))
    rig.disclose()
    rig.consent("send_onboarding_link")
    rig.consent("create_lead")
    assert rig.submit("send_onboarding_link", **link_args()).verdict == verdict
    # Reversible writes skip the reconsideration step.
    assert rig.submit("create_lead", product="soundbox").verdict == Verdict.EXECUTED


def test_system_failure_is_reported_as_failed():
    rig = Rig()
    rig.db.failures["devices"] = FailurePolicy(rate=1.0)
    decision = rig.submit("get_device_status")
    assert decision.verdict == Verdict.FAILED and "unavailable" in decision.reason


def test_every_attempt_lands_in_the_audit_trail():
    rig = Rig()
    rig.submit("get_device_status")
    rig.submit("send_onboarding_link", **link_args())
    rig.submit("give_free_rental")
    trail = audit_trail(rig.ledger.store, rig.mission.id)
    assert [d.verdict for d in trail] == [Verdict.EXECUTED, Verdict.BLOCKED, Verdict.REJECTED]
    assert [d.call.tool for d in trail] == ["get_device_status", "send_onboarding_link", "give_free_rental"]


def test_the_onboarding_reminder_is_a_contact_write_with_its_own_consent():
    rig = Rig(merchant_id="mer_imran")
    rig.disclose()
    reminder = {"session_id": "onb_imran_stalled"}
    assert rig.submit("send_onboarding_reminder", **reminder).reason == "no explicit consent for this action"
    rig.consent("send_summary")
    assert rig.submit("send_onboarding_reminder", **reminder).reason == "no explicit consent for this action"
    rig.consent("send_onboarding_reminder")
    assert rig.submit("send_onboarding_reminder", **reminder).verdict == Verdict.EXECUTED
    night = Rig(merchant_id="mer_imran", clock=NIGHT_IST)
    night.disclose()
    night.consent("send_onboarding_reminder")
    assert "outside calling hours" in night.submit("send_onboarding_reminder", **reminder).reason
