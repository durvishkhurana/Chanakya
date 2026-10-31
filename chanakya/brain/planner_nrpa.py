"""Look-ahead planner: Nested Rollout Policy Adaptation over moves against belief-sampled Twin-A merchants.

For each candidate move, merchants are sampled from the current belief (which hidden worries they may
hold), and NRPA (Rosin 2011; NRPA-GD and UP-NRPA, docs/IDEA.md section 9) searches the next two turns
against Twin-A's deterministic judge. Every candidate, including ESCALATE and END_CALL_POLITELY, is
scored by the same outcome function, so stopping a dead call is a decision, not a fallback.
"""

import copy
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from chanakya.brain.contracts.schemas import (
    DialogueState,
    Move,
    MoveType,
    Persona,
    PlanResult,
    ScoredMove,
    ToolCall,
)
from chanakya.sim.judge import Intent, TwinState, consent_chance, initial_state, judge_turn

from . import moves as lib
from .concern_bank import ConcernBank, default_bank
from .planner_rules import PERMISSION_RULES, WINBACK_RULES, RuleBasedPlanner, consent_tool, mission_product

# Rules that are never searched: safety and consent decisions always follow the baseline.
FORCED_RULES = {"disclose_first", "distress", "declined", "sensitive_request", "consent_given", "finished",
                "after_followup", "confirm_unprompted_yes", "discover_need"}
REWARD_CONSENT = 1.0
REWARD_FOLLOWUP = 0.45
PENALTY_WALK_AWAY = -0.35
TURN_COST = 0.03
BOOTSTRAP = 0.8


@dataclass
class Rollout:
    score: float
    sequence: list[tuple[str, str]]


# The value of a call that is still going when the look-ahead stops: (simulated twin, conversation, turns) -> value.
LeafValue = Callable[[TwinState, DialogueState, int], float]


def terminal_value(state: TwinState) -> float | None:
    """The score of a simulated call that has ended, or None while it is still going."""
    if state.consented:
        return REWARD_CONSENT
    if state.followup_agreed:
        return REWARD_FOLLOWUP
    if state.ended:
        return PENALTY_WALK_AWAY if state.willingness <= 0.08 or state.patience <= 0 else 0.0
    return None


def formula_value(state: TwinState, dialogue: DialogueState | None = None, turns: int = 0) -> float:
    """The hand-written horizon guess for an unfinished call: a fraction of today's chance of a yes."""
    return BOOTSTRAP * consent_chance(state)


def outcome(state: TwinState, turns: int, dialogue: DialogueState | None = None,
            leaf_value: LeafValue | None = None) -> float:
    """One score for every way a simulated call can end, minus call time.

    An unfinished call is valued by ``leaf_value`` (the N3 value network) when given, else by the formula.
    """
    value = terminal_value(state)
    if value is None:
        value = (leaf_value or formula_value)(state, dialogue, turns)
    return value - TURN_COST * turns


