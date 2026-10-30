"""Run every variant against the same held-out Twin-B merchants and write a report.

    python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7

``offline`` uses template voices and declared moves: deterministic, no network. ``online`` uses the
configured LLM provider for the variants, Twin-B's voice and a judge that labels every variant's
words into moves.
"""

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

from chanakya.brain import moves as lib
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.schemas import (
    TRIGGER_DOORS,
    Merchant,
    MissionCard,
    MissionKind,
    MoveType,
    Persona,
    TriggerType,
)
from chanakya.sim.judge import safety_violations
from chanakya.sim.twin import twin_b

from .labeler import DeclaredLabeler, LLMLabeler
from .metrics import CallRecord, summarise, to_json
from .report import write_report
from .variants import VARIANTS, CountingLLM, make_variant

SALES_TRIGGERS = (TriggerType.CALLBACK_REQUEST, TriggerType.UPI_RISING_NO_SOUNDBOX, TriggerType.CARD_DEMAND_NO_POS,
                  TriggerType.PRODUCT_QUESTION, TriggerType.LEAD_LIST, TriggerType.ONBOARDING_STUCK)


def card_for(persona: Persona, seed: int) -> MissionCard:
    """A sales mission card for a simulated merchant, its trigger fixed by the seed."""
    bank = default_bank()
    trigger = random.Random(f"{seed}:{persona.persona_id}:trigger").choice(SALES_TRIGGERS)
    return MissionCard(
        mission_id=f"eval_{persona.persona_id}_{seed}",
        merchant=Merchant(merchant_id=persona.persona_id, name=f"{persona.business_type} (simulated)",
                          business_type=persona.business_type, city=persona.city, language=persona.language),
        kind=MissionKind.SALES, goal="Sell the right payment product, then verified onboarding",
        door=TRIGGER_DOORS[trigger], trigger=trigger, why_now=f"Simulated {trigger.value}",
        starting_worries=bank.priors[trigger],
    )


async def run_call(variant_name: str, persona: Persona, seed: int, *, llm=None, llm_agent=None, twin_llm=None,
                   labeler=None, max_turns: int = 12, voice=None) -> CallRecord:
    """One text-mode call between a fresh variant and a Twin-B merchant."""
    counted = CountingLLM(llm) if llm is not None else None
    variant = make_variant(variant_name, llm=counted, llm_agent=llm_agent)
    labeler = labeler or DeclaredLabeler()
    card = card_for(persona, seed)
    await variant.open(card)
    twin = twin_b(persona, llm=twin_llm, seed=seed, voice=voice)
    merchant_text = twin.opening()
    record = CallRecord(variant=variant_name, persona_id=persona.persona_id, adversarial=persona.adversarial,
                        seed=seed, trigger=card.trigger.value, outcome="undecided", agent_turns=0)
    record.transcript.append({"speaker": "merchant", "text": merchant_text})
    for _ in range(max_turns):
        turn = await variant.turn(merchant_text)
        move = await labeler.label(turn.text, turn.move, merchant_text)
        record.agent_turns += 1
        record.latencies_ms.append(round(turn.latency_ms, 2))
        record.violations.extend(safety_violations(turn.text))
        consents = variant.state.transcript
        for decision in turn.actions:
            record.actions.append({"tool": decision.call.tool, "verdict": decision.verdict, "reason": decision.reason,
                                   "consented": consents.has_consent(decision.call.tool)})
        record.transcript.append({"speaker": "agent", "text": turn.text, "move": move.key() if move else None})
        if move and move.type == MoveType.ESCALATE:
            record.escalated = True
        if twin.state.consented and move and move.type == MoveType.TAKE_ACTION:
            break
        reply = await twin.respond(turn.text, move)
        merchant_text = reply.text
        record.transcript.append({"speaker": "merchant", "text": merchant_text})
        if reply.ended and not reply.consented:
            break
        if reply.consented and not any(m.type == MoveType.CONFIRM_CONSENT for m in [move] if m):
            break
    state = twin.state
    if state.consented:
        record.outcome = "consented"
    elif state.followup_agreed:
        record.outcome = "followup"
    elif record.escalated:
        record.outcome = "escalated"
    elif state.ended and (state.willingness <= 0.08 or state.patience <= 0):
        record.outcome = "walked_away"
    elif state.declined or lib.merchant_declined(merchant_text):
        record.outcome = "declined"
    elif state.ended:
        record.outcome = "ended_by_agent"
    belief = variant.state.belief.probabilities
    if belief:
        record.belief_hit = max(belief, key=belief.get) in persona.hidden_concerns
    record.llm_calls = counted.calls if counted else 0
    record.agent_errors = getattr(variant, "errors", 0)
    return record


