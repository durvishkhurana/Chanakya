"""Generate expert-style synthetic transcripts and mine the Strategy Forest from them.

    python -m chanakya.brain.forest.generate --seed 11

METRO reports synthetic transcripts as workable when real recordings are unavailable. Ours come from
the planners talking to planning-split Twin-A merchants (Hindi, Hinglish, Punjabi and English), with
some exploration so the forest also sees moves that did not work. Every transcript keeps its outcome.
"""

import argparse
import asyncio
import json
import random

from chanakya.brain import moves as lib
from chanakya.brain.belief import BayesianBeliefTracker
from chanakya.brain.concern_bank import DATA, default_bank, load_personas
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner, consent_tool, mission_product
from chanakya.core.schemas import (
    TRIGGER_DOORS,
    ConsentRecord,
    DialogueState,
    Merchant,
    MissionCard,
    MissionKind,
    MoveType,
    Persona,
    Transcript,
    TriggerType,
    Turn,
)
from chanakya.sim.twin import twin_a

from .forest import StrategyForest

TRANSCRIPTS = DATA / "transcripts" / "synthetic_transcripts.jsonl"
FOREST = DATA / "forest" / "forest.json"
TRIGGERS = (TriggerType.CALLBACK_REQUEST, TriggerType.UPI_RISING_NO_SOUNDBOX, TriggerType.CARD_DEMAND_NO_POS,
            TriggerType.PRODUCT_QUESTION, TriggerType.LEAD_LIST, TriggerType.ONBOARDING_STUCK)


def planning_card(persona: Persona, seed: int) -> MissionCard:
    """A sales mission for a planning persona, trigger fixed by the seed."""
    bank = default_bank()
    trigger = random.Random(f"{seed}:{persona.persona_id}").choice(TRIGGERS)
    return MissionCard(
        mission_id=f"gen_{persona.persona_id}_{seed}",
        merchant=Merchant(merchant_id=persona.persona_id, name=f"{persona.business_type} (simulated)",
                          business_type=persona.business_type, city=persona.city, language=persona.language),
        kind=MissionKind.SALES, goal="Sell the right payment product", door=TRIGGER_DOORS[trigger], trigger=trigger,
        why_now=f"Simulated {trigger.value}", starting_worries=bank.priors[trigger],
    )


async def simulate(planner, persona: Persona, seed: int, explore: float = 0.0, max_turns: int = 12) -> dict:
    """One text-mode call; with ``explore`` > 0 some moves are swapped for another legal move."""
    bank = default_bank()
    rng = random.Random(f"explore:{seed}:{persona.persona_id}")
    card = planning_card(persona, seed)
    tracker = BayesianBeliefTracker(bank)
    state = DialogueState(card=card, belief=tracker.start(card.starting_worries),
                          transcript=Transcript(mission_id=card.mission_id))
    twin = twin_a(persona, seed=seed)
    turns = [{"speaker": "merchant", "text": twin.opening()}]
    state.transcript.turns.append(Turn(speaker="merchant", text=turns[0]["text"]))
    for _ in range(max_turns):
        move = (await planner.plan(state)).move
        if explore and rng.random() < explore and move.type not in lib.TERMINAL_MOVES | {MoveType.TAKE_ACTION,
                                                                                       MoveType.DISCLOSE_AND_GREET}:
            options = [m for m in lib.legal_moves(state, bank, mission_product(card), consent_tool(card, state))
                       if m.type not in {MoveType.TAKE_ACTION, MoveType.DISCLOSE_AND_GREET}]
            move = rng.choice(options) if options else move
        top = state.belief.top(1)[0][0]
        state.moves.append(move)
        state.transcript.turns.append(Turn(speaker="agent", text=f"[{move.key()}]", move=move))
        turns.append({"speaker": "agent", "move": move.key(), "top_concern": top})
        if move.type == MoveType.DISCLOSE_AND_GREET:
            state.transcript.disclosed_ai = True
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
    return {"persona_id": persona.persona_id, "language": persona.language, "seed": seed,
            "trigger": card.trigger.value, "outcome": outcome, "turns": turns}


async def generate(seed: int, seeds_per_persona: int = 6) -> list[dict]:
    """Transcripts from the look-ahead planner, the baseline and an exploring baseline."""
    personas = [p for p in load_personas(split="planning") if not p.adversarial]
    policies = [(NRPAPlanner(seed=seed), 0.0), (RuleBasedPlanner(), 0.0), (RuleBasedPlanner(), 0.35)]
    calls = [simulate(planner, persona, seed * 100 + s, explore)
             for planner, explore in policies for persona in personas for s in range(seeds_per_persona)]
    return await asyncio.gather(*calls)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic transcripts and mine the Strategy Forest.")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--seeds-per-persona", type=int, default=6)
    parser.add_argument("--clusters", type=int, default=40)
    args = parser.parse_args(argv)
    transcripts = asyncio.run(generate(args.seed, args.seeds_per_persona))
    TRANSCRIPTS.parent.mkdir(parents=True, exist_ok=True)
    FOREST.parent.mkdir(parents=True, exist_ok=True)
    with open(TRANSCRIPTS, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(json.dumps(transcript, ensure_ascii=False) + "\n" for transcript in transcripts)
    forest = StrategyForest.fit(transcripts, k=args.clusters, seed=args.seed)
    forest.save(FOREST)
    closed = sum(t["outcome"] == "consented" for t in transcripts)
    print(f"{len(transcripts)} transcripts ({closed} consented) -> {len(forest.nodes)} clusters in {FOREST}")


if __name__ == "__main__":
    main()
