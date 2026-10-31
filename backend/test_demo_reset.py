"""Reset: a finished demo mission goes back in the queue and can run again; the ledger keeps the old run."""

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import demo_reset
from chanakya.brain.scenarios import run_scenario
from chanakya.core.config import Settings
from chanakya.core.schemas import EventKind, MissionState
from chanakya.missions.runtime import Runtime, set_runtime
from chanakya.missions.scheduler import SimClock

START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime.build(Settings(db_path=Path(self.tmp.name) / "ledger.db"), clock=SimClock(START))

    def tearDown(self):
        set_runtime(None)
        self.runtime.db.conn.close()
        self.runtime.ledger.store.conn.close()
        self.tmp.cleanup()

    def test_a_finished_sale_goes_back_to_the_queue_and_can_be_sold_again(self):
        first = asyncio.run(run_scenario(self.runtime, "card_machine_sale"))
        self.assertTrue(first.ok, first.checks)
        db = self.runtime.db
        self.assertEqual(db.one("SELECT has_card_machine FROM merchants WHERE id = 'mer_anita'")["has_card_machine"], 1)
        events_before = len(self.runtime.ledger.store.events(first.mission_id))

        new = asyncio.run(demo_reset.reset_mission(self.runtime, first.mission_id))

        old = self.runtime.ledger.store.get(first.mission_id)
        self.assertEqual((old.state, old.outcome), (MissionState.DONE, "reset"))
        old_events = self.runtime.ledger.store.events(first.mission_id)
        self.assertEqual(len(old_events), events_before + 1, "the old run's events are kept, plus one note")
        self.assertEqual(old_events[-1].kind, EventKind.NOTE)
        self.assertEqual(old_events[-1].payload["replaced_by"], new.id)
        self.assertEqual((new.state, new.card), (MissionState.CREATED, old.card))
        self.assertEqual(db.one("SELECT has_card_machine FROM merchants WHERE id = 'mer_anita'")["has_card_machine"], 0)
        self.assertIsNone(db.one("SELECT id FROM onboarding_sessions WHERE mission_id = ?", first.mission_id))
        self.assertFalse([j for j in self.runtime.scheduler.pending() if j.mission_id == first.mission_id])

        second = asyncio.run(run_scenario(self.runtime, "card_machine_sale"))
        self.assertEqual(second.mission_id, new.id, "the scenario picks up the fresh mission from the queue")
        self.assertTrue(second.ok, second.checks)

    def test_an_open_call_is_closed_and_unknown_missions_are_refused(self):
        result = asyncio.run(run_scenario(self.runtime, "distressed_handoff"))
        open_mission = asyncio.run(self.runtime.ledger.create(self.runtime.ledger.store.get(result.mission_id).card))
        new = asyncio.run(demo_reset.reset_mission(self.runtime, open_mission.id))
        old = self.runtime.ledger.store.get(open_mission.id)
        self.assertEqual((old.state, old.outcome), (MissionState.FAILED, "reset"))
        self.assertEqual(new.state, MissionState.CREATED)
        with self.assertRaises(LookupError):
            asyncio.run(demo_reset.reset_mission(self.runtime, "m_missing"))

    def test_only_the_laptop_can_reset(self):
        set_runtime(self.runtime)
        app = FastAPI()
        app.include_router(demo_reset.router)
        client = TestClient(app)
        mission = asyncio.run(run_scenario(self.runtime, "distressed_handoff")).mission_id
        tunnel = client.post(f"/api/demo-tools/missions/{mission}/reset", headers={"cf-connecting-ip": "1.2.3.4"})
        self.assertEqual(tunnel.status_code, 403)
        self.assertEqual(client.post("/api/demo-tools/missions/m_missing/reset").status_code, 404)
        reply = client.post(f"/api/demo-tools/missions/{mission}/reset").json()
        self.assertEqual(reply["replaced"], mission)
        self.assertEqual(self.runtime.ledger.store.get(reply["mission_id"]).state, MissionState.CREATED)


if __name__ == "__main__":
    unittest.main()
