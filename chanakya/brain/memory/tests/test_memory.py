"""Semantic memory (task N2): nearest-moment lookup, the planner hook, saving and the setting. FakeEncoder only."""

import asyncio

import numpy as np
import pytest

from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts.fakes import sample_card, sample_state
from chanakya.brain.contracts.schemas import BeliefState, Move, MoveType, Turn
from chanakya.brain.memory import memory as mem
from chanakya.brain.memory.build import converse, lookup_times
from chanakya.brain.memory.memory import SemanticMemory, belief_vector, configured_memory, moments
from chanakya.brain.planner_nrpa import NRPAPlanner
from chanakya.neural.encoder import FakeEncoder
from chanakya.sim.voice import LinesVoice

BANK = default_bank()


def transcript(line, move, outcome, belief):
    return {"outcome": outcome, "turns": [
        {"speaker": "merchant", "text": "Haan ji?"},
        {"speaker": "agent", "move": "DISCLOSE_AND_GREET", "top_concern": "hidden_charges", "belief": belief},
        {"speaker": "merchant", "text": line},
        {"speaker": "agent", "move": move, "top_concern": "hidden_charges", "belief": belief}]}


CHARGES = {"hidden_charges": 0.8, "rental_cost": 0.2}
RENT = {"rental_cost": 0.9, "hidden_charges": 0.1}
TRANSCRIPTS = (
    [transcript("Koi chhupa hua charge toh nahi lagega na?", "RESOLVE_CONCERN(hidden_charges)", "consented", CHARGES)] * 6
    + [transcript("Koi chhupa hua charge toh nahi lagega na?", "RECOMMEND(soundbox)", "not_closed", CHARGES)] * 6
    + [transcript("Mahine ka kiraya bahut zyada hai.", "PROBE_CONCERN(rental_cost)", "consented", RENT)] * 6
)


def memory(k=8):
    return SemanticMemory.build(TRANSCRIPTS, FakeEncoder(), seed=1, k=k)


def test_moments_keep_the_line_the_belief_the_abstract_move_and_discounted_credit():
    found = moments(TRANSCRIPTS[:1])
    assert [m["move"] for m in found] == ["DISCLOSE_AND_GREET", "RESOLVE_CONCERN(@top)"]
    assert found[1]["text"].startswith("Koi chhupa") and found[1]["belief"] == CHARGES
    assert found[1]["success"] == 1.0 and found[0]["success"] == pytest.approx(0.9)


def test_the_nearest_moments_rank_the_move_that_worked_there():
    store = memory()
    best = store.lookup("Koi chhupa hua charge toh nahi?", CHARGES)
    assert best[0][0] == "RESOLVE_CONCERN(@top)" and best[0][1] > 0
    assert "RECOMMEND(soundbox)" not in [key for key, _, _ in best[:1]]
    assert store.lookup("Kiraya zyada hai", RENT)[0][0] == "PROBE_CONCERN(rental_cost)"
    assert store.last_lookup_ms >= 0


def test_the_belief_separates_moments_with_similar_words():
    probabilities = {cid: 0.0 for cid in BANK.ids} | {"rental_cost": 1.0}
    vector = belief_vector(probabilities, BANK.ids)
    assert np.isclose(np.linalg.norm(vector), 1.0) and vector[BANK.ids.index("rental_cost")] == pytest.approx(1.0)
    store = memory(k=6)
    neutral = "Achha, theek hai."  # words that match neither remembered line: the belief decides
    assert store.lookup(neutral, RENT)[0][0] == "PROBE_CONCERN(rental_cost)"
    assert store.lookup(neutral, CHARGES)[0][0] != "PROBE_CONCERN(rental_cost)"


def test_moves_for_fills_the_top_worry_like_the_forest():
    store = memory()
    state = sample_state(sample_card())
    state.belief = BeliefState(probabilities={cid: (0.6 if cid == "hidden_charges" else 0.4 / 12) for cid in BANK.ids})
    state.transcript.turns.append(Turn(speaker="merchant", text="Koi chhupa hua charge toh nahi lagega na?"))
    moves = store.moves_for(state)
    assert moves[0][0] == Move(type=MoveType.RESOLVE_CONCERN, concern="hidden_charges")


def test_saving_keeps_the_moments_and_refuses_another_encoder(tmp_path):
    store = memory()
    path = tmp_path / "memory.npz"
    store.save(path)
    loaded = SemanticMemory.load(FakeEncoder(), path)
    assert loaded.moves == store.moves and loaded.metadata["data_hash"] == store.metadata["data_hash"]
    assert loaded.lookup("charge", CHARGES)[0][0] == store.lookup("charge", CHARGES)[0][0]

    class OtherEncoder(FakeEncoder):
        name = "intfloat/multilingual-e5-small"

    with pytest.raises(ValueError, match="built with"):
        SemanticMemory.load(OtherEncoder(), path)


def test_the_setting_falls_back_to_the_forest_without_the_encoder(monkeypatch):
    def unavailable():
        raise mem.MemoryUnavailableError("no encoder")

    monkeypatch.setattr(mem, "default_memory", unavailable)
    from chanakya.brain.forest.forest import StrategyForest

    assert isinstance(configured_memory("neural"), StrategyForest)
    assert isinstance(configured_memory("forest"), StrategyForest)


def test_the_planner_takes_the_memory_and_still_obeys_the_forced_rules():
    store = memory()
    state = sample_state(sample_card())
    state.transcript.turns.append(Turn(speaker="merchant", text="Haan ji?"))
    plan = asyncio.run(NRPAPlanner(BANK, forest=store).plan(state))
    assert plan.move.type == MoveType.DISCLOSE_AND_GREET  # disclosure comes first whatever the memory says


def test_build_conversations_are_voiced_with_split_lines_and_keep_the_belief():
    from chanakya.brain.concern_bank import load_personas
    from chanakya.brain.planner_rules import RuleBasedPlanner

    persona = next(p for p in load_personas(split="planning") if not p.adversarial)
    rows = [{"concern": cid, "language": lang, "text": f"[{cid} line]"} for cid in BANK.ids
            for lang in ("hinglish", "hindi", "punjabi", "english")]
    convo = asyncio.run(converse(RuleBasedPlanner(BANK), persona, 3, LinesVoice(BANK, rows)))
    agent = [t for t in convo["turns"] if t["speaker"] == "agent"]
    assert agent and all(set(t["belief"]) == set(BANK.ids) for t in agent)
    assert convo["outcome"] in {"consented", "followup", "not_closed"}
    store = SemanticMemory.build([convo], FakeEncoder())
    p50, p90 = lookup_times(store, [{"text": "kiraya"}, {"text": "charges"}], count=2)
    assert 0 <= p50 <= p90
