"""Approval queue (B10): a high-risk action waits, is approved, then executes, and every step is in the ledger."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.core.config import Settings
from chanakya.core.schemas import Door, EventKind, MerchantSignal, MissionState, SignalKind, ToolCall, Verdict
from chanakya.humans.approvals import router
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock

START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata, inside calling hours
S = MissionState


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def runtime(tmp_path):
    return Runtime.build(Settings(db_path=tmp_path / "ledger.db", approval_tools=("book_field_visit",),
                                  approval_timeout_minutes=30), clock=SimClock(START))


def visit_call(runtime) -> ToolCall:
    """A mission for Gurpreet with AI disclosure and an explicit yes to a technician visit, ready to act."""
    async def go():
        mission, _ = await runtime.intake.ingest(MerchantSignal(merchant_id="mer_gurpreet", kind=SignalKind.SOUNDBOX_UNUSED,
                                                                door=Door.DATA, source="test", details={"days": 8}))
        for state in (S.CONTACTING, S.IN_CONVERSATION, S.ACTION_PENDING):
            await runtime.ledger.advance(mission.id, state)
        await runtime.ledger.record(mission.id, EventKind.AI_DISCLOSED, {"text": "Main Chanakya hoon, ek AI assistant"})
        await runtime.ledger.record(mission.id, EventKind.CONSENT_GIVEN, {"tools": ["book_field_visit"], "utterance": "Haan, bhej do"})
        return ToolCall(mission_id=mission.id, tool="book_field_visit",
                        args={"merchant_id": "mer_gurpreet", "purpose": "technician", "slot": "2026-10-30T05:30:00+00:00"})
    return run(go())


def kinds(runtime, mission_id):
    return [(e.kind, e.payload.get("verdict") or e.payload.get("status")) for e in runtime.ledger.store.events(mission_id)
            if e.kind in (EventKind.ACTION_DECISION, EventKind.APPROVAL_REQUESTED, EventKind.APPROVAL_DECIDED)]


def visits(runtime) -> int:
    return len(runtime.db.all("SELECT id FROM field_visits WHERE merchant_id = 'mer_gurpreet'"))


def test_a_high_risk_action_waits_is_approved_then_executes_all_in_the_ledger(runtime):
    call = visit_call(runtime)
    decision = run(runtime.submit(call))
    assert decision.verdict == Verdict.PENDING and visits(runtime) == 0
    assert runtime.ledger.store.get(call.mission_id).state == S.ACTION_PENDING
    [request] = runtime.approvals.list("pending")
    approved = run(runtime.approvals.approve(request["approval_id"], by="Sunita"))
    assert approved["status"] == "approved" and approved["decided_by"] == "Sunita" and approved["verdict"] == "executed"
    assert visits(runtime) == 1
    assert runtime.ledger.store.get(call.mission_id).state == S.AWAITING_CONFIRMATION
    assert kinds(runtime, call.mission_id) == [(EventKind.ACTION_DECISION, "pending"), (EventKind.APPROVAL_REQUESTED, None),
                                               (EventKind.APPROVAL_DECIDED, "approved"), (EventKind.ACTION_DECISION, "executed")]
    executed = [e for e in runtime.ledger.store.events(call.mission_id) if e.payload.get("verdict") == "executed"]
    assert executed[0].payload["reason"] == "ok, approved by Sunita"


def test_a_rejected_action_never_runs_and_a_person_takes_the_mission(runtime):
    call = visit_call(runtime)
    run(runtime.submit(call))
    [request] = runtime.approvals.list("pending")
    rejected = run(runtime.approvals.reject(request["approval_id"], by="Sunita", note="visit not needed, device is fine"))
    assert rejected["status"] == "rejected" and visits(runtime) == 0
    assert runtime.ledger.store.get(call.mission_id).state == S.ESCALATED
    [card] = runtime.handoffs.list()
    assert "rejected by Sunita" in card.reason and not card.urgent


def test_a_request_nobody_decides_expires_and_goes_to_a_person_urgently(runtime):
    call = visit_call(runtime)
    run(runtime.submit(call))
    [request] = runtime.approvals.list("pending")
    run(runtime.fast_forward(timedelta(minutes=29)))
    assert runtime.approvals.list("pending"), "still waiting before the timeout"
    run(runtime.fast_forward(timedelta(minutes=2)))
    assert runtime.approvals.list("expired")[0]["approval_id"] == request["approval_id"]
    assert runtime.handoffs.list()[0].urgent and visits(runtime) == 0
    with pytest.raises(ValueError, match="already expired"):
        run(runtime.approvals.approve(request["approval_id"], by="Sunita"))


def test_approving_twice_runs_the_action_once(runtime):
    call = visit_call(runtime)
    run(runtime.submit(call))
    approval_id = runtime.approvals.list("pending")[0]["approval_id"]

    async def both():
        return await asyncio.gather(runtime.approvals.approve(approval_id, by="Sunita"),
                                    runtime.approvals.approve(approval_id, by="Rahul"), return_exceptions=True)

    results = run(both())
    assert sum(isinstance(r, ValueError) for r in results) == 1 and visits(runtime) == 1


def test_an_approved_action_still_passes_every_check_when_it_runs(runtime):
    call = visit_call(runtime)
    run(runtime.submit(call))
    approval_id = runtime.approvals.list("pending")[0]["approval_id"]
    run(runtime.ledger.record(call.mission_id, EventKind.CONSENT_DECLINED, {"utterance": "nahi, rehne do"}))
    approved = run(runtime.approvals.approve(approval_id, by="Sunita"))
    assert approved["verdict"] == "blocked" and approved["verdict_reason"] == "merchant declined" and visits(runtime) == 0
    assert "could not run" in runtime.handoffs.list()[0].reason


def test_tools_not_listed_run_straight_away(tmp_path):
    runtime = Runtime.build(Settings(db_path=tmp_path / "ledger.db"), clock=SimClock(START))
    call = visit_call(runtime)
    assert run(runtime.submit(call)).verdict == Verdict.EXECUTED and runtime.approvals.list() == []


def test_the_api_lists_and_decides_requests(runtime):
    call = visit_call(runtime)
    run(runtime.submit(call))
    set_runtime(runtime)
    try:
        app = FastAPI()
        app.include_router(router)
        http = TestClient(app)
        [pending] = http.get("/api/approvals", params={"status": "pending"}).json()
        assert pending["tool"] == "book_field_visit" and pending["merchant_name"] == "Gurpreet Medical Hall"
        assert http.post("/api/approvals/nope/approve", json={"by": "Sunita"}).status_code == 404
        assert http.post(f"/api/approvals/{pending['approval_id']}/approve", json={"by": "Sunita"}).json()["status"] == "approved"
        assert http.post(f"/api/approvals/{pending['approval_id']}/reject", json={"by": "Rahul"}).status_code == 409
    finally:
        set_runtime(None)


def test_on_a_call_chanakya_says_the_action_waits_for_a_colleague_then_approval_completes_it(runtime):
    from chanakya.brain.scenarios import run_scenario

    result = run(run_scenario(runtime, "soundbox_service"))
    mission = runtime.ledger.store.get(result.mission_id)
    assert mission.state == S.ACTION_PENDING, "the technician visit waits for approval"
    assert any("saathi ki manzoori" in text or "colleague's approval" in text for speaker, text in result.lines if speaker == "chanakya")
    approval_id = runtime.approvals.list("pending")[0]["approval_id"]
    run(runtime.approvals.approve(approval_id, by="Sunita"))
    assert runtime.ledger.store.get(result.mission_id).state == S.AWAITING_CONFIRMATION
