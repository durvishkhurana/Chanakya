"""Win-back missions: churn detection, the holdout group and the system-confirmed DONE (task W1). Mock data only."""

import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.actions.systems.tools import resolve_ticket
from chanakya.core.config import Settings
from chanakya.core.schemas import (
    Door,
    EventKind,
    MerchantSignal,
    MissionState,
    MissionType,
    SignalKind,
    ToolCall,
    Verdict,
    utcnow,
)
from chanakya.missions.api import router as missions_router
from chanakya.missions.churn import DEMO_SEED, ChurnDetector, holdout_mission_id, in_holdout, leaving_reasons
from chanakya.missions.demo_api import router as demo_router
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock

S = MissionState


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def runtime(tmp_path):
    # The seed dates former merchants relative to the real date, so the simulated clock starts there too.
    return Runtime.build(Settings(db_path=tmp_path / "ledger.db", winback_enabled=True), clock=SimClock(utcnow()))


def add_former(runtime, merchant_id, days, dnc=0, device="returned"):
    churned = (runtime.clock() - timedelta(days=days)).isoformat()
    runtime.db.write("INSERT INTO merchants (id, name, business_type, city, language, start_hour, end_hour, do_not_call, "
                     "phone_last4, relationship, churned_at) VALUES (?, ?, 'kirana', 'Patna', 'hi-IN', 9, 21, ?, NULL, "
                     "'former', ?)", merchant_id, f"{merchant_id} (mock)", dnc, churned)
    runtime.db.write("INSERT INTO devices VALUES (?, ?, 'soundbox', ?, ?, 'closed')", f"dev_{merchant_id}", merchant_id,
                     device, churned)


def decisions(runtime, clock=None):
    detector = ChurnDetector(runtime.db, runtime.ledger, runtime.intake, runtime.handoffs, clock or runtime.clock)
    return {d.merchant_id: d for d in run(detector.scan())}


def test_the_demo_merchants_go_to_a_call_a_person_or_the_holdout(runtime):
    routed = decisions(runtime)
    assert {m: d.decision for m, d in routed.items()} == {
        "mer_harish": "call", "mer_meena": "call", "mer_joginder": "holdout", "mer_kavita": "handoff"}
    for merchant_id in ("mer_harish", "mer_meena"):
        mission = runtime.ledger.store.get(routed[merchant_id].mission_id)
        assert mission.card.mission_type == MissionType.WIN_BACK and mission.state == S.CREATED
    held = runtime.ledger.store.events(holdout_mission_id("mer_joginder"))
    assert [e.kind for e in held] == [EventKind.HOLDOUT_ASSIGNED] and held[0].payload["seed"] == DEMO_SEED
    assert not [m for m in runtime.ledger.store.list() if m.card.merchant_id == "mer_joginder"]  # never called
    kavita = runtime.ledger.store.get(routed["mer_kavita"].mission_id)
    cards = [c for c in runtime.handoffs.list() if c.mission_id == kavita.id]
    assert kavita.state == S.ESCALATED and cards and "tkt_kavita_open" in cards[0].reason
    # The existing demo merchants are customers, not former ones.
    assert not {"mer_ramesh", "mer_gurpreet", "mer_anita", "mer_lakshmi"} & set(routed)


def test_a_second_scan_changes_nothing(runtime):
    first = decisions(runtime)
    missions, events = len(runtime.ledger.store.list()), len(runtime.ledger.store.events())
    again = decisions(runtime)
    assert {d.decision for d in again.values()} == {"skip"}
    assert {d.reason for d in again.values()} == {"win-back contact in the last 90 days"}
    assert len(runtime.ledger.store.list()) == missions and len(runtime.ledger.store.events()) == events
    assert set(first) == set(again)


def test_eligibility_edges(runtime):
    for merchant_id, days in (("mer_t13", 13), ("mer_t15", 15), ("mer_t179", 179), ("mer_t181", 181)):
        add_former(runtime, merchant_id, days)
    add_former(runtime, "mer_tdnc", 30, dnc=1)
    routed = decisions(runtime)
    assert routed["mer_t13"].reason == "churned under 14 days ago"
    assert routed["mer_t181"].reason == "churned over 180 days ago"
    assert routed["mer_t15"].decision in {"call", "holdout"} and routed["mer_t179"].decision in {"call", "holdout"}
    assert routed["mer_tdnc"] .decision == "skip" and routed["mer_tdnc"].reason == "on do-not-call"
    assert not [m for m in runtime.ledger.store.list() if m.card.merchant_id == "mer_tdnc"]


