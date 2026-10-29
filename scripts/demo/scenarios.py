"""Run the demo storyline in-process: every scenario from one command, on a fresh mock ledger.

    python scripts/demo/scenarios.py                       # all four scenarios, offline templates
    python scripts/demo/scenarios.py distressed_handoff    # one scenario
    python scripts/demo/scenarios.py --live                # Chanakya speaks through the configured LLM

The clock is fixed at 15:00 IST so calling hours always apply the same way. Exits non-zero if a check fails.
To run a scenario on a live backend instead (so Mission Control and the Live Call View show it), use the
"Run demo scenario" control or POST /api/calls/scenarios/<name>.
"""

import argparse
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chanakya.brain.scenarios import SCENARIOS, run_all
from chanakya.core.config import Settings
from chanakya.missions.runtime import Runtime
from chanakya.missions.scheduler import SimClock

START = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)  # 15:00 in Asia/Kolkata


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Chanakya's demo scenarios end to end.")
    parser.add_argument("names", nargs="*", choices=[*SCENARIOS, []], help="Scenarios to run (default: all)")
    parser.add_argument("--live", action="store_true", help="Use the configured LLM provider for Chanakya's words")
    args = parser.parse_args()
    llm = None
    if args.live:
        from dotenv import load_dotenv

        from chanakya.brain.contracts.llm import default_llm

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        llm = default_llm()
    with tempfile.TemporaryDirectory() as folder:
        runtime = Runtime.build(Settings(db_path=Path(folder) / "ledger.db"), clock=SimClock(START))
        results = asyncio.run(run_all(runtime, args.names or None, llm=llm))
        runtime.ledger.store.conn.close()
        runtime.db.conn.close()
    failed = 0
    for result in results:
        print(f"\n=== {SCENARIOS[result.scenario].title}")
        for speaker, text in result.lines:
            print(f"  {'Merchant' if speaker == 'merchant' else 'Chanakya'}: {text}")
        print(f"  -> mission {result.state}: {result.outcome or ''}")
        for name, ok in result.checks:
            print(f"  {'PASS' if ok else 'FAIL'} {name}")
        failed += not result.ok
    print(f"\n{len(results) - failed}/{len(results)} scenarios passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
