import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.actions.api import router as actions_router
from chanakya.actions.systems.seed import FORMER_MERCHANTS, MERCHANTS
from chanakya.actions.systems.tools import complete_onboarding
from chanakya.core.config import Settings
from chanakya.humans.api import router as handoffs_router
from chanakya.missions.api import router as missions_router
from chanakya.missions.demo_api import router as demo_router
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock

START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANAKYA_TICK_SECONDS", "3600")
    runtime = Runtime.build(Settings(db_path=tmp_path / "ledger.db"), clock=SimClock(START))
    set_runtime(runtime)
    app = FastAPI()
    for router in (missions_router, actions_router, handoffs_router, demo_router):
        app.include_router(router)
    with TestClient(app) as test_client:
        test_client.runtime = runtime
        yield test_client
    set_runtime(None)


def callback(client, merchant_id="mer_ramesh"):
    response = client.post("/api/missions/signals", json={
        "merchant_id": merchant_id, "kind": "callback_request", "door": "merchant",
        "source": "mock product page", "details": {"product": "soundbox"},
    })
    assert response.status_code == 200, response.text
    return response.json()["mission"]["id"]


def submit(client, mission_id, tool, **args):
    args.setdefault("merchant_id", "mer_ramesh")
    return client.post("/api/actions/submit", json={"mission_id": mission_id, "tool": tool, "args": args}).json()


def test_demo_feed_and_queue(client):
    assert client.post("/api/missions/signals/demo-feed").json() == {"created": 6, "missions": 6, "winback": []}
    assert client.post("/api/missions/signals/demo-feed").json()["created"] == 0
    callback(client)
    missions = client.get("/api/missions").json()
    assert len(missions) == 7
    assert client.get("/api/missions/queue/next").json()["mission"]["card"]["signal_kind"] == "callback_request"
    closed = [m for m in missions if m["mission"]["state"] == "CLOSED_NOT_INTERESTED"]
    assert closed[0]["queue"] is None and closed[0]["mission"]["outcome"] == "do-not-call"


def test_full_mission_over_http_reaches_done(client):
    mission_id = callback(client)
    for state in ("CONTACTING", "IN_CONVERSATION"):
        assert client.post(f"/api/missions/{mission_id}/advance", json={"state": state}).status_code == 200
    client.post(f"/api/missions/{mission_id}/events", json={"kind": "ai_disclosed", "payload": {"text": "AI"}})
    blocked = submit(client, mission_id, "send_onboarding_link", product="soundbox")
    assert blocked["verdict"] == "blocked" and blocked["reason"] == "no explicit consent for this action"
    client.post(f"/api/missions/{mission_id}/events", json={
        "kind": "consent_given", "payload": {"tools": ["send_onboarding_link", "send_onboarding_reminder"], "utterance": "Haan"}})
    client.post(f"/api/missions/{mission_id}/advance", json={"state": "ACTION_PENDING"})
    sent = submit(client, mission_id, "send_onboarding_link", product="soundbox")
    assert sent["verdict"] == "executed"
    assert client.get(f"/api/missions/{mission_id}").json()["mission"]["state"] == "AWAITING_CONFIRMATION"
    assert client.get("/api/actions/outbox", params={"mission_id": mission_id}).json()[0]["link"] == sent["result"]["data"]["link"]

    complete_onboarding(client.runtime.db, sent["result"]["data"]["session_id"])
    assert client.get("/api/missions/clock").json()["now"] == START.isoformat()
    assert client.post("/api/missions/clock/advance", json={"minutes": 150}).json()["jobs_run"] == 1
    detail = client.get(f"/api/missions/{mission_id}").json()
    assert detail["mission"]["state"] == "DONE"
    assert [d["verdict"] for d in client.get(f"/api/actions/audit/{mission_id}").json()] == [
        "blocked", "executed", "executed"]  # blocked send, send, verification read