def test_a_win_back_older_than_90_days_does_not_block_a_new_one(runtime):
    add_former(runtime, "mer_tback", 20)
    first = decisions(runtime)["mer_tback"]
    assert first.decision in {"call", "holdout"}
    later = runtime.clock() + timedelta(days=91)
    runtime.db.write("UPDATE merchants SET churned_at = ? WHERE id = 'mer_tback'", (later - timedelta(days=20)).isoformat())
    assert decisions(runtime, clock=lambda: later)["mer_tback"].decision in {"call", "holdout"}


def test_a_merchant_who_stopped_paying_counts_as_former_without_a_crm_flag(runtime):
    runtime.db.write("INSERT INTO merchants (id, name, business_type, city, language, start_hour, end_hour) "
                     "VALUES ('mer_tidle', 'Idle (mock)', 'kirana', 'Patna', 'hi-IN', 9, 21)")
    runtime.db.write("INSERT INTO devices VALUES ('dev_tidle', 'mer_tidle', 'soundbox', 'online', ?, 'paid')",
                     (runtime.clock() - timedelta(days=65)).isoformat())
    assert decisions(runtime)["mer_tidle"].decision in {"call", "holdout"}


def test_the_holdout_is_deterministic_for_a_seed_and_about_one_in_five():
    ids = [f"mer_{i}" for i in range(2000)]
    picked = [i for i in ids if in_holdout(i, seed=7)]
    assert picked == [i for i in ids if in_holdout(i, seed=7)]
    assert picked != [i for i in ids if in_holdout(i, seed=8)]
    assert 0.17 < len(picked) / len(ids) < 0.23
    assert in_holdout("mer_joginder", DEMO_SEED) and not in_holdout("mer_harish", DEMO_SEED)


# ── DONE only on system confirmation ─────────────────────────────────────


def fixed(runtime, merchant_id="mer_harish", tool="raise_ticket"):
    """A win-back mission whose fix ran with consent; returns the mission id and the call time."""
    signal = MerchantSignal(merchant_id=merchant_id, kind=SignalKind.MERCHANT_CHURNED, door=Door.DATA, source="test",
                            details={"days": 30})
    mission, _ = run(runtime.intake.ingest(signal))
    mid = mission.id

    async def converse():
        for state in (S.CONTACTING, S.IN_CONVERSATION):
            await runtime.ledger.advance(mid, state)
        await runtime.ledger.record(mid, EventKind.AI_DISCLOSED, {"text": "Main ek AI assistant hoon"})
        await runtime.ledger.record(mid, EventKind.CONSENT_GIVEN, {"tool": tool, "utterance": "Haan, ticket bana do"})
        await runtime.ledger.advance(mid, S.ACTION_PENDING)
        args = {"merchant_id": merchant_id, "category": "device", "description": "Soundbox not announcing payments"}
        return await runtime.submit(ToolCall(mission_id=mid, tool=tool, args=args))

    decision = run(converse())
    assert decision.verdict == Verdict.EXECUTED
    return mid, runtime.clock(), decision.result.data.get("ticket_id")


def state(runtime, mid):
    return runtime.ledger.store.get(mid).state


def test_done_when_the_ticket_raised_on_the_call_is_resolved(runtime):
    mid, _, ticket_id = fixed(runtime)
    assert state(runtime, mid) == S.AWAITING_CONFIRMATION
    resolve_ticket(runtime.db, ticket_id)
    assert run(runtime.verifier.check_winback_now(ticket_id)) == [mid]
    mission = runtime.ledger.store.get(mid)
    assert mission.state == S.DONE and "ticketing system" in mission.outcome


def test_done_when_the_device_is_active_again(runtime):
    mid, _, _ = fixed(runtime)
    runtime.db.write("UPDATE devices SET status = 'online' WHERE id = 'dev_harish_sb'")
    run(runtime.verifier.run_mission_now(mid))
    assert state(runtime, mid) == S.DONE and "devices system" in runtime.ledger.store.get(mid).outcome


def test_done_on_a_payment_within_14_days_of_the_call_and_not_after(runtime):
    mid, since, _ = fixed(runtime, merchant_id="mer_meena")  # her device was online all along
    runtime.db.write("UPDATE devices SET last_payment_at = ? WHERE id = 'dev_meena_sb'", (since + timedelta(days=20)).isoformat())
    run(runtime.verifier.run_mission_now(mid))
    assert state(runtime, mid) == S.AWAITING_CONFIRMATION  # outside the window, and "online" was no change
    runtime.db.write("UPDATE devices SET last_payment_at = ? WHERE id = 'dev_meena_sb'", (since + timedelta(days=3)).isoformat())
    run(runtime.verifier.run_mission_now(mid))
    assert state(runtime, mid) == S.DONE and "14 days" in runtime.ledger.store.get(mid).outcome


