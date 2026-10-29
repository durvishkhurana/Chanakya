import asyncio
import json
import math

from chanakya.brain.concern_bank import load_personas
from chanakya.brain.contracts.schemas import MoveType, Turn
from chanakya.brain.forest.forest import (
    StrategyForest,
    abstract,
    cosine,
    default_forest,
    embed,
    instantiate,
    wilson_lower,
)
from chanakya.brain.forest.generate import FOREST, TRANSCRIPTS, simulate
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.brain.planner_rules import RuleBasedPlanner
from chanakya.brain.tests.test_planner_rules import GREETED, with_turns


def test_wilson_lower_bound_distrusts_small_samples():
    assert wilson_lower(2, 2) < wilson_lower(90, 100) < 0.9
    assert wilson_lower(0, 0) == 0.0 and wilson_lower(0, 10) == 0.0


def test_embedding_is_deterministic_unit_length_and_works_across_scripts():
    a, b = embed("Koi hidden charge toh nahi?"), embed("Koi hidden charge toh nahi?")
    assert a == b and math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-9)
    hindi = embed("क्या कोई छुपा हुआ चार्ज है?")
    assert cosine(hindi, embed("क्या इसमें छुपा चार्ज है?")) > cosine(hindi, embed("Mujhe time nahi hai"))


def transcript(merchant, move, outcome, top=None):
    return {"outcome": outcome, "turns": [{"speaker": "merchant", "text": merchant},
                                          {"speaker": "agent", "move": move, "top_concern": top}]}


def test_forest_prefers_the_move_with_the_better_record():
    data = ([transcript("Rent kitna hai?", "RESOLVE_CONCERN(rental_cost)", "consented", "rental_cost")] * 8
            + [transcript("Rent kitna hai?", "RECOMMEND(soundbox)", "not_closed", "rental_cost")] * 8
            + [transcript("Haan, bhej do", "TAKE_ACTION(send_onboarding_link)", "consented")] * 8)
    forest = StrategyForest.fit(data, k=2, seed=0)
    best = forest.lookup("Rent kitna padega?", None, "rental_cost")[0]
    assert best[0] == "RESOLVE_CONCERN(@top)" and best[1] > 0.5
    def recommend_record():
        return [sum(n.stats.get("RECOMMEND(soundbox)", [0, 0])[i] for n in forest.nodes) for i in (0, 1)]

    successes, trials = recommend_record()
    forest.update(transcript("Rent kitna hai?", "RECOMMEND(soundbox)", "consented", "rental_cost"))
    assert recommend_record() == [successes + 1, trials + 1]


def test_top_worry_moves_are_abstracted_and_filled_back_in():
    assert abstract("RESOLVE_CONCERN(rental_cost)", "rental_cost") == "RESOLVE_CONCERN(@top)"
    assert abstract("RESOLVE_CONCERN(rental_cost)", "hidden_charges") == "RESOLVE_CONCERN(rental_cost)"
    assert instantiate("PROBE_CONCERN(@top)", "setup_hassle").concern == "setup_hassle"
    assert instantiate("PROBE_CONCERN(@top)", None) is None
    assert instantiate("CONFIRM_CONSENT(send_onboarding_link)", None).tool == "send_onboarding_link"


def test_committed_transcripts_are_multilingual_and_labelled():
    rows = [json.loads(line) for line in TRANSCRIPTS.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 500
    assert {row["language"] for row in rows} >= {"hi-IN", "pa-IN"}
    assert {row["outcome"] for row in rows} >= {"consented", "not_closed"}
    planning = {p.persona_id for p in load_personas(split="planning")}
    assert {row["persona_id"] for row in rows} <= planning, "transcripts must never use held-out personas"


def test_committed_forest_lookup_is_fast_and_sensible():
    forest = default_forest()
    assert forest is not None and len(forest.nodes) == 40
    times = []
    for text in ("Koi hidden charge toh nahi hai na?", "Haan, theek hai, aap bhej do.", "ਮੇਰੇ ਗਾਹਕ ਤਾਂ ਕੈਸ਼ ਦਿੰਦੇ ਹਨ।"):
        forest.lookup(text, "DISCLOSE_AND_GREET", None)
        times.append(forest.last_lookup_ms)
    assert max(times) < 50
    assert forest.lookup("Haan, theek hai, aap bhej do.", "CONFIRM_CONSENT(send_onboarding_link)", None)[0][0] \
        == "TAKE_ACTION(send_onboarding_link)"
    assert FOREST.exists()


def test_forest_moves_become_planner_candidates():
    state = with_turns(Turn(speaker="merchant", text="Iska rent zyada toh nahi padega?"), moves=[GREETED])
    state.transcript.disclosed_ai = True
    state.belief = state.belief.model_copy(update={"probabilities": {"rental_cost": 0.7, "hidden_charges": 0.2,
                                                                     "just_busy": 0.1}})
    planner = NRPAPlanner(forest=default_forest())
    keys = [m.key() for m in planner.candidates(state, asyncio.run(RuleBasedPlanner().plan(state)).move)]
    assert "RESOLVE_CONCERN(rental_cost)" in keys and keys[-1] == "END_CALL_POLITELY"


def test_simulated_transcripts_are_reproducible():
    persona = next(p for p in load_personas(split="planning") if not p.adversarial)
    first = asyncio.run(simulate(RuleBasedPlanner(), persona, 5, explore=0.3))
    second = asyncio.run(simulate(RuleBasedPlanner(), persona, 5, explore=0.3))
    assert first == second and first["turns"][1]["move"] == MoveType.DISCLOSE_AND_GREET.value
