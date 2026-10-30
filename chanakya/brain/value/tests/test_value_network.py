"""The planner's value network (task N3): the hook, the network, self-play data and the safety rules first."""

import asyncio
import random

import numpy as np
import pytest

from chanakya.brain import moves as lib
from chanakya.brain.concern_bank import default_bank, load_personas
from chanakya.brain.contracts.fakes import sample_card, sample_state
from chanakya.brain.contracts.schemas import ConsentRecord, Move, MoveType, Turn
from chanakya.brain.planner_nrpa import BOOTSTRAP, NRPAPlanner, formula_value, outcome
from chanakya.brain.value.features import FEATURES, leaf_features
from chanakya.brain.value.network import ValueNetwork, configured_leaf_value, default_network, train
from chanakya.brain.value.selfplay import LeafRecorder, call, play_out
from chanakya.sim.judge import consent_chance, initial_state

BANK = default_bank()
PERSONA = next(p for p in load_personas(split="planning") if not p.adversarial)


def twin(**changes):
    state = initial_state(PERSONA)
    for key, value in changes.items():
        setattr(state, key, value)
    return state


def test_the_hook_values_only_unfinished_calls_and_the_default_is_the_formula():
    open_call, said_yes = twin(willingness=0.5), twin(consented=True)
    assert outcome(open_call, 2) == pytest.approx(BOOTSTRAP * consent_chance(open_call) - 0.06)
    assert outcome(open_call, 2, leaf_value=lambda *_: 0.9) == pytest.approx(0.9 - 0.06)
    assert outcome(said_yes, 2, leaf_value=lambda *_: -1.0) == pytest.approx(1.0 - 0.06)  # endings are never guessed
    assert formula_value(open_call) == pytest.approx(BOOTSTRAP * consent_chance(open_call))
    assert NRPAPlanner(BANK).leaf_value is None


def test_features_describe_the_leaf_with_a_fixed_length():
    state = sample_state(sample_card())
    x = leaf_features(twin(willingness=0.4, last_move_key="RESOLVE_CONCERN(hidden_charges)"), state, 2)
    assert x.shape == (len(FEATURES),) and np.isfinite(x).all()
    assert x[FEATURES.index("last_resolve_concern")] == 1.0 and x[FEATURES.index("willingness")] == 0.4


def test_the_network_learns_saves_and_refuses_other_features(tmp_path):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(1200, len(FEATURES)))
    y = np.tanh(x[:, 0] - 0.5 * x[:, 1]) * 0.6
    groups = np.asarray([f"p{i % 20}" for i in range(len(x))])
    net, report = train(x, y, groups, seed=1, epochs=60)
    assert report["validation_mse"] < float(np.var(y)) / 4
    path = tmp_path / "net.npz"
    net.save(path)
    loaded = ValueNetwork.load(path)
    assert np.allclose(loaded.predict(x[:5]), net.predict(x[:5])) and loaded.metadata["data_hash"]
    assert (net.predict(x * 100) <= 1.0).all() and (net.predict(x * 100) >= -0.5).all()
    loaded.metadata["features"] = ["something", "else"]
    np.savez(path, metadata=np.asarray(__import__("json").dumps(loaded.metadata)), **loaded.params)
    with pytest.raises(ValueError, match="different features"):
        ValueNetwork.load(path)


def test_the_setting_picks_formula_or_the_committed_network():
    assert configured_leaf_value("formula") is None
    leaf = configured_leaf_value("network")
    assert callable(leaf) and -0.5 <= leaf(twin(willingness=0.5), sample_state(sample_card()), 1) <= 1.0
    meta = default_network().metadata
    assert meta["features"] == FEATURES and {"seed", "date", "data_hash"} <= set(meta)


def test_self_play_is_seeded_and_plays_leaves_to_a_real_ending():
    async def rows(seed):
        recorder = LeafRecorder(rate=0.05, playouts=2, seed=seed)
        await call(NRPAPlanner(BANK, seed=seed, budget_ms=1e9, leaf_value=recorder), PERSONA, seed)
        return recorder

    first, again = asyncio.run(rows(3)), asyncio.run(rows(3))
    assert first.targets and first.targets == again.targets
    assert all(-0.7 <= t <= 1.0 for t in first.targets)
    value = play_out(twin(willingness=0.9, unresolved=set()), sample_state(sample_card()), random.Random(0))
    assert -0.7 <= value <= 1.0


# ── The forced safety rules always decide before the network ────────────


def state_after(*merchant_lines, consent_for=None):
    state = sample_state(sample_card())
    greet = Move(type=MoveType.DISCLOSE_AND_GREET)
    state.transcript.turns.append(Turn(speaker="merchant", text="Haan ji?"))
    if merchant_lines or consent_for:
        state.moves.append(greet)
        state.transcript.turns.append(Turn(speaker="agent", text="Namaste, main AI assistant hoon.", move=greet))
        state.transcript.disclosed_ai = True
    if consent_for:
        ask = Move(type=MoveType.CONFIRM_CONSENT, tool=consent_for)
        state.moves.append(ask)
        state.transcript.turns += [Turn(speaker="merchant", text="Achha."), Turn(speaker="agent", text="?", move=ask)]
    for line in merchant_lines:
        state.transcript.turns.append(Turn(speaker="merchant", text=line))
    if consent_for:
        state.transcript.consents.append(ConsentRecord(tool=consent_for, turn_index=len(state.transcript.turns) - 1,
                                                       utterance=merchant_lines[-1]))
    return state


@pytest.mark.parametrize("leaf", [lambda *_: 1.0, lambda *_: -0.5, "network"])
@pytest.mark.parametrize("lines,consent,expected", [
    ((), None, MoveType.DISCLOSE_AND_GREET),
    (("Mera payment fail ho gaya, ghar pe sab bahut pareshan hain, kisi insaan se baat karao.",), None, MoveType.ESCALATE),
    (("Nahi chahiye, call mat karo.",), None, MoveType.END_CALL_POLITELY),
    (("Mujhe apna OTP batao.",), None, MoveType.END_CALL_POLITELY),
    (("Haan, bhej do link.",), "send_onboarding_link", MoveType.TAKE_ACTION),
])
def test_forced_safety_rules_decide_before_any_leaf_value(leaf, lines, consent, expected):
    leaf_value = default_network().leaf_value if leaf == "network" else leaf
    state = state_after(*lines, consent_for=consent)
    plan = asyncio.run(NRPAPlanner(BANK, leaf_value=leaf_value).plan(state))
    assert plan.move.type == expected and plan.tree.get("searched") is False
    assert lib.is_legal(plan.move, state, BANK)


def test_the_network_planner_is_deterministic_for_a_seed():
    state = state_after("Koi hidden charge toh nahi hai na?")
    planner = NRPAPlanner(BANK, seed=5, budget_ms=1e9, leaf_value=default_network().leaf_value)
    first, again = asyncio.run(planner.plan(state)), asyncio.run(planner.plan(state))
    assert first.move.key() == again.move.key() and [c.score for c in first.candidates] == \
        [c.score for c in again.candidates]
