"""Generate self-play data, train the value network and write its training report.

    python -m chanakya.brain.value.train --seed 7 --seeds 70

Planning personas only. Writes ``data/neural/value_net.npz`` (weights, seed, date, data hash) and
``docs/results/neural-value-network/training.md``; the raw self-play rows go to ``.state/`` and are not committed.
"""

import argparse
import asyncio
import json
import sys
import time

import numpy as np

from chanakya.brain.concern_bank import ROOT

from .network import WEIGHTS, train
from .selfplay import generate

RESULTS = ROOT / "docs" / "results" / "neural-value-network"


def report(meta: dict, formula_mse: float, formula_val_mse: float, calls: int, seconds: float, command: str) -> str:
    """The training report: how well the network and the formula predict played-out endings on held-out personas."""
    return "\n".join([
        "# Value network: training", "",
        f"- Command: `{command}`",
        (f"- Self-play: {calls} calls, the look-ahead planner against Twin-A (template voice) on planning personas; "
        f"{meta['train_rows'] + meta['validation_rows']} sampled leaves, each played to its end; {seconds:.0f} s"),
        (f"- Validation: leaves from {len(meta['validation_personas'])} planning personas never trained on "
        f"({', '.join(meta['validation_personas'])})"),
        (f"- Network: {len(meta['features'])} features, tanh layers {meta['hidden']}, seed {meta['seed']}, "
        f"data hash `{meta['data_hash']}`, {meta['date']}"), "",
        "| Predictor of the played-out ending | Validation MSE | All rows MSE |", "|---|---|---|",
        f"| Formula (`0.8 x consent_chance`) | {formula_val_mse:.4f} | {formula_mse:.4f} |",
        f"| Value network | {meta['validation_mse']:.4f} | train {meta['train_mse']:.4f} |", "",
        ("Lower is better. This only says the network predicts self-play endings; whether it helps the planner is "
        "measured on held-out evaluation personas in `README.md`."),
    ]) + "\n"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Train the planner's value network from self-play.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--seeds", type=int, default=70, help="call seeds per planning persona")
    parser.add_argument("--rate", type=float, default=0.01, help="share of look-ahead leaves recorded")
    parser.add_argument("--playouts", type=int, default=4)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    x, y, formula, groups, calls = asyncio.run(generate(args.seeds, args.seed, args.rate, args.playouts))
    seconds = time.perf_counter() - started
    state = ROOT / ".state"
    state.mkdir(exist_ok=True)
    np.savez(state / f"value_selfplay_{args.seed}.npz", x=x, y=y, formula=formula, groups=groups)
    net, meta = train(x, y, groups, seed=args.seed)
    val = np.isin(groups, meta["validation_personas"])
    formula_val = float(np.mean((formula[val] - y[val]) ** 2))
    net.metadata |= {"formula_validation_mse": round(formula_val, 5), "selfplay_calls": calls}
    net.save(WEIGHTS)
    RESULTS.mkdir(parents=True, exist_ok=True)
    command = "python -m chanakya.brain.value.train " + " ".join(argv if argv is not None else sys.argv[1:])
    (RESULTS / "training.md").write_text(report(net.metadata, float(np.mean((formula - y) ** 2)), formula_val, calls,
                                                seconds, command), encoding="utf-8")
    print(json.dumps({k: v for k, v in net.metadata.items() if k != "features"}, indent=1))


if __name__ == "__main__":
    main()