def test_mock_onboarding_page_completes_and_verifies_the_mission(client):
    mission_id = callback(client)
    for state in ("CONTACTING", "IN_CONVERSATION"):
        client.post(f"/api/missions/{mission_id}/advance", json={"state": state})
    client.post(f"/api/missions/{mission_id}/events", json={"kind": "ai_disclosed", "payload": {}})
    client.post(f"/api/missions/{mission_id}/events", json={"kind": "consent_given", "payload": {"tool": "send_onboarding_link"}})
    client.post(f"/api/missions/{mission_id}/advance", json={"state": "ACTION_PENDING"})
    session_id = submit(client, mission_id, "send_onboarding_link", product="soundbox")["result"]["data"]["session_id"]

    page = client.get(f"/api/demo/onboarding/{session_id}").json()
    assert page["session"]["status"] == "pending" and page["merchant"]["name"] == "Ramesh Kirana Store"
    done = client.post(f"/api/demo/onboarding/{session_id}/complete").json()
    assert done["session"]["status"] == "completed" and done["verified_missions"] == [mission_id]
    assert client.get(f"/api/missions/{mission_id}").json()["mission"]["state"] == "DONE"
    assert client.post(f"/api/demo/onboarding/{session_id}/complete").json()["verified_missions"] == []
    assert client.get("/api/demo/onboarding/onb_missing").status_code == 404


def test_errors_map_to_http_codes(client):
    mission_id = callback(client)
    assert client.get("/api/missions/m_missing").status_code == 404
    assert client.post(f"/api/missions/{mission_id}/advance", json={"state": "DONE"}).status_code == 409
    assert client.post(f"/api/missions/{mission_id}/events", json={"kind": "state_changed"}).status_code == 422
    assert client.post("/api/missions/signals", json={
        "merchant_id": "mer_nobody", "kind": "callback_request", "door": "merchant", "source": "x"}).status_code == 404
    assert client.post("/api/missions/signals", json={
        "merchant_id": "mer_ramesh", "kind": "callback_request", "door": "data", "source": "x"}).status_code == 422
    assert submit(client, mission_id, "give_free_rental")["verdict"] == "rejected"
    assert len(client.get("/api/actions/tools").json()) == 17
    assert len(client.get("/api/actions/merchants").json()) == len(MERCHANTS) + len(FORMER_MERCHANTS)


def test_handoff_flow(client):
    mission_id = callback(client)
    for state in ("CONTACTING", "IN_CONVERSATION"):
        client.post(f"/api/missions/{mission_id}/advance", json={"state": state})
    card = client.post("/api/handoffs/escalate", json={"mission_id": mission_id, "reason": "asked for a human",
                                                       "urgent": True}).json()
    assert card["status"] == "open" and card["urgent"]
    assert client.post(f"/api/handoffs/{card['id']}/resolve", json={"resolution": "x"}).status_code == 409
    assert client.post(f"/api/handoffs/{card['id']}/claim", json={"agent": "Sunita"}).json()["status"] == "claimed"
    assert client.post(f"/api/handoffs/{card['id']}/resolve", json={"resolution": "Sold"}).json()["status"] == "resolved"
    assert client.get("/api/handoffs", params={"status": "resolved"}).json()[0]["id"] == card["id"]
    assert client.post("/api/handoffs/ho_missing/claim", json={"agent": "x"}).status_code == 404


def test_stream_replays_then_delivers_live_events(client):
    mission_id = callback(client)
    with client.websocket_connect(f"/api/missions/stream?mission_id={mission_id}&replay=10") as socket:
        replayed = [socket.receive_json()["kind"] for _ in range(2)]
        assert replayed == ["mission_created", "signal_received"]
        client.post(f"/api/missions/{mission_id}/advance", json={"state": "CONTACTING"})
        live = socket.receive_json()
        assert live["kind"] == "state_changed" and live["payload"]["to"] == "CONTACTING" and live["seq"] == 3


def test_backend_mounts_routes_only_when_enabled():
    probe = "import backend.main as m; print('/api/missions' in m.app.openapi()['paths'])"
    results = {}
    for flag in ("false", "true"):
        env = os.environ | {"MISSIONS_ENABLED": flag, "OPENROUTER_API_KEY": "", "SARVAM_API_KEY": ""}
        out = subprocess.run([sys.executable, "-c", probe], cwd=REPO, env=env, capture_output=True, text=True, check=True)
        results[flag] = out.stdout.strip().splitlines()[-1]
    assert results == {"false": "False", "true": "True"}