def test_never_done_without_a_system_and_back_to_the_queue_after_the_re_checks(runtime):
    mid, _, _ = fixed(runtime)
    for _ in range(3):
        run(runtime.verifier.run_mission_now(mid))
    assert state(runtime, mid) == S.SCHEDULED
    checks = [e.payload["status"] for e in runtime.ledger.store.events(mid) if e.kind == EventKind.VERIFICATION_CHECKED]
    assert checks == ["not yet", "not yet", "not yet"]
    assert runtime.scheduler.pending(mid) == []
    assert runtime.db.all("SELECT id FROM outbox WHERE mission_id = ?", mid) == []  # no messages without consent
    callbacks = [e for e in runtime.ledger.store.events(mid) if e.kind == EventKind.FOLLOWUP_SCHEDULED
                 and e.payload.get("kind") == "callback"]
    assert callbacks and datetime.fromisoformat(callbacks[-1].payload["due_at"]) > runtime.clock()


def test_a_sales_ticket_does_not_start_a_win_back_check(runtime):
    signal = MerchantSignal(merchant_id="mer_lakshmi", kind=SignalKind.RENTAL_MISSED, door=Door.DATA, source="test")
    mission, _ = run(runtime.intake.ingest(signal))
    run(runtime.ledger.advance(mission.id, S.CONTACTING))
    run(runtime.ledger.advance(mission.id, S.IN_CONVERSATION))
    run(runtime.ledger.record(mission.id, EventKind.AI_DISCLOSED, {"text": "AI"}))
    run(runtime.ledger.record(mission.id, EventKind.CONSENT_GIVEN, {"tool": "raise_ticket", "utterance": "Haan"}))
    run(runtime.submit(ToolCall(mission_id=mission.id, tool="raise_ticket", args={
        "merchant_id": "mer_lakshmi", "category": "settlement", "description": "Late settlement"})))
    assert runtime.scheduler.pending(mission.id) == []


# ── API and the reasons card ─────────────────────────────────────────────


@pytest.fixture
def client(runtime, monkeypatch):
    monkeypatch.setenv("CHANAKYA_TICK_SECONDS", "3600")
    set_runtime(runtime)
    app = FastAPI()
    app.include_router(missions_router)
    app.include_router(demo_router)
    with TestClient(app) as test_client:
        yield test_client
    set_runtime(None)


def test_the_demo_feed_runs_the_churn_scan_and_the_card_reads_the_ledger(client, runtime):
    loaded = client.post("/api/missions/signals/demo-feed").json()
    assert {d["merchant_id"]: d["decision"] for d in loaded["winback"]}["mer_joginder"] == "holdout"
    summary = client.get("/api/missions/winback").json()
    assert summary["enabled"] and [h["merchant_id"] for h in summary["holdouts"]] == ["mer_joginder"]
    assert summary["reasons"]["total"] == 0
    for reason, city in (("device_issue", "Patna"), ("device_issue", "Bhopal"), ("not_needed", "Bhopal")):
        run(runtime.ledger.record("m_x", EventKind.LEAVING_REASON_RECORDED,
                                  {"reason": reason, "city": city, "product": "soundbox"}))
    reasons = client.get("/api/missions/winback").json()["reasons"]
    assert reasons == {"total": 3, "by_reason": {"device_issue": 2, "not_needed": 1},
                       "by_city": {"Bhopal": 2, "Patna": 1}, "by_product": {"soundbox": 3}}
    assert leaving_reasons(runtime.ledger) == reasons


def test_the_mock_ticketing_page_verifies_a_waiting_win_back(client, runtime):
    mid, _, ticket_id = fixed(runtime)
    resolved = client.post(f"/api/demo/tickets/{ticket_id}/resolve").json()
    assert resolved["ticket"]["status"] == "resolved" and resolved["verified_missions"] == [mid]
    assert client.post("/api/demo/tickets/tkt_missing/resolve").status_code == 404


def test_the_scan_is_refused_while_win_back_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANAKYA_TICK_SECONDS", "3600")
    runtime = Runtime.build(Settings(db_path=tmp_path / "off.db"), clock=SimClock(utcnow()))
    set_runtime(runtime)
    app = FastAPI()
    app.include_router(missions_router)
    with TestClient(app) as client:
        assert client.post("/api/missions/winback/scan").status_code == 409
        assert client.post("/api/missions/signals/demo-feed").json()["winback"] == []
        assert client.get("/api/missions/winback").json()["enabled"] is False
    set_runtime(None)
    assert not [m for m in runtime.ledger.store.list() if m.card.mission_type == MissionType.WIN_BACK]
