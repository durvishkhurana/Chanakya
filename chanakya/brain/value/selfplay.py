"""Self-play data for the value network: the current planner against Twin-A on planning personas, seeded.

At a sample of the look-ahead's unfinished leaves (exactly where the planner would apply its formula) the
recorder keeps what is known there, then plays that simulated call on to its end against the deterministic judge
with a playout policy that only uses what an agent could know (the worry just voiced, the belief, its own asks).
The target is how the call ended, minus the call time it took; the formula's guess is kept alongside to compare.
"""

import copy
import random
from dataclasses import dataclass, field

import numpy as np

from chanakya.brain import moves as lib
from chanakya.brain.belief import BayesianBeliefTracker
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.fakes import sample_card, sample_state
from chanakya.brain.contracts.schemas import ConsentRecord, Merchant, Move, MoveType, Persona, TriggerType, Turn
from chanakya.brain.planner_nrpa import TURN_COST, NRPAPlanner, formula_value, terminal_value
from chanakya.brain.planner_rules import consent_tool, mission_product
from chanakya.sim.judge import TwinState, consent_chance, judge_turn
from chanakya.sim.twin import twin_a

from .features import leaf_features

TRIGGERS = (TriggerType.CALLBACK_REQUEST, TriggerType.UPI_RISING_NO_SOUNDBOX, TriggerType.CARD_DEMAND_NO_POS,
            TriggerType.PRODUCT_QUESTION, TriggerType.LEAD_LIST, TriggerType.ONBOARDING_STUCK)
MAX_PLAYOUT_TURNS = 10
EXPLORE = 0.2


def playout_move(sim: TwinState, dialogue, asks: int, rng: random.Random) -> Move:
    """A competent but imperfect next move from what an agent knows: answer the voiced worry, else ask or probe."""
    open_concerns = [cid for cid, _ in lib.open_concerns(dialogue)[:3]]
    ask = Move(type=MoveType.CONFIRM_CONSENT, tool=consent_tool(dialogue.card, dialogue))
    if rng.random() < EXPLORE:
        pool = [Move(type=MoveType.RESOLVE_CONCERN, concern=c) for c in open_concerns]
        pool += [Move(type=MoveType.PROBE_CONCERN, concern=c) for c in open_concerns]
        pool += [ask, Move(type=MoveType.RECOMMEND, product=mission_product(dialogue.card)),
                 Move(type=MoveType.SCHEDULE_FOLLOWUP)]
        return rng.choice(pool)
    if sim.last_voiced and sim.last_voiced in open_concerns + [sim.last_voiced]:
        return Move(type=MoveType.RESOLVE_CONCERN, concern=sim.last_voiced)
    if asks < 2 and (consent_chance(sim) >= 0.4 or not open_concerns):
        return ask
    target = open_concerns[0] if open_concerns else "not_needed"
    return Move(type=MoveType.PROBE_CONCERN, concern=target)


def play_out(sim: TwinState, dialogue, rng: random.Random) -> float:
    """Play an unfinished simulated call to its end; returns the ending's score minus the extra call time."""
    sim = copy.deepcopy(sim)
    asks = sum(1 for m in dialogue.moves if m.type == MoveType.CONFIRM_CONSENT)
    for turn in range(1, MAX_PLAYOUT_TURNS + 1):
        move = playout_move(sim, dialogue, asks, rng)
        asks += move.type == MoveType.CONFIRM_CONSENT
        judge_turn(sim, move, "", rng)
        value = terminal_value(sim)
        if value is not None:
            return value - TURN_COST * turn
    return formula_value(sim) - TURN_COST * MAX_PLAYOUT_TURNS


@dataclass
class LeafRecorder:
    """A ``leaf_value`` hook that samples leaves, records them with their played-out ending, and returns the formula."""

    rate: float
    playouts: int
    seed: int
    rows: list[np.ndarray] = field(default_factory=list)
    targets: list[float] = field(default_factory=list)
    formulas: list[float] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    group: str = ""

    def __post_init__(self):
        self.rng = random.Random(f"selfplay:{self.seed}")

    def __call__(self, sim: TwinState, dialogue, turns: int) -> float:
        guess = formula_value(sim, dialogue, turns)
        if dialogue is not None and self.rng.random() < self.rate:
            self.rows.append(leaf_features(sim, dialogue, turns))
            self.targets.append(sum(play_out(sim, dialogue, self.rng) for _ in range(self.playouts)) / self.playouts)
            self.formulas.append(guess)
            self.groups.append(self.group)
        return guess


async def call(planner: NRPAPlanner, persona: Persona, seed: int, max_turns: int = 14):
    """One text-mode call: planner moves against Twin-A's template voice, consent captured as on a live call."""
    bank = default_bank()
    trigger = random.Random(f"{seed}:{persona.persona_id}:trigger").choice(TRIGGERS)
    card = sample_card(mission_id=f"selfplay_{persona.persona_id}_{seed}", trigger=trigger,
                       merchant=Merchant(merchant_id=persona.persona_id, name="simulated",
                                         business_type=persona.business_type, city=persona.city,
                                         language=persona.language),
                       starting_worries=bank.priors[trigger])
    tracker = BayesianBeliefTracker(bank)
    state = sample_state(card)
    state.belief = tracker.start(card.starting_worries)
    twin = twin_a(persona, seed=seed)
    state.transcript.turns.append(Turn(speaker="merchant", text=twin.opening()))
    for _ in range(max_turns):
        move = (await planner.plan(state)).move
        state.moves.append(move)
        state.transcript.turns.append(Turn(speaker="agent", text=f"[{move.key()}]", move=move))
        state.transcript.disclosed_ai |= move.type == MoveType.DISCLOSE_AND_GREET
        if move.type == MoveType.TAKE_ACTION or move.type in lib.TERMINAL_MOVES:
            break
        reply = await twin.respond(f"[{move.key()}]", move)
        merchant = Turn(speaker="merchant", text=reply.text)
        state.transcript.turns.append(merchant)
        if move.type == MoveType.CONFIRM_CONSENT and lib.explicit_consent(reply.text):
            state.transcript.consents.append(ConsentRecord(tool=move.tool, turn_index=len(state.transcript.turns) - 1,
                                                           utterance=reply.text))
        state.belief = await tracker.update(state.belief, merchant, state.transcript.turns)
        if reply.ended:
            break
    return state, twin


async def generate(seeds: int, seed: int = 7, rate: float = 0.02, playouts: int = 4, split: str = "planning"):
    """Self-play on every non-adversarial persona of ``split`` x ``seeds`` call seeds; returns x, y, formula, groups."""
    recorder = LeafRecorder(rate=rate, playouts=playouts, seed=seed)
    # No time budget: the data must not depend on how fast the machine is.
    planner = NRPAPlanner(seed=seed, budget_ms=1e9, leaf_value=recorder)
    personas = [p for p in load_personas(split=split) if not p.adversarial]
    for persona in personas:
        recorder.group = persona.persona_id
        for call_seed in range(seeds):
            await call(planner, persona, seed * 100_000 + call_seed)
    return (np.vstack(recorder.rows), np.asarray(recorder.targets), np.asarray(recorder.formulas),
            np.asarray(recorder.groups), len(personas) * seeds)
