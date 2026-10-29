import asyncio
import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.brain import calls_api
from chanakya.brain.mission_call import MissionCall
from chanakya.brain.scenarios import SCENARIOS, open_mission, run_all
from chanakya.core import schemas as core
from chanakya.core.config import Settings
from chanakya.missions.api import router as missions_router
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock

START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata


@pytest.fixture
def runtime(tmp_path):
    return Runtime.build(Settings(db_path=tmp_path / "ledger.db"), clock=SimClock(START))


def test_every_demo_scenario_reaches_its_outcome_through_the_real_gate_and_ledger(runtime):
    results = asyncio.run(run_all(runtime))
    assert [r.scenario for r in results] == list(SCENARIOS)
    for result in results:
        assert result.ok, (result.scenario, [name for name, ok in result.checks if not ok], result.lines)


def test_a_clear_no_closes_the_mission_and_blocks_any_later_write(runtime):
    async def go():
        mission = await open_mission(runtime, SCENARIOS["card_machine_sale"])
        call = MissionCall(runtime, mission.id)
        await call.start()
        assert "AI assistant" in await call.say("Haan ji, boliye?")
        await call.say("Nahi chahiye, mujhe interest nahi hai.")
        return mission.id, call

    mission_id, call = asyncio.run(go())
    mission = runtime.ledger.store.get(mission_id)
    kinds = [e.kind for e in runtime.ledger.store.events(mission_id)]
    assert mission.state == core.MissionState.CLOSED_NOT_INTERESTED
    assert core.EventKind.CONSENT_DECLINED in kinds
    assert core.EventKind.ACTION_DECISION not in kinds
    assert asyncio.run(call.say("Achha theek hai bhej do")) is None


@pytest.fixture
def client(runtime, monkeypatch):
    monkeypatch.setenv("CHANAKYA_TICK_SECONDS", "3600")
    monkeypatch.setattr(calls_api, "PAUSE_S", 0)
    monkeypatch.setattr(calls_api, "_llm", lambda: None)  # no network in tests
    calls_api.calls.clear()
    set_runtime(runtime)
    app = FastAPI()
    app.include_router(missions_router)
    app.include_router(calls_api.router)
    with TestClient(app) as test_client:
        yield test_client
    set_runtime(None)


def test_the_dashboard_can_list_and_run_a_scenario(client, runtime):
    assert [s["name"] for s in client.get("/api/calls/scenarios").json()] == list(SCENARIOS)
    assert client.post("/api/calls/scenarios/nope").status_code == 404
    mission_id = client.post("/api/calls/scenarios/distressed_handoff").json()["mission_id"]
    deadline = time.monotonic() + 30
    while runtime.ledger.store.get(mission_id).state != core.MissionState.ESCALATED and time.monotonic() < deadline:
        time.sleep(0.1)
    assert runtime.ledger.store.get(mission_id).state == core.MissionState.ESCALATED
    mission_id = asyncio.run(open_mission(runtime, SCENARIOS["soundbox_service"])).id
    client.post(f"/api/calls/{mission_id}/say", json={"text": "Haan ji"})
    assert client.post("/api/calls/scenarios/soundbox_service").status_code == 409  # never hijack a call in progress


def test_speaking_as_the_merchant_drives_a_live_call_on_the_mission(client, runtime):
    mission_id = asyncio.run(open_mission(runtime, SCENARIOS["callback_followup"])).id
    first = client.post(f"/api/calls/{mission_id}/say", json={"text": "Haan ji, boliye?"}).json()
    assert "AI assistant" in first["reply"] and first["state"] == "IN_CONVERSATION"
    turns = [e for e in runtime.ledger.store.events(mission_id) if e.kind == core.EventKind.TURN_COMPLETED]
    assert [t.payload["speaker"] for t in turns] == ["merchant", "agent"]
    assert client.post("/api/calls/missing/say", json={"text": "hello"}).status_code == 404
    assert client.post(f"/api/calls/{mission_id}/say", json={"text": ""}).status_code == 422
