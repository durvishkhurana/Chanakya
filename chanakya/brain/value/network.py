"""A small numpy value network: standardised features, two tanh layers, one linear output, trained with Adam."""

import hashlib
import itertools
import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np

from chanakya.brain.concern_bank import DATA
from chanakya.brain.contracts.schemas import DialogueState
from chanakya.sim.judge import TwinState

from .features import FEATURES, leaf_features

WEIGHTS = DATA / "neural" / "value_net.npz"
VALUE_RANGE = (-0.5, 1.0)  # a walk-away scores -0.35, a yes 1.0


class ValueNetwork:
    """Predicts how an unfinished simulated call ends from what is known at the leaf."""

    def __init__(self, params: dict[str, np.ndarray], metadata: dict | None = None):
        self.params = params
        self.metadata = metadata or {}

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Values for a batch of feature rows (or one row)."""
        p = self.params
        z = (np.atleast_2d(x) - p["mean"]) / p["std"]
        h1 = np.tanh(z @ p["w1"] + p["b1"])
        h2 = np.tanh(h1 @ p["w2"] + p["b2"])
        return np.clip((h2 @ p["w3"] + p["b3"]).ravel(), *VALUE_RANGE)

    def leaf_value(self, state: TwinState, dialogue: DialogueState | None, turns: int) -> float:
        """The planner's ``leaf_value`` hook."""
        return float(self.predict(leaf_features(state, dialogue, turns))[0])

    def save(self, path: Path = WEIGHTS) -> None:
        """Write weights and metadata (seed, date, data hash) to a small ``.npz``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, metadata=np.asarray(json.dumps(self.metadata)), **self.params)

    @classmethod
    def load(cls, path: Path = WEIGHTS) -> "ValueNetwork":
        """Read a saved network."""
        with np.load(path) as data:
            metadata = json.loads(str(data["metadata"]))
            params = {key: data[key] for key in data.files if key != "metadata"}
        if metadata.get("features") != FEATURES:
            raise ValueError(f"{path} was trained on different features; retrain it")
        return cls(params, metadata)


def data_hash(x: np.ndarray, y: np.ndarray) -> str:
    """A short fingerprint of the training data, stored with the weights."""
    return hashlib.sha256(np.ascontiguousarray(x).tobytes() + np.ascontiguousarray(y).tobytes()).hexdigest()[:16]


def train(x: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = 7, hidden: tuple[int, int] = (32, 16),
          epochs: int = 300, batch: int = 256, lr: float = 3e-3, patience: int = 25,
          validation: float = 0.15) -> tuple[ValueNetwork, dict]:
    """Fit on a seeded split by ``groups`` (personas), so validation calls come from personas never trained on.

    Early stopping keeps the weights with the lowest validation loss. Returns the network and its report.
    """
    rng = np.random.default_rng(seed)
    names = np.unique(groups)
    held = set(rng.choice(names, size=max(1, round(len(names) * validation)), replace=False).tolist())
    val = np.isin(groups, list(held))
    xt, yt, xv, yv = x[~val], y[~val], x[val], y[val]
    mean, std = xt.mean(axis=0), xt.std(axis=0)
    std[std < 1e-8] = 1.0
    sizes = [x.shape[1], *hidden, 1]
    params = {"mean": mean, "std": std}
    for i, (a, b) in enumerate(itertools.pairwise(sizes), start=1):
        params[f"w{i}"] = rng.normal(0, np.sqrt(1 / a), (a, b))
        params[f"b{i}"] = np.zeros(b)
    trainable = [k for k in params if k[0] in "wb"]
    m = {k: np.zeros_like(params[k]) for k in trainable}
    v = {k: np.zeros_like(params[k]) for k in trainable}
    net = ValueNetwork(params)

    def loss(xs, ys):
        return float(np.mean((net.predict(xs) - ys) ** 2))

    best, best_params, waited, step = np.inf, None, 0, 0
    for _epoch in range(epochs):
        order = rng.permutation(len(xt))
        for start in range(0, len(order), batch):
            idx = order[start:start + batch]
            z = (xt[idx] - mean) / std
            h1 = np.tanh(z @ params["w1"] + params["b1"])
            h2 = np.tanh(h1 @ params["w2"] + params["b2"])
            out = (h2 @ params["w3"] + params["b3"]).ravel()
            d_out = (2 / len(idx)) * (out - yt[idx])[:, None]
            grads = {"w3": h2.T @ d_out, "b3": d_out.sum(axis=0)}
            d_h2 = (d_out @ params["w3"].T) * (1 - h2 ** 2)
            grads |= {"w2": h1.T @ d_h2, "b2": d_h2.sum(axis=0)}
            d_h1 = (d_h2 @ params["w2"].T) * (1 - h1 ** 2)
            grads |= {"w1": z.T @ d_h1, "b1": d_h1.sum(axis=0)}
            step += 1
            for k in trainable:
                m[k] = 0.9 * m[k] + 0.1 * grads[k]
                v[k] = 0.999 * v[k] + 0.001 * grads[k] ** 2
                params[k] -= lr * (m[k] / (1 - 0.9 ** step)) / (np.sqrt(v[k] / (1 - 0.999 ** step)) + 1e-8)
        current = loss(xv, yv)
        if current < best - 1e-6:
            best, best_params, waited = current, {k: a.copy() for k, a in params.items()}, 0
        else:
            waited += 1
            if waited >= patience:
                break
    net = ValueNetwork(best_params)
    report = {"train_rows": len(xt), "validation_rows": len(xv), "validation_personas": sorted(held),
              "validation_mse": round(best, 5), "train_mse": round(loss(xt, yt), 5)}
    net.metadata = {"features": FEATURES, "seed": seed, "date": datetime.now(UTC).date().isoformat(),
                    "data_hash": data_hash(x, y), "hidden": list(hidden), **report}
    return net, report


@lru_cache(maxsize=1)
def default_network() -> ValueNetwork:
    """The committed value network (``data/neural/value_net.npz``)."""
    return ValueNetwork.load()


def configured_leaf_value(planner_value: str):
    """The planner's ``leaf_value`` for a ``PLANNER_VALUE`` setting: None keeps the formula."""
    if planner_value == "network":
        return default_network().leaf_value
    return None