class NRPAPlanner:
    """Implements ``Planner``. Deterministic for a given seed and conversation."""

    def __init__(self, bank: ConcernBank | None = None, samples: int = 12, level: int = 2, iterations: int = 4,
                 depth: int = 2, budget_ms: float = 300.0, alpha: float = 1.0, seed: int = 0,
                 evaluations: int = 8, forest=None, leaf_value: LeafValue | None = None):
        if not 1 <= level <= 2:
            raise ValueError("NRPA level must be 1 or 2")
        self.bank = bank or default_bank()
        self.baseline = RuleBasedPlanner(self.bank)
        self.samples, self.level, self.iterations = samples, level, iterations
        self.depth, self.budget_ms, self.alpha, self.seed = depth, budget_ms, alpha, seed
        self.evaluations = evaluations
        # Strategy Forest (A9): moves that worked in similar states become the first candidates.
        self.forest = forest
        # N3: a learned value for unfinished simulated calls (PLANNER_VALUE=network); None keeps the formula.
        self.leaf_value = leaf_value

    # ── simulation model ────────────────────────────────────────────────

    def strata(self, rng: random.Random) -> list[float]:
        """One uniform draw per sample, one in each of ``samples`` equal slices of [0, 1), in random order."""
        values = [(i + rng.random()) / self.samples for i in range(self.samples)]
        rng.shuffle(values)
        return values

    def sample_merchants(self, state: DialogueState, rng: random.Random) -> list[TwinState]:
        """Merchants consistent with the belief: hidden worries drawn from it, conversation so far replayed."""
        open_concerns = lib.open_concerns(state)
        resolved = lib.resolved_concerns(state)
        agent_turns = sum(1 for t in state.transcript.turns if t.speaker == "agent")
        card = state.card
        # Stratified draws (Latin hypercube): the few sampled merchants cover the belief evenly instead of by luck,
        # so the chosen move does not swing with the seed when worries are close (a 3-way tie splits 2/2/2 of 6).
        u_none, u_count, *u_picks = (self.strata(rng) for _ in range(4))
        merchants = []
        for index in range(self.samples):
            pool = [(cid, p) for cid, p in open_concerns if p > 0]
            hidden = []
            # With little belief mass left on open worries, the merchant may simply have none left.
            top_p = open_concerns[0][1] if open_concerns else 0.0
            none_left = u_none[index] < max(0.0, min(0.85, 1 - 2.5 * top_p))
            count = 0 if none_left else (1 if u_count[index] < 0.6 else 2)
            for draw in range(count):
                if not pool:
                    break
                total = sum(p for _, p in pool)
                pick, acc = u_picks[draw][index] * total, 0.0
                for i, (cid, p) in enumerate(pool):
                    acc += p
                    if acc >= pick:
                        hidden.append(cid)
                        pool.pop(i)
                        break
            persona = Persona(
                persona_id=f"belief_{index}", business_type=card.merchant.business_type, city=card.merchant.city,
                language=card.merchant.language, patience=0.6, busyness=0.5, tech_comfort=0.5,
                hidden_concerns=hidden or ["not_needed"], willingness_prior=0.35,
            )
            twin = initial_state(persona)
            if not hidden:
                twin.unresolved = set()
            twin.willingness = min(1.0, 0.3 + 0.18 * len(resolved))
            twin.patience = max(0.1, twin.patience - 0.04 * agent_turns)
            twin.turns = agent_turns
            twin.disclosed = lib.disclosed(state)
            twin.last_move_key = state.moves[-1].key() if state.moves else None
            twin.voiced = {cid for cid in hidden if state.belief.probabilities.get(cid, 0) >= 0.4}
            top = open_concerns[0] if open_concerns else None
            twin.last_voiced = top[0] if top and top[1] >= 0.5 and top[0] in hidden else None
            merchants.append(twin)
        return merchants

    def options(self, state: DialogueState, intent: Intent, twin: TwinState) -> list[Move]:
        """Moves the rollout may take after the merchant shows ``intent``."""
        if intent.kind in {"hang_up", "decline"}:
            return [Move(type=MoveType.END_CALL_POLITELY)]
        concerns = [c for c, _ in lib.open_concerns(state)[:3]]
        if intent.concern and intent.concern not in concerns:
            concerns.append(intent.concern)
        moves = [Move(type=MoveType.RESOLVE_CONCERN, concern=c) for c in concerns]
        moves += [Move(type=MoveType.PROBE_CONCERN, concern=c) for c in concerns]
        moves += [Move(type=MoveType.CONFIRM_CONSENT, tool=consent_tool(state.card, state)),
                  Move(type=MoveType.RECOMMEND, product=mission_product(state.card)),
                  Move(type=MoveType.SCHEDULE_FOLLOWUP), Move(type=MoveType.END_CALL_POLITELY)]
        return moves

    @staticmethod
    def code(intent: Intent, move: Move) -> tuple[str, str]:
        """The policy key: what the merchant just did, and the move with whether it targets that worry."""
        relation = "same" if move.concern and move.concern == intent.concern else "other"
        return intent.kind, f"{move.type.value}:{relation if move.concern else '-'}"

    def rollout(self, state: DialogueState, first: Move, twin: TwinState, policy: dict, rng: random.Random) -> Rollout:
        """Play ``first`` then policy-sampled moves for ``depth`` turns against a copy of ``twin``."""
        sim = copy.deepcopy(twin)
        intent = judge_turn(sim, first, "", rng)
        sequence, turns = [], 1
        while not sim.ended and not sim.consented and turns < self.depth:
            options = self.options(state, intent, sim)
            weights = [math.exp(policy.get(self.code(intent, m), 0.0)) for m in options]
            pick = rng.random() * sum(weights)
            for move, weight in zip(options, weights, strict=True):
                pick -= weight
                if pick <= 0:
                    break
            sequence.append(self.code(intent, move))
            intent = judge_turn(sim, move, "", rng)
            turns += 1
        return Rollout(outcome(sim, turns, state, self.leaf_value), sequence)

    def adapt(self, policy: dict, best: Rollout) -> dict:
        """Standard NRPA adaptation: raise the best sequence's codes, lower the alternatives in proportion."""
        updated = dict(policy)
        for code in best.sequence:
            updated[code] = updated.get(code, 0.0) + self.alpha
        return updated

    def nrpa(self, level: int, state: DialogueState, first: Move, twin: TwinState, policy: dict,
             rng: random.Random, deadline: float) -> tuple[Rollout, dict]:
        """Nested search: level 0 is one rollout; each level adapts the policy toward its best sequence."""
        if level == 0 or time.perf_counter() > deadline:
            return self.rollout(state, first, twin, policy, rng), policy
        best = Rollout(-math.inf, [])
        for _ in range(self.iterations):
            result, _ = self.nrpa(level - 1, state, first, twin, dict(policy), rng, deadline)
            if result.score >= best.score:
                best = result
            policy = self.adapt(policy, best)
        return best, policy

    def value(self, state: DialogueState, first: Move, twin: TwinState, rng: random.Random, deadline: float) -> float:
        """Expected score of ``first``: NRPA adapts the follow-up policy, then fresh rollouts are averaged.

        The merchant's replies are random, so the best single rollout would be a lucky draw; the mean of
        rollouts under the adapted policy estimates what the move is actually worth.
        """
        _, policy = self.nrpa(self.level, state, first, twin, {}, rng, deadline)
        scores = [self.rollout(state, first, twin, policy, rng).score for _ in range(self.evaluations)]
        return sum(scores) / len(scores)

    # ── planner interface ───────────────────────────────────────────────

    def candidates(self, state: DialogueState, baseline: Move) -> list[Move]:
        """The baseline's move plus the strongest alternatives, always including asking for consent and stopping."""
        product, tool = mission_product(state.card), consent_tool(state.card, state)
        done = {m.key() for m in state.moves}
        open_concerns = [cid for cid, _ in lib.open_concerns(state)[:2]]
        mined = [move for move, _ in self.forest.moves_for(state, limit=2)] if self.forest is not None else []
        ranked = [baseline, *mined, Move(type=MoveType.CONFIRM_CONSENT, tool=tool)]
        for cid in open_concerns:
            ranked += [Move(type=MoveType.RESOLVE_CONCERN, concern=cid), Move(type=MoveType.PROBE_CONCERN, concern=cid)]
        ranked += [Move(type=MoveType.RECOMMEND, product=product), Move(type=MoveType.DISCOVER_NEED),
                   Move(type=MoveType.SCHEDULE_FOLLOWUP)]
        asks = sum(1 for m in state.moves if m.type == MoveType.CONFIRM_CONSENT)
        chosen, keys = [], set()
        for move in ranked:
            repeat = move.key() in done and not (move.type == MoveType.CONFIRM_CONSENT and asks < 2)
            if move.key() in keys or (repeat and move is not baseline) or not lib.is_legal(move, state, self.bank):
                continue
            chosen.append(move)
            keys.add(move.key())
            if len(chosen) == 4:
                break
        chosen.append(Move(type=MoveType.END_CALL_POLITELY))
        return chosen

    async def plan(self, state: DialogueState) -> PlanResult:
        """Search the candidates within the time budget; fall back to the baseline move if it runs out."""
        started = time.perf_counter()
        deadline = started + self.budget_ms / 1000
        baseline_move, rule = self.baseline.choose(state)
        if (rule in FORCED_RULES or rule in WINBACK_RULES or rule in PERMISSION_RULES
                or not lib.is_legal(baseline_move, state, self.bank)):
            result = await self.baseline.plan(state)
            return result.model_copy(update={"tree": {"rule": rule, "searched": False}})
        rng = random.Random(f"{self.seed}:{state.card.mission_id}:{len(state.transcript.turns)}")
        merchants = self.sample_merchants(state, rng)
        candidates = self.candidates(state, baseline_move.model_copy(update={"reason": rule}))
        scored, tree = [], []
        for move in candidates:
            scores = []
            for twin in merchants:
                if time.perf_counter() > deadline:
                    break
                scores.append(self.value(state, move, twin, rng, deadline))
            if not scores:
                break
            mean = sum(scores) / len(scores)
            scored.append(ScoredMove(move=move, score=round(mean, 4), visits=len(scores)))
            tree.append({"move": move.key(), "score": round(mean, 4), "samples": [round(s, 3) for s in scores]})
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        if len(scored) < len(candidates):
            move = baseline_move.model_copy(update={"reason": f"{rule} (time budget)"})
            return PlanResult(move=move, candidates=scored, elapsed_ms=elapsed, fallback=True,
                              tree={"rule": rule, "searched": True, "candidates": tree, "budget_ms": self.budget_ms})
        best = max(scored, key=lambda s: (s.score, s.move.key() == baseline_move.key()))
        move = best.move.model_copy(update={"reason": best.move.reason or f"look-ahead {best.score:+.2f}"})
        return PlanResult(move=move, candidates=sorted(scored, key=lambda s: -s.score), elapsed_ms=elapsed,
                          tree={"rule": rule, "searched": True, "candidates": tree, "samples": len(merchants)})

    async def reconsider(self, state: DialogueState, call: ToolCall) -> bool:
        """Pre-write reconsideration uses the same checks as the baseline."""
        return await self.baseline.reconsider(state, call)
