"""The worry head (task N1): 13 independent sigmoid outputs on top of the sentence encoder.

Independent sigmoids, not a softmax, because a line can hold two worries and a filler line should score
near zero for all thirteen. The head is a small neural network in numpy (one hidden ReLU layer, or none
for a plain logistic model), trained full-batch with Adam on binary cross-entropy, stopped early on a
validation split, then calibrated with one temperature fitted on that same validation split.
"""

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


def bce(p: np.ndarray, y: np.ndarray) -> float:
    """Mean binary cross-entropy over every (line, worry) pair."""
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over every (line, worry) pair: how far stated confidence is from reality."""
    p, y = p.ravel(), y.ravel()
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for low, high in itertools.pairwise(edges):
        inside = (p > low) & (p <= high) if low > 0 else (p >= low) & (p <= high)
        if inside.any():
            total += inside.mean() * abs(p[inside].mean() - y[inside].mean())
    return float(total)


@dataclass
class WorryHead:
    concerns: list[str]
    weights: list[np.ndarray]  # [W, b] for a logistic head, [W1, b1, W2, b2] with one hidden layer
    temperature: float = 1.0
    base_rates: dict[str, float] = field(default_factory=dict)  # share of training lines holding each worry
    meta: dict = field(default_factory=dict)

    def logits(self, x: np.ndarray) -> np.ndarray:
        if len(self.weights) == 2:
            return x @ self.weights[0] + self.weights[1]
        w1, b1, w2, b2 = self.weights
        return np.maximum(x @ w1 + b1, 0) @ w2 + b2

    def probabilities(self, x: np.ndarray, calibrated: bool = True) -> np.ndarray:
        return sigmoid(self.logits(x) / (self.temperature if calibrated else 1.0))

    def save(self, path: Path) -> None:
        arrays = {f"w{i}": w for i, w in enumerate(self.weights)}
        np.savez(path, **arrays, temperature=self.temperature,
                 info=json.dumps({"concerns": self.concerns, "base_rates": self.base_rates, "meta": self.meta}))

    @classmethod
    def load(cls, path: Path) -> "WorryHead":
        data = np.load(path)
        info = json.loads(str(data["info"]))
        weights = [data[f"w{i}"] for i in range(sum(k.startswith("w") for k in data.files))]
        return cls(info["concerns"], weights, float(data["temperature"]), info["base_rates"], info["meta"])


def train(x: np.ndarray, y: np.ndarray, x_val: np.ndarray, y_val: np.ndarray, concerns: list[str], hidden: int = 128,
          seed: int = 7, lr: float = 0.01, l2: float = 1e-4, epochs: int = 3000, patience: int = 200) -> WorryHead:
    """Fit the head with Adam on binary cross-entropy; keep the weights with the lowest validation loss."""
    rng = np.random.default_rng(seed)
    dims = [x.shape[1], hidden, y.shape[1]] if hidden else [x.shape[1], y.shape[1]]
    weights = []
    for fan_in, fan_out in itertools.pairwise(dims):
        weights += [rng.normal(0, np.sqrt(2 / fan_in), (fan_in, fan_out)), np.zeros(fan_out)]
    head = WorryHead(concerns, weights)
    m = [np.zeros_like(w) for w in weights]
    v = [np.zeros_like(w) for w in weights]
    best, best_weights, waited = np.inf, [w.copy() for w in weights], 0
    for step in range(1, epochs + 1):
        grads = gradients(head, x, y, l2)
        for i, g in enumerate(grads):
            m[i] = 0.9 * m[i] + 0.1 * g
            v[i] = 0.999 * v[i] + 0.001 * g * g
            head.weights[i] -= lr * (m[i] / (1 - 0.9 ** step)) / (np.sqrt(v[i] / (1 - 0.999 ** step)) + 1e-8)
        loss = bce(head.probabilities(x_val, calibrated=False), y_val)
        if loss < best - 1e-5:
            best, best_weights, waited = loss, [w.copy() for w in head.weights], 0
        else:
            waited += 1
            if waited >= patience:
                break
    head.weights = best_weights
    head.base_rates = {cid: float(rate) for cid, rate in zip(concerns, y.mean(axis=0), strict=True)}
    head.meta.update({"hidden": hidden, "seed": seed, "lr": lr, "l2": l2, "steps": step, "validation_bce": best})
    return head


def gradients(head: WorryHead, x: np.ndarray, y: np.ndarray, l2: float) -> list[np.ndarray]:
    """Backpropagation of mean binary cross-entropy plus an L2 penalty on the weight matrices."""
    n = len(x)
    if len(head.weights) == 2:
        w, _ = head.weights
        delta = (sigmoid(x @ w + head.weights[1]) - y) / n
        return [x.T @ delta + l2 * w, delta.sum(axis=0)]
    w1, b1, w2, b2 = head.weights
    pre = x @ w1 + b1
    hidden = np.maximum(pre, 0)
    delta2 = (sigmoid(hidden @ w2 + b2) - y) / n
    delta1 = (delta2 @ w2.T) * (pre > 0)
    return [x.T @ delta1 + l2 * w1, delta1.sum(axis=0), hidden.T @ delta2 + l2 * w2, delta2.sum(axis=0)]


def fit_temperature(head: WorryHead, x_val: np.ndarray, y_val: np.ndarray) -> float:
    """The single temperature that minimises validation cross-entropy (log-spaced grid from 0.25 to 4)."""
    logits = head.logits(x_val)
    grid = np.exp(np.linspace(np.log(0.25), np.log(4.0), 121))
    head.temperature = float(min(grid, key=lambda t: bce(sigmoid(logits / t), y_val)))
    return head.temperature
