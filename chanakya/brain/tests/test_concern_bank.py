import json

import pytest

from chanakya.brain import concern_bank as cb
from chanakya.brain.contracts.schemas import TriggerType


def test_repository_bank_is_consistent():
    concerns, priors, personas = cb.load_concerns(), cb.load_priors(), cb.load_personas()
    assert cb.validate(concerns, priors, personas, cb.knowledge_node_ids()) == []
    assert 10 <= len(concerns) <= 15


def test_every_resolve_condition_points_to_an_existing_knowledge_node():
    nodes = cb.knowledge_node_ids()
    assert {"qr", "soundbox", "card_machine", "gateway", "payment_links", "onboarding"} <= nodes
    for concern in cb.load_concerns().values():
        for condition in concern.resolve_conditions:
            assert condition.knowledge_node_ids
            assert set(condition.knowledge_node_ids) <= nodes, concern.concern_id


def test_every_trigger_has_a_prior_over_known_concerns():
    bank = cb.default_bank()
    for trigger in TriggerType:
        prior = bank.prior_for(trigger)
        assert set(prior) == set(bank.ids)
        assert abs(sum(prior.values()) - 1) < 1e-9
        top = max(prior, key=prior.get)
        assert top in bank.priors[trigger]


def test_idea_priors_are_copied_exactly():
    priors = cb.load_priors()
    assert priors[TriggerType.ONBOARDING_STUCK] == {"setup_hassle": 0.45, "data_privacy": 0.3, "trust_in_caller": 0.25}
    assert priors[TriggerType.CARD_MACHINE_PRICE_QUESTION]["per_swipe_charges"] == 0.55


def test_smoothing_keeps_unlisted_concerns_reachable():
    bank = cb.default_bank()
    prior = bank.prior_for(TriggerType.CALLBACK_REQUEST, smoothing=0.1)
    assert prior["data_privacy"] > 0
    assert prior["hidden_charges"] == pytest.approx(0.9 * 0.5 + 0.1 / len(bank.ids))
    with pytest.raises(ValueError):
        bank.prior_for(TriggerType.CALLBACK_REQUEST, smoothing=1.0)


def test_personas_cover_both_splits_and_the_adversarial_set():
    personas = cb.load_personas()
    assert len(personas) >= 40
    planning, evaluation = cb.load_personas(split="planning"), cb.load_personas(split="evaluation")
    assert planning and evaluation and len(planning) + len(evaluation) == len(personas)
    assert {p.city for p in planning}.isdisjoint({p.city for p in evaluation})
    kinds = {p.adversarial for p in evaluation if p.adversarial}
    assert kinds == {"angry", "prompt_injection", "fake_staff_otp", "distressed"}


def test_validation_reports_broken_references(tmp_path):
    concerns = cb.load_concerns()
    priors = cb.load_priors()
    priors[TriggerType.LEAD_LIST] = {"made_up": 1.0}
    del priors[TriggerType.FIELD_NOTE]
    problems = cb.validate(concerns, priors, cb.load_personas(), {"qr"})
    assert any("unknown knowledge node soundbox" in p for p in problems)
    assert "lead_list: unknown concern made_up" in problems
    assert "field_note: no starting-worries prior" in problems


def test_duplicate_concern_ids_are_rejected(tmp_path):
    raw = json.loads((cb.DATA / "concerns" / "concerns.json").read_text(encoding="utf-8"))
    raw["concerns"].append(raw["concerns"][0])
    path = tmp_path / "concerns.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        cb.load_concerns(path)


def test_generator_reproduces_the_committed_personas(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", cb.DATA / "personas" / "generate_personas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    module.main()
    committed = (cb.DATA / "personas" / "personas.json").read_text(encoding="utf-8")
    assert (tmp_path / "personas.json").read_text(encoding="utf-8") == committed
