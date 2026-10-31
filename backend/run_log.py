"""Demo run logs (DEMO_TOOLS_ENABLED): a backend log file, and a saved snapshot of every mission with automatic checks.

A saved run lands in `<state dir>/runs/<time>/`: `missions.json` (every mission and its full ledger), `transcript.md`
(each call as readable lines) and `report.md` (problems found). The state dir is the ledger's folder, `.state/` by
default, which git ignores.
"""

import json
import logging
import re
import statistics
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import APIRouter, Request

from backend.phone_link import require_laptop
from chanakya.sim.judge import safety_violations

SLOW_REPLY_SECONDS = 4.0
MAX_LOG_PROBLEMS = 20
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# A Hinglish line that switches into Devanagari mid-reply reads and sounds broken.
LATIN_WORDS = re.compile(r"\b[a-zA-Z]{3,}\b(?:\W+\b[a-zA-Z]{3,}\b){2}")
DEVANAGARI_WORDS = re.compile(r"[ऀ-ॿ]{2,}(?:\W+[ऀ-ॿ]{2,}){2}")


def state_dir() -> Path:
    """The folder that holds the mission ledger."""
    from chanakya.core.config import Settings

    return Settings.from_env().db_path.parent


def log_path() -> Path:
    return state_dir() / "logs" / "backend.log"


def start_file_logging(path: Path) -> RotatingFileHandler:
    """Copy the app's and the server's log lines into a rotating file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(min(root.level or logging.WARNING, logging.INFO))
    # uvicorn's loggers do not propagate to the root logger.
    for name in ("", "uvicorn"):
        logging.getLogger(name).addHandler(handler)
    return handler


def stop_file_logging(handler: RotatingFileHandler) -> None:
    for name in ("", "uvicorn"):
        logging.getLogger(name).removeHandler(handler)
    handler.close()


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def review(events: list[dict]) -> tuple[list[str], list[str]]:
    """Problems and notes for one mission's ledger events (dicts as the mission API returns them)."""
    problems, notes = [], []
    turns = [e for e in events if e["kind"] == "turn_completed"]
    agent = [t for t in turns if t["payload"]["speaker"] != "merchant"]
    if agent and not any(e["kind"] == "ai_disclosed" for e in events):
        problems.append("Chanakya never disclosed that it is an AI")
    if agent and "AI" not in agent[0]["payload"]["text"]:
        problems.append("Chanakya's first line does not say it is an AI")
    delays = []
    last_merchant = None
    for number, turn in enumerate(turns, 1):
        payload = turn["payload"]
        if payload["speaker"] == "merchant":
            last_merchant = payload.get("at") or turn["at"]
            continue
        for problem in safety_violations(payload["text"]):
            problems.append(f"turn {number}: {problem} in \"{payload['text'][:80]}\"")
        if LATIN_WORDS.search(payload["text"]) and DEVANAGARI_WORDS.search(payload["text"]):
            problems.append(f"turn {number}: mixes Latin and Devanagari script in \"{payload['text'][:80]}\"")
        if last_merchant:
            delay = _seconds(last_merchant, payload.get("at") or turn["at"])
            delays.append(delay)
            if delay > SLOW_REPLY_SECONDS:
                problems.append(f"turn {number}: reply took {delay:.1f} s")
            last_merchant = None
    if delays:
        notes.append(f"reply time: median {statistics.median(delays):.1f} s, slowest {max(delays):.1f} s")
    fallbacks = sum(1 for e in events if e["kind"] == "plan_computed" and e["payload"].get("fallback"))
    if fallbacks:
        notes.append(f"planner fell back to its rule {fallbacks} time(s)")
    consent = False
    for event in events:
        payload = event["payload"]
        if event["kind"] == "consent_given":
            consent = True
        elif event["kind"] == "action_decision":
            tool = payload.get("call", {}).get("tool")
            if payload.get("kind") == "write" and payload.get("verdict") == "executed" and not consent:
                problems.append(f"{tool} ran without consent in the ledger")
            elif payload.get("verdict") != "executed":
                notes.append(f"{tool}: {payload.get('verdict')} ({payload.get('reason')})")
    return problems, notes


