"""Demo tools: the phone link tunnel and the saved run log with its checks. Never starts a real tunnel."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import phone_link
from backend.phone_link import INSTALL_HINT, Tunnel
from backend.run_log import RunLog, log_problems, review

URL = "https://quiet-river-sample-words.trycloudflare.com"


class FakeProcess:
    """Stands in for cloudflared: prints `lines` to stderr, then runs until terminated (or exits if `exits`)."""

    def __init__(self, lines, exits=False):
        self.done = threading.Event()
        if exits:
            self.done.set()
        self.lines = lines
        self.terminated = False

    @property
    def stderr(self):
        yield from (line + "\n" for line in self.lines)
        self.done.wait(5)

    def poll(self):
        return 0 if self.done.is_set() else None

    def terminate(self):
        self.terminated = True
        self.done.set()

    def wait(self, timeout=None):
        return 0

    kill = terminate


def started(lines, exits=False):
    process = FakeProcess(lines, exits)
    return process, patch.multiple(phone_link.subprocess, Popen=lambda *a, **k: process), \
        patch.object(phone_link.shutil, "which", lambda name: "cloudflared.exe")


class TunnelTest(unittest.TestCase):
    def test_start_returns_url_once_registered_and_stop_terminates(self):
        process, popen, which = started([f"INF |  {URL}  |", "INF Registered tunnel connection connIndex=0"])
        tunnel = Tunnel()
        with popen, which:
            self.assertEqual(tunnel.start(3000, timeout=5), {"running": True, "url": URL})
            self.assertEqual(tunnel.start(3000, timeout=5)["url"], URL)  # already open: reused
            self.assertEqual(tunnel.stop(), {"running": False, "url": None})
        self.assertTrue(process.terminated)

    def test_missing_cloudflared_says_how_to_install(self):
        with patch.object(phone_link.shutil, "which", lambda name: None), \
                self.assertRaisesRegex(RuntimeError, "winget install"):
            Tunnel().start(3000, timeout=1)
        self.assertIn("cloudflared", INSTALL_HINT)

    def test_process_that_exits_reports_its_output(self):
        _, popen, which = started(["ERR failed to request quick Tunnel"], exits=True)
        with popen, which, self.assertRaisesRegex(RuntimeError, "failed to request quick Tunnel"):
            Tunnel().start(3000, timeout=2)

    def test_only_the_laptop_can_open_or_close_the_link(self):
        app = FastAPI()
        app.include_router(phone_link.router)
        client = TestClient(app)
        self.assertEqual(client.post("/api/phone-link/stop", headers={"cf-connecting-ip": "1.2.3.4"}).status_code, 403)
        self.assertEqual(client.post("/api/phone-link/start", headers={"cf-ray": "abc"}).status_code, 403)
        self.assertEqual(client.post("/api/phone-link/stop").json(), {"running": False, "url": None})


def turn(seq, speaker, text, at, move=None):
    return {"seq": seq, "kind": "turn_completed", "at": at,
            "payload": {"speaker": speaker, "text": text, "move": move, "at": at}}


def good_call():
    return [
        turn(1, "merchant", "Haan ji, boliye?", "2026-10-31T06:00:00Z"),
        {"seq": 2, "kind": "ai_disclosed", "at": "2026-10-31T06:00:01Z", "payload": {}},
        turn(3, "agent", "Namaste, main Chanakya hoon, ek AI assistant.", "2026-10-31T06:00:01.500000Z"),
        turn(4, "merchant", "Haan, bhej dijiye.", "2026-10-31T06:00:05Z"),
        {"seq": 5, "kind": "consent_given", "at": "2026-10-31T06:00:05Z", "payload": {}},
        {"seq": 6, "kind": "action_decision", "at": "2026-10-31T06:00:06Z",
         "payload": {"kind": "write", "verdict": "executed", "call": {"tool": "send_onboarding_link"}}},
        turn(7, "agent", "Link bhej diya hai.", "2026-10-31T06:00:07Z"),
    ]


class ReviewTest(unittest.TestCase):
    def test_a_clean_call_has_no_problems_and_notes_reply_time(self):
        problems, notes = review(good_call())
        self.assertEqual(problems, [])
        self.assertIn("reply time: median 1.8 s, slowest 2.0 s", notes)

    def test_finds_missing_disclosure_unsafe_text_slow_reply_and_mixed_script(self):
        events = [
            turn(1, "merchant", "Haan?", "2026-10-31T06:00:00Z"),
            turn(2, "agent", "Namaste — apna OTP bata dijiye?", "2026-10-31T06:00:06Z"),
            turn(3, "merchant", "Achha.", "2026-10-31T06:00:07Z"),
            turn(4, "agent", "Agar aap link खोलने के बाद पूरा नहीं कर पाते, toh main reminder bhejta hoon.",
                 "2026-10-31T06:00:08Z"),
        ]
        problems = " | ".join(review(events)[0])
        for expected in ("never disclosed", "first line does not say", "em_dash", "asked_sensitive_data",
                         "turn 2: reply took 6.0 s", "turn 4: mixes Latin and Devanagari"):
            self.assertIn(expected, problems)

    def test_a_write_before_consent_is_a_problem_and_blocked_actions_are_noted(self):
        events = [e for e in good_call() if e["kind"] != "consent_given"]
        events.append({"seq": 8, "kind": "action_decision", "at": "2026-10-31T06:00:08Z",
                       "payload": {"kind": "write", "verdict": "rejected", "reason": "no consent",
                                   "call": {"tool": "book_field_visit"}}})
        problems, notes = review(events)
        self.assertEqual(problems, ["send_onboarding_link ran without consent in the ledger"])
        self.assertIn("book_field_visit: rejected (no consent)", notes)


class RunLogTest(unittest.TestCase):
    def test_save_writes_the_run_folder_and_new_log_errors_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "backend.log"
            log.write_text("2026 ERROR old: before this run\n", encoding="utf-8")
            run_log = RunLog(Path(tmp) / "runs", log)
            with log.open("a", encoding="utf-8") as file:
                file.write("2026 INFO app: fine\n2026 ERROR backend.voice: Sarvam closed\nTraceback (most recent)\n")
            card = {"merchant_name": "Anita Sweets", "why_now": "12 card attempts"}
            missions = [{"mission": {"id": "m_1", "state": "DONE", "card": card}, "events": good_call()},
                        {"mission": {"id": "m_2", "state": "CREATED", "card": card}, "events": []}]
            result = run_log.save(missions)
            folder = Path(result["folder"])
            self.assertEqual({p.name for p in folder.iterdir()}, {"missions.json", "transcript.md", "report.md"})
            self.assertEqual((result["missions"], result["calls"]), (2, 1))
            self.assertEqual(len(result["problems"]), 2)
            self.assertIn("Sarvam closed", result["problems"][0])
            self.assertNotIn("before this run", " ".join(result["problems"]))
            self.assertIn("**Chanakya:** Namaste", (folder / "transcript.md").read_text(encoding="utf-8"))
            self.assertIn("2 missions, 1 with calls, 2 problems.", (folder / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(log_problems(log, log.stat().st_size), ([], log.stat().st_size))


if __name__ == "__main__":
    unittest.main()
