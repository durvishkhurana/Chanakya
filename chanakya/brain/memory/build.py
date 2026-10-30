"""Build the planner's semantic memory from conversations spoken with the train-split lines voice.

    python -m chanakya.brain.memory.build --seed 11           # needs the e5 encoder (python -m chanakya.neural.encoder --download)
    python -m chanakya.brain.memory.build --seed 11 --encoder fake --out .state/memory_fake.npz   # smoke run, no model

The conversations come from the same three policies as the Strategy Forest (look-ahead planner, baseline, exploring
baseline) talking to planning-split Twin-A merchants, but every voiced worry is a labelled paraphrase from N0's train
split instead of one of the 82 Concern Bank sentences. Writes ``data/neural/memory.npz`` and
``docs/results/neural-memory/build.md`` with the lookup time.
"""

import argparse
import asyncio
import random
import statistics
import sys
import time
from pathlib import Path

from chanakya.brain import moves as lib
from chanakya.brain.belief import BayesianBeliefTracker
from chanakya.brain.concern_bank import ROOT, default_bank, load_personas
from chanakya.brain.contracts.schemas import ConsentRecord, DialogueState, MoveType, Persona, Transcript, Turn
from chanakya.brain.forest.generate import planning_card
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner, consent_tool, mission_product
from chanakya.neural.paraphrase import load as load_lines
from chanakya.sim.twin import SimulatedMerchant
from chanakya.sim.voice import LinesVoice

from .memory import MEMORY, SemanticMemory

RESULTS = ROOT / "docs" / "results" / "neural-memory"


async def converse(planner, persona: Persona, seed: int, voice, explore: float = 0.0, max_turns: int = 12) -> dict:
    """One text-mode call against a planning twin speaking ``voice``; each agent move keeps the belief it saw."""
    bank = default_bank()
    rng = random.Random(f"explore:{seed}:{persona.persona_id}")
    card = planning_card(persona, seed)
    tracker = BayesianBeliefTracker(bank)
    state = DialogueState(card=card, belief=tracker.start(card.starting_worries),
                          transcript=Transcript(mission_id=card.mission_id))
    twin = SimulatedMerchant(persona, voice, seed, name="twin_a")
    turns = [{"speaker": "merchant", "text": twin.opening()}]
    state.transcript.turns.append(Turn(speaker="merchant", text=turns[0]["text"]))
    for _ in range(max_turns):
        move = (await planner.plan(state)).move
        if explore and rng.random() < explore and move.type not in lib.TERMINAL_MOVES | {MoveType.TAKE_ACTION,
                                                                                       MoveType.DISCLOSE_AND_GREET}:
            options = [m for m in lib.legal_moves(state, bank, mission_product(card), consent_tool(card, state))
                       if m.type not in {MoveType.TAKE_ACTION, MoveType.DISCLOSE_AND_GREET}]
            move = rng.choice(options) if options else move
        state.moves.append(move)
        state.transcript.turns.append(Turn(speaker="agent", text=f"[{move.key()}]", move=move))
        turns.append({"speaker": "agent", "move": move.key(), "top_concern": state.belief.top(1)[0][0],
                      "belief": {cid: round(p, 4) for cid, p in state.belief.probabilities.items()}})
        state.transcript.disclosed_ai |= move.type == MoveType.DISCLOSE_AND_GREET
        if move.type == MoveType.TAKE_ACTION or move.type in lib.TERMINAL_MOVES:
            break
        reply = await twin.respond(f"[{move.key()}]", move)
        turns.append({"speaker": "merchant", "text": reply.text})
        merchant = Turn(speaker="merchant", text=reply.text)
        state.transcript.turns.append(merchant)
        if move.type == MoveType.CONFIRM_CONSENT and lib.explicit_consent(reply.text):
            state.transcript.consents.append(ConsentRecord(tool=move.tool, turn_index=len(state.transcript.turns) - 1,
                                                           utterance=reply.text))
        state.belief = await tracker.update(state.belief, merchant, state.transcript.turns)
        if reply.ended:
            break
    outcome = "consented" if twin.state.consented else "followup" if twin.state.followup_agreed else "not_closed"
    return {"persona_id": persona.persona_id, "language": persona.language, "seed": seed, "outcome": outcome,
            "turns": turns}


async def transcripts(seed: int, seeds_per_persona: int = 6, split: str = "train") -> list[dict]:
    """Conversations from three policies on planning personas, voiced with one split of the labelled lines."""
    voice = LinesVoice(default_bank(), load_lines(split))
    personas = [p for p in load_personas(split="planning") if not p.adversarial]
    policies = [(NRPAPlanner(seed=seed, budget_ms=1e9), 0.0), (RuleBasedPlanner(), 0.0), (RuleBasedPlanner(), 0.35)]
    return [await converse(planner, persona, seed * 100 + s, voice, explore)
            for planner, explore in policies for persona in personas for s in range(seeds_per_persona)]


def lookup_times(memory: SemanticMemory, lines: list[dict], count: int = 200, seed: int = 0) -> tuple[float, float]:
    """p50 and p90 milliseconds of one lookup (embedding included) on held-out test-split lines."""
    rng = random.Random(seed)
    sample = rng.sample(lines, min(count, len(lines)))
    concern_ids = memory.concern_ids
    times = []
    for row in sample:
        memory.lookup(row["text"], {cid: 1 / len(concern_ids) for cid in concern_ids})
        times.append(memory.last_lookup_ms)
    return statistics.median(times), statistics.quantiles(times, n=10)[8]


def encoder_for(name: str):
    """The real e5 encoder, or the trigram FakeEncoder for a smoke run."""
    from chanakya.neural.encoder import FakeEncoder, load_encoder

    if name == "fake":
        return FakeEncoder()
    encoder = load_encoder()
    if encoder is None:
        raise SystemExit("the e5 encoder is not available; run python -m chanakya.neural.encoder --download")
    return encoder


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Build the planner's semantic memory (task N2).")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--seeds-per-persona", type=int, default=6)
    parser.add_argument("--encoder", choices=["e5", "fake"], default="e5")
    parser.add_argument("--out", type=Path, default=MEMORY)
    args = parser.parse_args(argv)
    encoder = encoder_for(args.encoder)
    started = time.perf_counter()
    found = asyncio.run(transcripts(args.seed, args.seeds_per_persona))
    memory = SemanticMemory.build(found, encoder, seed=args.seed)
    memory.save(args.out)
    p50, p90 = lookup_times(memory, load_lines("test"))
    command = "python -m chanakya.brain.memory.build " + " ".join(argv if argv is not None else sys.argv[1:])
    meta = memory.metadata
    report = "\n".join([
        "# Semantic memory: build", "",
        f"- Command: `{command}`",
        (f"- Conversations: {meta['transcripts']} (look-ahead planner, baseline, exploring baseline x planning personas), "
        f"voiced with N0's train-split lines; {sum(t['outcome'] == 'consented' for t in found)} ended in a yes"),
        (f"- Moments remembered: {meta['moments']}; encoder `{meta['encoder']}`; seed {meta['seed']}; "
        f"data hash `{meta['data_hash']}`; {meta['date']}; built in {time.perf_counter() - started:.0f} s"),
        f"- Lookup on 200 test-split lines (embedding included): p50 {p50:.2f} ms, p90 {p90:.2f} ms", "",
    ]) + "\n"
    if args.out == MEMORY:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "build.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