def log_problems(path: Path, offset: int) -> tuple[list[str], int]:
    """ERROR and Traceback lines written to the log since `offset`, and the new offset."""
    if not path.exists():
        return [], 0
    size = path.stat().st_size
    if size < offset:  # rotated since the last save
        offset = 0
    with path.open(encoding="utf-8", errors="replace") as file:
        file.seek(offset)
        lines = [line.rstrip() for line in file if " ERROR " in line or line.startswith("Traceback")]
    return [f"backend log: {line[:200]}" for line in lines[:MAX_LOG_PROBLEMS]], size


def transcript(mission: dict, events: list[dict]) -> str:
    """One mission as readable markdown lines."""
    card = mission["card"]
    lines = [f"## {card['merchant_name']} ({mission['id']})", "",
             f"{card['why_now']}. State: **{mission['state']}**. Times are UTC.", ""]
    for event in events:
        payload, at = event["payload"], event["at"][11:19]
        if event["kind"] == "turn_completed":
            move = (payload.get("move") or {}).get("type")
            who = "Merchant" if payload["speaker"] == "merchant" else f"Chanakya ({move})" if move else "Chanakya"
            lines.append(f"- `{at}` **{who}:** {payload['text']}")
        elif event["kind"] == "action_decision":
            lines.append(f"- `{at}` action {payload.get('call', {}).get('tool')}: {payload.get('verdict')}")
        elif event["kind"] == "state_changed":
            lines.append(f"- `{at}` state {payload['from']} → {payload['to']} ({payload.get('reason')})")
    return "\n".join(lines) + "\n"


class RunLog:
    """Saves a snapshot of every mission in the ledger with its review."""

    def __init__(self, base: Path, log_file: Path | None):
        self.base = base
        self.log_file = log_file
        self.log_offset = log_file.stat().st_size if log_file and log_file.exists() else 0

    def save(self, missions: list[dict]) -> dict:
        """Write the run folder and return where it is and what was found."""
        folder = self.base / datetime.now().strftime("%Y%m%d-%H%M%S")
        folder.mkdir(parents=True, exist_ok=True)
        report, texts, problems = ["# Run report", ""], ["# Transcripts", ""], []
        for item in missions:
            mission, events = item["mission"], item["events"]
            if not any(e["kind"] == "turn_completed" for e in events):
                continue  # never called: nothing to review
            found, notes = review(events)
            problems += [f"{mission['card']['merchant_name']}: {p}" for p in found]
            report += [f"## {mission['card']['merchant_name']} ({mission['id']}): {mission['state']}", ""]
            report += [f"- PROBLEM {p}" for p in found] + [f"- note: {n}" for n in notes] or ["- no problems"]
            report.append("")
            texts.append(transcript(mission, events))
        if self.log_file:
            found, self.log_offset = log_problems(self.log_file, self.log_offset)
            problems += found
            report += ["## Backend log", ""] + ([f"- PROBLEM {p}" for p in found] or ["- no errors"])
        calls = len(texts) - 2
        report[2:2] = [f"{len(missions)} missions, {calls} with calls, {len(problems)} problems.", ""]
        (folder / "missions.json").write_text(json.dumps(missions, ensure_ascii=False, indent=1), encoding="utf-8")
        (folder / "transcript.md").write_text("\n".join(texts), encoding="utf-8")
        (folder / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        return {"folder": str(folder), "missions": len(missions), "calls": calls, "problems": problems}


router = APIRouter(prefix="/api/run-logs", tags=["demo"])
_run_log: RunLog | None = None


def configure_run_log(run_log: RunLog | None) -> None:
    """Set where runs are saved (main.py at startup, tests with a temporary folder)."""
    global _run_log
    _run_log = run_log


@router.post("")
async def save_run(request: Request) -> dict:
    """Save every mission in the ledger with its review, and the backend log errors since the last save."""
    require_laptop(request)
    from chanakya.missions.runtime import get_runtime

    store = get_runtime().ledger.store
    missions = [{"mission": m.model_dump(mode="json"), "events": [e.model_dump(mode="json") for e in store.events(m.id)]}
                for m in reversed(store.list())]
    run_log = _run_log or RunLog(state_dir() / "runs", None)
    return run_log.save(missions)
