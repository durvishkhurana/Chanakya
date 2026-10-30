"""A small seeded ledger: real calls through the mission system, and the API returns its insights."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.core.config import Settings
from chanakya.insights.api import router
from chanakya.insights.seed import START, seed_ledger
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock


def test_a_seeded_ledger_has_real_calls_and_the_api_summarises_it(tmp_path, monkeypatch):
    monkeypatch.setenv("WORRY_SCORER", "lexical")  # no model download in tests
    runtime = Runtime.build(Settings(db_path=tmp_path / "ledger.db", calling_hours=(9, 21)), clock=SimClock(START))
    states = asyncio.run(seed_ledger(runtime, seed=3, rounds=1, limit=4))
    assert sum(states.values()) == 4 and "CREATED" not in states, "every seeded mission was called"
    assert all(m.card.merchant_name.endswith("(simulated)") for m in runtime.ledger.store.list())
    set_runtime(runtime)
    try:
        app = FastAPI()
        app.include_router(router)
        data = TestClient(app).get("/api/insights").json()
    finally:
        set_runtime(None)
    assert data["headline"]["missions"] == 4 and data["headline"]["talked"] == 4
    assert data["funnel"]["overall"][0] == {"stage": "opened", "label": "Mission opened", "missions": 4}
    assert data["worries"]["calls"] == 4 and data["worries"]["by_day"][0]["day"] == "2026-10-26"
    assert set(data) == {"generated_at", "headline", "worries", "funnel", "moves", "escalations", "leaving"}
