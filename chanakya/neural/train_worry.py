"""Train, calibrate and measure the worry head (task N1).

    python -m chanakya.neural.encoder --download        # once
    python -m chanakya.neural.train_worry --seed 7      # writes data/neural/worry_head.npz and the results

The N0 train split is divided once (seeded, per label) into fit lines and a 15% validation split. The head
trains on the fit lines, stops early and is calibrated on validation only; the no-worry threshold is tuned on
validation too. The N0 test split (another model family) and the hand-written set are never seen before
scoring. A logistic head and a one-hidden-layer network are both trained; the lower validation loss wins.
"""

import argparse
import asyncio
import hashlib
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from chanakya.brain.belief import LexicalScorer
from chanakya.brain.concern_bank import default_bank
from chanakya.neural import human_set
from chanakya.neural.baseline import decide, evaluate_scorer, score_all, tune
from chanakya.neural.head import bce, ece, fit_temperature, train
from chanakya.neural.paraphrase import NONE, OUT, load
from chanakya.neural.scorer import HEAD, EmbeddingScorer

VALIDATION_SHARE = 0.15


def split_validation(rows: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    """Per label, a seeded 15% of rows for validation; the rest for fitting."""
    rng, groups = random.Random(seed), defaultdict(list)
    for row in rows:
        groups[row["concern"]].append(row)
    fit, validation = [], []
    for label in sorted(groups):
        items = groups[label][:]
        rng.shuffle(items)
        cut = max(1, round(len(items) * VALIDATION_SHARE))
        validation += items[:cut]
        fit += items[cut:]
    return fit, validation


def targets(rows: list[dict], concerns: list[str]) -> np.ndarray:
    """One column per worry: 1 where the line holds it; no-worry lines are all zeros."""
    index = {cid: i for i, cid in enumerate(concerns)}
    y = np.zeros((len(rows), len(concerns)))
    for r, row in enumerate(rows):
        if row["concern"] != NONE:
            y[r, index[row["concern"]]] = 1.0
    return y


def encode(encoder, rows: list[dict], batch: int = 64) -> np.ndarray:
    return np.vstack([encoder.encode([r["text"] for r in rows[i:i + batch]]) for i in range(0, len(rows), batch)])


async def human_metrics(scorer, threshold: float, rows: list[dict]) -> dict:
    """Accuracy on the hand-written set, overall and per slice: right when the pick is one of the line's worries,
    or no worry when the line holds none."""
    scores, latencies = await score_all(scorer, rows)
    correct = []
    for row, score in zip(rows, scores, strict=True):
        pick = decide(score, threshold)
        correct.append(not row["concerns"] if pick == NONE else pick in row["concerns"])
    by_slice = defaultdict(list)
    for row, ok in zip(rows, correct, strict=True):
        by_slice[row["slice"]].append(ok)
    return {"lines": len(rows), "accuracy": round(sum(correct) / len(rows), 3),
            "by_slice": {s: round(sum(v) / len(v), 3) for s, v in sorted(by_slice.items())},
            "latency_ms_p50": round(sorted(latencies)[len(latencies) // 2], 2)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and measure the N1 worry head.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--hidden", type=int, default=128, help="Hidden units of the network head (0 skips it)")
    parser.add_argument("--head", type=Path, default=HEAD)
    parser.add_argument("--out", type=Path, default=Path("docs/results/neural-worry-scorer"))
    args = parser.parse_args()

    from chanakya.neural.encoder import load_encoder

    encoder = load_encoder()
    if encoder is None:
        raise SystemExit("encoder missing: pip install -r requirements-neural.txt, then python -m chanakya.neural.encoder --download")
    bank = default_bank()
    concerns = list(bank.ids)
    fit_rows, val_rows = split_validation(load("train"), args.seed)
    test_rows = load("test")
    x_fit, x_val = encode(encoder, fit_rows), encode(encoder, val_rows)
    y_fit, y_val = targets(fit_rows, concerns), targets(val_rows, concerns)

    candidates = {}
    for hidden in sorted({0, args.hidden}):
        candidates[hidden] = train(x_fit, y_fit, x_val, y_val, concerns, hidden=hidden, seed=args.seed)
    chosen = min(candidates.values(), key=lambda h: h.meta["validation_bce"])
    raw = chosen.probabilities(x_val, calibrated=False)
    temperature = fit_temperature(chosen, x_val, y_val)
    calibrated = chosen.probabilities(x_val)
    data_hash = hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]
    chosen.meta.update({"encoder": encoder.name, "trained_on": str(date.today()), "data_sha256": data_hash,
                        "fit_lines": len(fit_rows), "validation_lines": len(val_rows)})
    args.head.parent.mkdir(parents=True, exist_ok=True)
    chosen.save(args.head)

    scorer = EmbeddingScorer(encoder, chosen)
    lexical = LexicalScorer(bank)
    results = {
        "command": f"python -m chanakya.neural.train_worry --seed {args.seed} --hidden {args.hidden}",
        "encoder": encoder.name, "data_sha256": data_hash, "seed": args.seed,
        "heads": {("logistic" if h == 0 else f"network ({h} hidden)"): round(c.meta["validation_bce"], 4)
                  for h, c in candidates.items()},
        "chosen": "logistic" if chosen.meta["hidden"] == 0 else f"network ({chosen.meta['hidden']} hidden)",
        "calibration": {"temperature": round(temperature, 3), "ece_before": round(ece(raw, y_val), 4),
                        "ece_after": round(ece(calibrated, y_val), 4), "bce_before": round(bce(raw, y_val), 4),
                        "bce_after": round(bce(calibrated, y_val), 4)},
        "test_split": {"lexical (today)": asyncio.run(evaluate_scorer(lexical, val_rows, test_rows)),
                       "embedding (N1)": asyncio.run(evaluate_scorer(scorer, val_rows, test_rows))},
        "human_set": None,
    }
    human_rows = human_set.load()
    if human_rows and not human_set.problems():
        thresholds = {name: tune(list(zip(asyncio.run(score_all(s, val_rows))[0], (r["concern"] for r in val_rows),
                                          strict=True)))
                      for name, s in (("lexical (today)", lexical), ("embedding (N1)", scorer))}
        results["human_set"] = {name: asyncio.run(human_metrics(s, thresholds[name], human_rows))
                                for name, s in (("lexical (today)", lexical), ("embedding (N1)", scorer))}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in results.items() if k != "test_split"}, indent=2, ensure_ascii=False))
    for name, r in results["test_split"].items():
        print(f"{name}: accuracy {r['accuracy']} (worry {r['worry_accuracy']}, no worry {r['no_worry_accuracy']}), "
              f"by language {r['by_language']}, p50 {r['latency_ms_p50']} ms")


if __name__ == "__main__":
    main()
