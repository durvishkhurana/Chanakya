"""The worry head learns, calibrates and round-trips; the scorer picks and falls back without a real model."""

import asyncio

import numpy as np

from chanakya.brain.belief import LexicalScorer, LLMScorer
from chanakya.brain.concern_bank import default_bank
from chanakya.neural.encoder import FakeEncoder
from chanakya.neural.head import WorryHead, ece, fit_temperature, train
from chanakya.neural.scorer import EmbeddingScorer, configured_worry_scorer, select_scorer

LINES = {"rent": ["kiraya kitna hai", "monthly rent kitna", "rent bahut zyada hai", "kiraya kam karo"],
         "busy": ["abhi busy hoon", "baad mein call karo", "customer hai abhi", "time nahi hai abhi"],
         "none": ["haan ji boliye", "achha theek hai", "namaste", "haan sun raha hoon"]}


def toy():
    encoder, texts, labels = FakeEncoder(), [], []
    for label, lines in LINES.items():
        texts += lines
        labels += [label] * len(lines)
    x = encoder.encode(texts)
    y = np.array([[label == "rent", label == "busy"] for label in labels], dtype=float)
    return encoder, x, y


def test_the_network_head_learns_two_worries_and_keeps_filler_low(tmp_path):
    encoder, x, y = toy()
    head = train(x, y, x, y, ["rental_cost", "just_busy"], hidden=16, seed=1, lr=0.05, epochs=400)
    p = head.probabilities(encoder.encode(["kiraya kitna hai", "baad mein call karo", "haan ji boliye"]))
    assert p[0, 0] > 0.7 and p[1, 1] > 0.7 and p[2].max() < 0.3
    assert head.base_rates == {"rental_cost": 1 / 3, "just_busy": 1 / 3}
    path = tmp_path / "head.npz"
    head.save(path)
    again = WorryHead.load(path)
    assert np.allclose(again.probabilities(x), head.probabilities(x)) and again.meta["hidden"] == 16


def test_temperature_scaling_does_not_make_calibration_worse():
    _, x, y = toy()
    head = train(x, y, x, y, ["rental_cost", "just_busy"], hidden=0, seed=1, lr=0.05, epochs=300)
    before = ece(head.probabilities(x, calibrated=False), y)
    fit_temperature(head, x, y)
    assert ece(head.probabilities(x), y) <= before + 1e-9


def test_embedding_scorer_returns_one_probability_per_worry_and_exposes_base_rates():
    encoder, x, y = toy()
    head = train(x, y, x, y, ["rental_cost", "just_busy"], hidden=0, seed=1, lr=0.05, epochs=300)
    scores = asyncio.run(EmbeddingScorer(encoder, head).score("kiraya kitna hai", []))
    assert set(scores) == {"rental_cost", "just_busy"} and all(0 <= p <= 1 for p in scores.values())
    assert EmbeddingScorer(encoder, head).base_rates == head.base_rates


def test_selection_keeps_the_old_default_and_falls_back_when_the_model_is_missing(monkeypatch):
    bank = default_bank()
    monkeypatch.delenv("WORRY_SCORER", raising=False)
    assert configured_worry_scorer() is None
    assert isinstance(select_scorer(None, bank), LexicalScorer)
    assert isinstance(select_scorer(None, bank, llm=object()), LLMScorer)
    monkeypatch.setattr("chanakya.neural.scorer.load_embedding_scorer", lambda: None)
    assert isinstance(select_scorer("embedding", bank), LexicalScorer)
    monkeypatch.setenv("WORRY_SCORER", "embedding")
    assert configured_worry_scorer() == "embedding"


def test_the_brain_agent_and_the_eval_variant_follow_worry_scorer(monkeypatch):
    import pytest

    from agent.brain_agent import BrainAgent
    from chanakya.eval.variants import make_variant

    encoder, x, y = toy()
    fake = EmbeddingScorer(encoder, train(x, y, x, y, ["rental_cost", "just_busy"], hidden=0, seed=1, lr=0.05, epochs=50))
    monkeypatch.setattr("chanakya.neural.scorer.load_embedding_scorer", lambda: fake)
    monkeypatch.delenv("WORRY_SCORER", raising=False)
    assert isinstance(BrainAgent().scorer, LexicalScorer)
    assert isinstance(BrainAgent(llm=object()).scorer, LLMScorer), "unset keeps the LLM scorer on live calls"
    monkeypatch.setenv("WORRY_SCORER", "embedding")
    assert BrainAgent(llm=object()).scorer is fake
    assert make_variant("chanakya_embedding").agent.scorer is fake
    monkeypatch.setattr("chanakya.neural.scorer.load_embedding_scorer", lambda: None)
    with pytest.raises(RuntimeError, match="worry_head"):
        make_variant("chanakya_embedding")
