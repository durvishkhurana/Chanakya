import asyncio
import json

from chanakya.brain.concern_bank import load_personas
from chanakya.brain.contracts.fakes import FakeLLM
from chanakya.brain.contracts.schemas import Move, MoveType
from chanakya.eval.harness import card_for, evaluate, main, merchant_set, run_call
from chanakya.eval.labeler import DeclaredLabeler, LLMLabeler
from chanakya.eval.metrics import CallRecord, summarise
from chanakya.eval.variants import VARIANTS

EVAL = load_personas(split="evaluation")


def test_merchant_set_uses_only_held_out_personas_and_the_adversarial_set():
    calls = merchant_set(100, adversarial_repeats=2)
    assert len(calls) == 100 + 2 * 4
    assert all(persona.split == "evaluation" for persona, _ in calls)
    assert {p.adversarial for p, _ in calls if p.adversarial} == {"angry", "prompt_injection", "fake_staff_otp",
                                                                 "distressed"}


def test_offline_runs_are_reproducible_and_cover_every_variant():
    first = asyncio.run(evaluate(VARIANTS, merchants=6, seed=3, adversarial_repeats=1))
    second = asyncio.run(evaluate(VARIANTS, merchants=6, seed=3, adversarial_repeats=1))
    assert set(first["summary"]) == set(VARIANTS)
    for name in VARIANTS:
        strip = [{k: v for k, v in call.items() if k != "latencies_ms"} for call in first["calls"][name]]
        again = [{k: v for k, v in call.items() if k != "latencies_ms"} for call in second["calls"][name]]
        assert strip == again
    assert first["summary"]["reactive"]["mission_success_rate"] == 0.0  # never asks, so never closes


def test_chanakya_never_breaks_safety_rules_and_escalates_distress():
    persona = next(p for p in EVAL if p.adversarial == "distressed")
    record = asyncio.run(run_call("chanakya", persona, 11))
    assert record.escalated and record.outcome == "escalated"
    for adversary in [p for p in EVAL if p.adversarial]:
        record = asyncio.run(run_call("chanakya", adversary, 5))
        assert [v for v in record.violations if v != "em_dash"] == []
        assert record.wrong_actions == 0


def test_actions_are_only_taken_after_consent():
    results = asyncio.run(evaluate(("actions_only", "chanakya"), merchants=10, seed=2, adversarial_repeats=0))
    for calls in results["calls"].values():
        for call in calls:
            assert all(a["consented"] for a in call["actions"] if a["verdict"] == "executed")
            if call["success"]:
                assert any(a["verdict"] == "executed" for a in call["actions"])


def test_metrics_summary():
    records = [
        CallRecord("v", "a", None, 1, "t", "consented", 4, [10.0, 20.0]),
        CallRecord("v", "b", None, 1, "t", "walked_away", 6, [30.0], ["overpromise"]),
        CallRecord("v", "c", "distressed", 1, "t", "escalated", 2, [5.0], escalated=True),
        CallRecord("v", "d", None, 1, "t", "declined", 3,
                   actions=[{"tool": "send_onboarding_link", "verdict": "blocked", "consented": False}]),
    ]
    summary = summarise(records)
    assert summary["calls"] == 3 and summary["mission_success_rate"] == 0.333
    assert summary["walk_away_rate"] == 0.333 and summary["turns_to_close"] == 4
    assert summary["escalation_precision"] == 1.0 and summary["escalation_recall"] == 1.0
    assert summary["wrong_action_rate"] == 0.25 and summary["safety_violations"] == 1
    assert summary["latency_p50_ms"] == 20.0


def test_llm_labeler_reads_one_move_and_drops_unknown_concerns():
    labeler = LLMLabeler(FakeLLM(json.dumps({"type": "RESOLVE_CONCERN", "concern": "aliens"})))
    move = asyncio.run(labeler.label("text", None, "merchant"))
    assert move.type == MoveType.RESOLVE_CONCERN and move.concern is None
    assert asyncio.run(LLMLabeler(FakeLLM("not json")).label("t", None, "m")) is None
    declared = Move(type=MoveType.DISCOVER_NEED)
    assert asyncio.run(DeclaredLabeler().label("t", declared, "m")) is declared


def test_one_command_writes_json_markdown_and_html(tmp_path, capsys):
    main(["--merchants", "4", "--adversarial-repeats", "1", "--seed", "1", "--out", str(tmp_path)])
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "python -m chanakya.eval.harness --merchants 4" in report and "| Mission success" in report
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["config"]["seed"] == 1 and set(data["summary"]) == set(VARIANTS)
    assert "<svg" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_cards_are_held_out_sales_missions():
    card = card_for(EVAL[0], 9)
    assert card.mission_id == f"eval_{EVAL[0].persona_id}_9" and "(simulated)" in card.merchant.name
