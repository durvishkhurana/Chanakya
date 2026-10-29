"""Planner measurements behind docs/results section 2: look-ahead vs baseline, and seed stability.

    python -m chanakya.eval.planner_checks lookahead   # consent rate, Twin-A, planning x seeds 0-9, evaluation x 0-4
    python -m chanakya.eval.planner_checks stability   # coach recording: does the suggestion depend on the seed?

Offline and deterministic: template twins, lexical belief, no network.
"""

import argparse
import asyncio
import json
import statistics
from collections import Counter
from typing import ClassVar

from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.schemas import Door, Merchant, MissionCard, MissionKind, TriggerType, Turn
from chanakya.brain.forest.forest import parse_move
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.tests.test_planner_rules import converse
from chanakya.humans.coach_api import FIXTURE
from chanakya.humans.coach_engine import CoachEngine

BANK = default_bank()


class TimedPlanner(NRPAPlanner):
    """NRPA that records the time of every searched plan."""

    times: ClassVar[list[float]] = []

    async def plan(self, state):
        result = await super().plan(state)
        if result.tree.get("searched"):
            self.times.append(result.elapsed_ms)
        return result


async def consent_rate(make, personas, seeds: int) -> float:
    results = [await converse(make(), persona, seed) for persona in personas for seed in range(seeds)]
    return sum(twin.state.consented for _, twin in results) / len(results)


async def lookahead() -> None:
    """Consent rate of the baseline and the look-ahead planner, and planner time per searched move."""
    for split, seeds in (("planning", 10), ("evaluation", 5)):
        personas = [p for p in load_personas(split=split) if not p.adversarial]
        baseline = await consent_rate(lambda: RuleBasedPlanner(BANK), personas, seeds)
        nrpa = await consent_rate(lambda: TimedPlanner(BANK), personas, seeds)
        print(f"{split}: {len(personas)} personas x seeds 0-{seeds - 1} ({len(personas) * seeds} calls): "
              f"baseline {baseline:.3f}, look-ahead {nrpa:.3f}")
    times = TimedPlanner.times
    print(f"planner time: p50 {statistics.median(times):.0f} ms, p90 {statistics.quantiles(times, n=10)[8]:.0f} ms, "
          f"max {max(times):.0f} ms over {len(times)} plans")


async def stability(seeds: int = 42) -> None:
    """Replay the coach recording with ``seeds`` mission ids and count how often each suggestion agrees."""
    recording = json.loads(FIXTURE.read_text(encoding="utf-8"))
    trigger = TriggerType(recording["metadata"]["mission"]["trigger"])

    async def run(mission_id: str) -> list[str]:
        card = MissionCard(mission_id=mission_id, merchant=Merchant(merchant_id="coach_merchant", name="Merchant",
                                                                    business_type="kirana", city="Jaipur",
                                                                    language="hi-IN"),
                           kind=MissionKind.SALES, goal="Coach a telecaller's call", door=Door.HUMAN, trigger=trigger,
                           why_now="stability check", starting_worries=BANK.priors[trigger])
        engine, keys = CoachEngine(card), []
        for turn in recording["turns"]:
            move = parse_move(turn["move"]) if turn.get("move") else None
            suggestion = await engine.observe(Turn(speaker=turn["speaker"], text=turn["text"], move=move))
            if suggestion is not None:
                keys.append(suggestion.move.key())
        return keys

    runs = [await run(f"seed_{i}") for i in range(seeds)]
    for index, keys in enumerate(zip(*runs, strict=True)):
        print(f"merchant turn {index + 1}: " + ", ".join(f"{k} {n}/{seeds}" for k, n in Counter(keys).most_common()))
    print(f"whole call identical to the most common run: {Counter(map(tuple, runs)).most_common(1)[0][1]}/{seeds}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Planner measurements for docs/results.")
    parser.add_argument("check", choices=["lookahead", "stability"])
    args = parser.parse_args(argv)
    asyncio.run(lookahead() if args.check == "lookahead" else stability())


if __name__ == "__main__":
    main()
