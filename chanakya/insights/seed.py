"""A seeded mission ledger for the insights screen (task B12): simulated calls through the real mission system.

Every held-out evaluation persona becomes a fictional merchant in the mock systems, a signal opens its mission
through the real intake, and a Twin-B merchant speaking held-out lines (``LinesVoice``, test split) talks to
Chanakya through ``MissionCall``: the real belief tracker, planner, safety gate, mock tools, verifier and hand-off
queue. Former-customer personas get win-back missions, so reasons for leaving are recorded too. Nothing is
invented after the fact; the insights are computed from whatever these calls write to the ledger.

    python -m chanakya.insights.seed --dir .state/insights-demo --seed 7 --rounds 2
    CHANAKYA_DB_PATH=.state/insights-demo/ledger.db MISSIONS_ENABLED=true uvicorn backend.main:app   # then open /insights
"""

import argparse
import asyncio
import json
import os
import random
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chanakya.actions.systems.tools import complete_onboarding
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.schemas import Persona
from chanakya.brain.mission_call import MissionCall
from chanakya.core.config import Settings
from chanakya.core.schemas import Door, MerchantSignal, MissionState, SignalKind
from chanakya.missions.runtime import Runtime
from chanakya.missions.scheduler import SimClock
from chanakya.neural.paraphrase import load
from chanakya.sim.twin import twin_b
from chanakya.sim.voice import LinesVoice

START = datetime(2026, 10, 26, 3, 45, tzinfo=UTC)  # 09:15 in Asia/Kolkata, inside calling hours
CALL_GAP = timedelta(minutes=12)
SALES_SIGNALS = [
    (SignalKind.CALLBACK_REQUEST, Door.MERCHANT, {"product": "soundbox"}),
    (SignalKind.ONBOARDING_STALLED, Door.MERCHANT, {"days": 2, "step": "bank details", "product": "soundbox"}),
    (SignalKind.PRICE_QUESTION_DROPPED, Door.MERCHANT, {"product": "card_machine"}),
    (SignalKind.UPI_RISING_NO_SOUNDBOX, Door.DATA, {"growth_pct": 48}),
    (SignalKind.CARD_ATTEMPTS_NO_POS, Door.DATA, {"attempts": 9}),
    (SignalKind.LEAD_LIST_ASSIGNED, Door.HUMAN, {"assigned_by": "Sunita"}),
]
ONBOARDING_COMPLETES = 0.75  # share of sent links the simulated merchant finishes; the verifier still checks each one


def add_merchant(runtime: Runtime, merchant_id: str, persona: Persona, now: datetime, churned_days: int | None) -> None:
    """A fictional merchant in the mock systems for this persona (labelled simulated)."""
    name = f"{persona.business_type.title()} {persona.city} (simulated)"
    runtime.db.write("INSERT INTO merchants (id, name, business_type, city, language, start_hour, end_hour, relationship, "
                     "churned_at) VALUES (?, ?, ?, ?, ?, 9, 21, ?, ?)", merchant_id, name, persona.business_type,
                     persona.city, persona.language, "former" if churned_days else "customer",
                     (now - timedelta(days=churned_days)).isoformat() if churned_days else None)


async def play(runtime: Runtime, mission_id: str, persona: Persona, call_seed: int, voice: LinesVoice,
               max_turns: int = 12) -> None:
    """One call between Chanakya and the persona's twin, ended the way the real system would end it."""
    call = MissionCall(runtime, mission_id)
    await call.start()
    twin = twin_b(persona, seed=call_seed, voice=voice)
    text = twin.opening()
    for _ in range(max_turns):
        reply = await call.say(text)
        mission = runtime.ledger.store.get(mission_id)
        if reply is None or not call.open or mission.state == MissionState.AWAITING_CONFIRMATION:
            break
        answer = await twin.respond(reply, call.state.moves[-1])
        if answer.ended and not answer.text:
            break
        text = answer.text
    mission = runtime.ledger.store.get(mission_id)
    if mission.state == MissionState.IN_CONVERSATION:
        outcome = "merchant hung up" if twin.state.ended else "call ended without a decision"
        await runtime.ledger.close(mission_id, MissionState.CLOSED_NOT_INTERESTED, outcome=outcome)


