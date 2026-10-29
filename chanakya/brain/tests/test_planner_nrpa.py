import asyncio
import random

from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.fakes import sample_state
from chanakya.brain.contracts.interfaces import Planner
from chanakya.brain.contracts.schemas import ConsentRecord, MoveType, Turn
from chanakya.brain.planner_nrpa import NRPAPlanner, outcome
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.tests.test_planner_rules import GREETED, converse, with_turns
from chanakya.sim.judge import initial_state

BANK = default_bank()
FIXED_SET = [p for p in load_personas(split="planning") if not p.adversarial][:15]


def plan(planner, state):
    return asyncio.run(planner.plan(state))


def open_state():
    state = with_turns(Turn(speaker="merchant", text="Rent zyada toh nahi padega?"), moves=[GREETED])
    state.transcript.disclosed_ai = True
    state.belief = state.belief.model_copy(update={"probabilities": {"rental_cost": 0.6, "hidden_charges": 0.3,
                                                                     "just_busy": 0.1}})
    return state


def test_same_seed_and_conversation_give_the_same_plan():
    first, second = plan(NRPAPlanner(BANK, seed=4), open_state()), plan(NRPAPlanner(BANK, seed=4), open_state())
    assert first.move == second.move and first.candidates == second.candidates
    assert isinstance(NRPAPlanner(BANK), Planner)


def test_sampled_merchants_cover_a_tied_belief_evenly_whatever_the_seed():
    state = open_state()
    state.belief = state.belief.model_copy(update={"probabilities": {"rental_cost": 0.32, "hidden_charges": 0.32,
                                                                     "just_busy": 0.32, "not_needed": 0.04}})
    for seed in range(10):
        planner = NRPAPlanner(BANK, samples=6)
        merchants = planner.sample_merchants(state, random.Random(seed))
        firsts = [m.persona.hidden_concerns[0] for m in merchants if m.unresolved]
        # Stratified draws: no worry is left out or doubled up by luck, so the plan does not swing with the seed.
        assert max(firsts.count(c) for c in set(firsts)) - min(firsts.count(c) for c in set(firsts)) <= 1, firsts


def test_safety_and_consent_rules_are_never_searched():
    planner = NRPAPlanner(BANK)
    assert plan(planner, sample_state()).move.type == MoveType.DISCLOSE_AND_GREET
    distressed = with_turns(Turn(speaker="merchant", text="Kisi insaan se baat karao, bahut pareshan hain."),
                            moves=[GREETED])
    assert plan(planner, distressed).move.type == MoveType.ESCALATE
    consented = with_turns(Turn(speaker="merchant", text="Haan, bhej do"), moves=[GREETED],
                           consents=[ConsentRecord(tool="send_onboarding_link", turn_index=0, utterance="Haan")])
    result = plan(planner, consented)
    assert result.move.type == MoveType.TAKE_ACTION and result.tree["searched"] is False


def test_stopping_is_scored_like_any_other_move_and_the_tree_is_reported():
    result = plan(NRPAPlanner(BANK), open_state())
    keys = [c.move.key() for c in result.candidates]
    assert "END_CALL_POLITELY" in keys and "CONFIRM_CONSENT(send_onboarding_link)" in keys
    assert 3 <= len(keys) <= 5 and result.tree["searched"] and len(result.tree["candidates"]) == len(keys)
    assert all(c.visits == result.tree["samples"] for c in result.candidates)


def test_time_budget_falls_back_to_the_baseline_move():
    planner = NRPAPlanner(BANK, budget_ms=0.01)
    result = plan(planner, open_state())
    baseline = asyncio.run(RuleBasedPlanner(BANK).plan(open_state())).move
    assert result.fallback and result.move.type == baseline.type and result.move.concern == baseline.concern
    assert plan(NRPAPlanner(BANK, budget_ms=300), open_state()).elapsed_ms < 300


def test_outcome_values_consent_over_follow_up_over_walking_away():
    persona = FIXED_SET[0]
    yes, later, gone, open_ = (initial_state(persona) for _ in range(4))
    yes.consented, later.followup_agreed = True, True
    gone.ended, gone.willingness = True, 0.05
    assert outcome(yes, 2) > outcome(later, 2) > outcome(open_, 2) > outcome(gone, 2)


def test_lookahead_beats_the_baseline_on_a_fixed_twin_a_set():
    async def rate(make):
        results = [await converse(make(), p, seed) for p in FIXED_SET for seed in range(2)]
        return sum(twin.state.consented for _, twin in results) / len(results)

    baseline = asyncio.run(rate(lambda: RuleBasedPlanner(BANK)))
    lookahead = asyncio.run(rate(lambda: NRPAPlanner(BANK, budget_ms=2000)))
    assert lookahead > baseline, (lookahead, baseline)