def merchant_set(count: int, adversarial_repeats: int) -> list[tuple[Persona, int]]:
    """``count`` held-out calls cycling the evaluation personas, plus each adversarial persona repeated."""
    personas = load_personas(split="evaluation")
    regular = [p for p in personas if not p.adversarial]
    calls = [(regular[i % len(regular)], i) for i in range(count)]
    calls += [(p, 1000 + r) for p in personas if p.adversarial for r in range(adversarial_repeats)]
    return calls


async def evaluate(variants=VARIANTS, merchants: int = 100, seed: int = 7, adversarial_repeats: int = 3,
                   mode: str = "offline", concurrency: int = 8, max_turns: int = 12, voice: str = "template") -> dict:
    """Run every variant on the same calls and return the summary plus per-call records.

    ``voice`` is ``template`` (Concern Bank phrasings) or a split of the labelled lines (``test`` for evaluation).
    """
    llm = llm_agent = twin_llm = None
    lines_voice = None
    if voice != "template":
        from chanakya.neural.paraphrase import load
        from chanakya.sim.voice import LinesVoice

        lines_voice = LinesVoice(default_bank(), load(voice))
    labeler = DeclaredLabeler()
    if mode == "online":
        from agent.graph import Agent
        from agent.prompts.prompts import voice_assistant_system_prompt
        from chanakya.brain.contracts.llm import default_llm

        llm = twin_llm = default_llm()
        llm_agent = Agent(name="Chanakya-Eval-Reactive", system_prompt=voice_assistant_system_prompt)
        labeler = LLMLabeler(llm)
    calls = [(persona, seed * 10_000 + index) for persona, index in merchant_set(merchants, adversarial_repeats)]
    gate = asyncio.Semaphore(concurrency)

    async def one(name, persona, call_seed):
        async with gate:
            return await run_call(name, persona, call_seed, llm=llm, llm_agent=llm_agent, twin_llm=twin_llm,
                                  labeler=labeler, max_turns=max_turns, voice=lines_voice)

    started = time.perf_counter()
    records = {name: await asyncio.gather(*[one(name, p, s) for p, s in calls]) for name in variants}
    if llm is not None:
        await llm.aclose()
        await llm_agent.aclose()
    return {
        "config": {"mode": mode, "seed": seed, "merchants": merchants, "adversarial_repeats": adversarial_repeats,
                   "variants": list(variants), "max_turns": max_turns, "voice": voice,
                   "elapsed_s": round(time.perf_counter() - started, 1)},
        "summary": {name: summarise(list(recs)) for name, recs in records.items()},
        "calls": {name: [to_json(r) for r in recs] for name, recs in records.items()},
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate Chanakya variants against held-out Twin-B merchants.")
    parser.add_argument("--mode", choices=["offline", "online"], default="offline")
    parser.add_argument("--merchants", type=int, default=100)
    parser.add_argument("--adversarial-repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--voice", choices=["template", "test", "train"], default="template",
                        help="Twin-B speech: Concern Bank templates, or labelled lines from one split (offline only)")
    parser.add_argument("--out", type=Path, default=None, help="Output folder (default .state/eval/<mode>-<seed>)")
    args = parser.parse_args(argv)
    if args.mode == "online":
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    results = asyncio.run(evaluate(tuple(args.variants.split(",")), args.merchants, args.seed,
                                   args.adversarial_repeats, args.mode, args.concurrency, args.max_turns, args.voice))
    out = args.out or Path(".state") / "eval" / f"{args.mode}-{args.seed}"
    command = "python -m chanakya.eval.harness " + " ".join(argv if argv is not None else __import__("sys").argv[1:])
    paths = write_report(results, out, command)
    print(json.dumps(results["summary"], indent=2))
    print("Report:", ", ".join(str(p) for p in paths))


if __name__ == "__main__":
    main()
