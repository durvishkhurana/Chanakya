"""Planning while listening: prepare the next turn from the partial transcript, commit it if the final matches.

Speculation runs on a copy of the conversation state with no writes and no published events. If the
final transcript matches the partial it was prepared from, the prepared turn is committed at once;
otherwise it is discarded and the turn is computed normally. Write actions are never taken
speculatively (docs/IDEA.md 3.4: only read-only lookups before the merchant finishes).

    python -m chanakya.brain.speculative --turns 40 --seed 3
"""

import argparse
import asyncio
import json
import random
import re
import statistics
import time
from dataclasses import dataclass

from .belief import dice, trigrams

MATCH_THRESHOLD = 0.9


def normalise(text: str) -> str:
    """Lower-case, drop punctuation and squeeze spaces so trivial transcript changes still match."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def matches(partial: str, final: str) -> bool:
    """Whether a turn prepared from ``partial`` is still right for ``final``."""
    a, b = normalise(partial), normalise(final)
    return a == b or dice(trigrams(a), trigrams(b)) >= MATCH_THRESHOLD


@dataclass
class Speculation:
    """A turn being prepared from a partial transcript, tied to the state version it started from."""

    text: str
    version: int
    task: asyncio.Task

    def usable_for(self, final: str, version: int) -> bool:
        """Only a match on the same state version may be committed."""
        return self.version == version and matches(self.text, final)


class SlowFakeLLM:
    """A fake model with fixed delays per role, for measuring latency without a network."""

    def __init__(self, delays: dict[str, float]):
        self.delays = delays

    async def complete(self, role, messages, **kwargs):
        await asyncio.sleep(self.delays.get(role, 0.0))
        if "scores" in messages[0]["content"]:
            return json.dumps({"scores": {}})
        return json.dumps({"text": "Aapke grahak abhi payment kaise karte hain?"})


async def measure(turns: int = 40, seed: int = 3, lead_s: float = 0.6, change_rate: float = 0.25,
                  delays: dict[str, float] | None = None, llm=None) -> dict:
    """Turn latency (final transcript to reply) with and without speculation, on identical scripted turns.

    With ``llm`` the real provider is used; otherwise a fake model with fixed ``delays`` per role.
    """
    from agent.brain_agent import BrainAgent

    delays = delays or {"rollout": 0.25, "main": 0.8}
    rng = random.Random(seed)
    lines = ["Hello?", "Haan boliye", "Mere paas pehle se QR hai", "Rent kitna hai", "Achha", "Soch ke bataunga"]
    script = []
    for index in range(turns):
        final = lines[index % len(lines)]
        changed = rng.random() < change_rate
        script.append((final.split()[0] if changed and " " in final else final, final))

    async def run(speculate: bool) -> list[float]:
        agent = BrainAgent(llm=llm or SlowFakeLLM(delays))
        latencies = []
        for partial, final in script:
            if speculate:
                await agent.prepare(partial, "m", "hi-IN")
                await asyncio.sleep(lead_s)  # the merchant is still speaking
            started = time.perf_counter()
            await agent.respond(final, "m", "hi-IN")
            latencies.append((time.perf_counter() - started) * 1000)
        return latencies

    after, listening = await run(False), await run(True)

    def summary(values):
        ordered = sorted(values)
        return {"p50_ms": round(statistics.median(ordered), 1), "p90_ms": round(ordered[int(0.9 * len(ordered))], 1)}

    return {"turns": turns, "seed": seed, "lead_s": lead_s, "change_rate": change_rate,
            "model": "live provider" if llm else {"fake_delays_s": delays},
            "planning_after_speech": summary(after), "planning_while_listening": summary(listening),
            "speculation_misses": sum(1 for partial, final in script if not matches(partial, final))}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Measure turn latency with and without planning while listening.")
    parser.add_argument("--turns", type=int, default=40)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--lead", type=float, default=0.6, help="Seconds between the partial and final transcript")
    parser.add_argument("--change-rate", type=float, default=0.25)
    parser.add_argument("--live", action="store_true", help="Use the configured LLM provider instead of fake delays")
    args = parser.parse_args(argv)
    llm = None
    if args.live:
        from pathlib import Path

        from dotenv import load_dotenv

        from chanakya.core.llm import OpenAICompatibleLLM

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        llm = OpenAICompatibleLLM()
    print(json.dumps(asyncio.run(measure(args.turns, args.seed, args.lead, args.change_rate, llm=llm)), indent=2))


if __name__ == "__main__":
    main()