async def finish_onboarding(runtime: Runtime, mission_id: str, rng: random.Random) -> None:
    """Some merchants complete the mock onboarding page; the verifier confirms it like on a real backend."""
    sessions = runtime.db.all("SELECT id FROM onboarding_sessions WHERE mission_id = ?", mission_id)
    if sessions and rng.random() < ONBOARDING_COMPLETES:
        complete_onboarding(runtime.db, sessions[0]["id"])
        await runtime.verifier.check_now(sessions[0]["id"])


async def seed_ledger(runtime: Runtime, seed: int = 7, rounds: int = 2, limit: int | None = None) -> Counter:
    """Play ``rounds`` days of calls, one per held-out persona per day; return the final mission states."""
    rng = random.Random(seed)
    voice = LinesVoice(default_bank(), load("test"))
    personas = (load_personas(split="evaluation") + load_personas(split="evaluation", relationship="former"))[:limit]
    for day in range(rounds):
        for index, persona in enumerate(personas):
            target = START + timedelta(days=day) + index * CALL_GAP
            if target > runtime.clock():
                runtime.clock.advance(target - runtime.clock())
            merchant_id = f"mer_sim_{day}_{index:02d}"
            former = persona.relationship == "former"
            days_ago = rng.randint(20, 150) if former else None
            add_merchant(runtime, merchant_id, persona, runtime.clock(), days_ago)
            if former:
                kind, door, details = SignalKind.MERCHANT_CHURNED, Door.DATA, {"days": days_ago, "product": "soundbox"}
            else:
                kind, door, details = rng.choice(SALES_SIGNALS)
            mission, _ = await runtime.intake.ingest(MerchantSignal(
                merchant_id=merchant_id, kind=kind, door=door, source="insights seed (simulated)", details=details))
            if mission.state in {MissionState.CREATED, MissionState.SCHEDULED}:
                await play(runtime, mission.id, persona, seed * 10_000 + day * 100 + index, voice)
                await finish_onboarding(runtime, mission.id, rng)
    return Counter(m.state.value for m in runtime.ledger.store.list())


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a mission ledger with simulated calls for the insights screen.")
    parser.add_argument("--dir", type=Path, default=Path(".state/insights-demo"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=2, help="Days of calls; each day calls every held-out persona once")
    parser.add_argument("--force", action="store_true", help="Replace an existing seeded folder")
    parser.add_argument("--worry-scorer", choices=["embedding", "lexical"], default="embedding",
                        help="Chanakya's worry scorer for these calls (embedding falls back to lexical without the model)")
    args = parser.parse_args()
    os.environ["WORRY_SCORER"] = args.worry_scorer
    if args.dir.exists():
        if not args.force:
            raise SystemExit(f"{args.dir} exists; pass --force to replace it")
        shutil.rmtree(args.dir)
    args.dir.mkdir(parents=True)
    runtime = Runtime.build(Settings(db_path=args.dir / "ledger.db", calling_hours=(9, 21)), clock=SimClock(START))
    states = asyncio.run(seed_ledger(runtime, args.seed, args.rounds))
    from chanakya.neural.scorer import load_embedding_scorer

    scorer = "embedding" if args.worry_scorer == "embedding" and load_embedding_scorer() else "lexical"
    (args.dir / "seed.json").write_text(json.dumps({"seed": args.seed, "rounds": args.rounds, "worry_scorer": scorer,
                                                    "missions": dict(states.most_common())}, indent=2) + "\n")
    print(f"{sum(states.values())} missions in {args.dir / 'ledger.db'}: {dict(states.most_common())}")
    print(f"View: CHANAKYA_DB_PATH={args.dir / 'ledger.db'} MISSIONS_ENABLED=true, then open /insights")


if __name__ == "__main__":
    main()
