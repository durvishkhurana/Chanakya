import asyncio

from chanakya.eval.winback import evaluate, report


def test_the_win_back_evaluation_is_reproducible_and_never_acts_on_not_needed():
    first = asyncio.run(evaluate(seed=7, repeats=1))
    again = asyncio.run(evaluate(seed=7, repeats=1))
    assert first["summary"] == again["summary"]
    summary = first["summary"]
    assert summary["calls"] == len(first["config"]["personas"]) >= 8
    assert summary["identified_not_needed_pitches_or_writes"] == 0
    assert summary["not_needed_writes"] == 0 and summary["safety_violations"] == 0
    assert 0 <= summary["reason_accuracy"] <= 1 and 0 <= summary["fix_rate"] <= 1
    assert "Reason accuracy" in report(first, "python -m chanakya.eval.winback --seed 7 --repeats 1")
