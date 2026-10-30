"""Phase-0 baselines for the neural worry scorer (task N0): what any new scorer has to beat.

Every scorer makes the same 14-way call on held-out lines: one of the 13 worries, or no worry. A scorer
says "no worry" when its strongest evidence is below a threshold tuned on the train split only. Encoders
are compared with a nearest-centroid classifier over train-split embeddings, so the score reflects the
embedding, not a trained head.

    python -m chanakya.neural.baseline --llm-sample 112 --out docs/results/neural-baseline
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path

from chanakya.brain.belief import LexicalScorer, LLMScorer
from chanakya.brain.concern_bank import default_bank
from chanakya.neural.paraphrase import NONE, OUT, load

ENCODERS = {
    "fastembed:paraphrase-multilingual-MiniLM-L12-v2": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "st:multilingual-e5-small": "intfloat/multilingual-e5-small",
}


class NoEvidence:
    """A scorer that sees nothing; stands in when the LLM scorer's call fails."""

    def __init__(self, bank):
        self.ids = bank.ids

    async def score(self, text: str, history: list) -> dict[str, float]:
        return {cid: 0.0 for cid in self.ids}


def decide(scores: dict[str, float], threshold: float) -> str:
    """The worry with the strongest evidence, or no worry when even that is weak."""
    best = max(scores, key=scores.get)
    return best if scores[best] >= threshold else NONE


def tune(scored: list[tuple[dict, str]]) -> float:
    """The no-worry threshold with the best train-split accuracy."""
    candidates = sorted({round(max(s.values()), 3) for s, _ in scored} | {0.0})
    return max(candidates, key=lambda t: sum(decide(s, t) == label for s, label in scored))


def metrics(rows: list[dict], predictions: list[str], latencies: list[float]) -> dict:
    """Accuracy over all 14 labels, on worry lines and on no-worry lines, per language, and speed."""
    def accuracy(pairs):
        pairs = list(pairs)
        return round(sum(p == r["concern"] for r, p in pairs) / len(pairs), 3) if pairs else None

    pairs = list(zip(rows, predictions, strict=True))
    by_language = defaultdict(list)
    for row, prediction in pairs:
        by_language[row["language"]].append((row, prediction))
    return {
        "lines": len(rows),
        "accuracy": accuracy(pairs),
        "worry_accuracy": accuracy((r, p) for r, p in pairs if r["concern"] != NONE),
        "no_worry_accuracy": accuracy((r, p) for r, p in pairs if r["concern"] == NONE),
        "by_language": {lang: accuracy(items) for lang, items in sorted(by_language.items())},
        "latency_ms_p50": round(statistics.median(latencies), 2),
        "latency_ms_p90": round(sorted(latencies)[int(0.9 * (len(latencies) - 1))], 2),
    }


async def score_all(scorer, rows: list[dict]) -> tuple[list[dict], list[float]]:
    scores, latencies = [], []
    for row in rows:
        started = time.perf_counter()
        scores.append(await scorer.score(row["text"], []))
        latencies.append((time.perf_counter() - started) * 1000)
    return scores, latencies


async def evaluate_scorer(scorer, train: list[dict], test: list[dict]) -> dict:
    """Tune the no-worry threshold on train, then score test."""
    train_scores, _ = await score_all(scorer, train)
    threshold = tune(list(zip(train_scores, (r["concern"] for r in train), strict=True)))
    test_scores, latencies = await score_all(scorer, test)
    return {"threshold": threshold, **metrics(test, [decide(s, threshold) for s in test_scores], latencies)}


def stratified(rows: list[dict], per_label: int, seed: int) -> list[dict]:
    """``per_label`` rows of each label, spread across languages, chosen with ``seed``."""
    rng, groups = random.Random(seed), defaultdict(list)
    for row in rows:
        groups[row["concern"]].append(row)
    return [row for label in sorted(groups) for row in rng.sample(groups[label], min(per_label, len(groups[label])))]


def evaluate_encoder(name: str, train: list[dict], test: list[dict]) -> dict:
    """Nearest-centroid accuracy over the encoder's embeddings, plus load and per-line encode time."""
    import numpy as np

    started = time.perf_counter()
    if name.startswith("fastembed:"):
        from fastembed import TextEmbedding

        model = TextEmbedding(ENCODERS[name])
        encode = lambda texts: np.array(list(model.embed(texts)))
    else:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(ENCODERS[name], device="cpu")
        encode = lambda texts: model.encode([f"query: {t}" for t in texts], normalize_embeddings=True)
    load_s = time.perf_counter() - started
    unit = lambda m: m / np.linalg.norm(m, axis=1, keepdims=True)
    train_vectors = unit(encode([r["text"] for r in train]))
    labels = sorted({r["concern"] for r in train})
    centroids = unit(np.stack([train_vectors[[r["concern"] == lab for r in train]].mean(axis=0) for lab in labels]))
    latencies, predictions = [], []
    for row in test:
        started = time.perf_counter()
        vector = unit(encode([row["text"]]))
        latencies.append((time.perf_counter() - started) * 1000)
        predictions.append(labels[int(np.argmax(centroids @ vector[0]))])
    return {"model": ENCODERS[name], "load_s": round(load_s, 1), "dimensions": int(train_vectors.shape[1]),
            **metrics(test, predictions, latencies)}


def report(results: dict) -> str:
    lines = ["# Neural worry scorer: phase-0 baselines", "",
             (f"Held-out test lines from `{results['test_model']}`; train lines from `{results['train_model']}`. "
              f"Command: `{results['command']}`."), "",
             "| Scorer | Lines | All 14 labels | Worry lines | No-worry lines | p50 ms | p90 ms |",
             "|---|---|---|---|---|---|---|"]
    for name, r in results["scorers"].items():
        lines.append(f"| {name} | {r['lines']} | {r['accuracy']} | {r['worry_accuracy']} | {r['no_worry_accuracy']} "
                     f"| {r['latency_ms_p50']} | {r['latency_ms_p90']} |")
    lines += ["", "| Scorer | " + " | ".join(results["languages"]) + " |",
              "|---|" + "---|" * len(results["languages"])]
    for name, r in results["scorers"].items():
        lines.append(f"| {name} | " + " | ".join(str(r["by_language"].get(lang)) for lang in results["languages"]) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase-0 worry scorer baselines.")
    parser.add_argument("--data", type=Path, default=OUT)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--llm-sample", type=int, default=0, help="Lines per label for the LLM scorer (0 skips it)")
    parser.add_argument("--encoders", default=",".join(ENCODERS), help="Comma-separated, or empty to skip")
    parser.add_argument("--out", type=Path, default=Path("docs/results/neural-baseline"))
    args = parser.parse_args()
    bank = default_bank()
    train, test = load("train", args.data), load("test", args.data)
    results = {"train_model": train[0]["model"], "test_model": test[0]["model"],
               "languages": sorted({r["language"] for r in test}), "scorers": {},
               "command": f"python -m chanakya.neural.baseline --seed {args.seed} --llm-sample {args.llm_sample}"}
    results["scorers"]["lexical (today)"] = asyncio.run(evaluate_scorer(LexicalScorer(bank), train, test))
    if args.llm_sample:
        from dotenv import load_dotenv

        from chanakya.brain.contracts.llm import default_llm

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        llm = default_llm()
        scorer = LLMScorer(llm, bank)
        scorer.fallback = NoEvidence(bank)  # a failed call counts as a miss, not as a lexical answer
        sample = lambda rows: stratified(rows, args.llm_sample // 14 or 1, args.seed)
        results["scorers"][f"LLM ({llm.settings.models['rollout']})"] = asyncio.run(
            evaluate_scorer(scorer, sample(train), sample(test)))
    for name in filter(None, args.encoders.split(",")):
        results["scorers"][f"{name} (nearest centroid)"] = evaluate_encoder(name, train, test)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.out / "report.md").write_text(report(results), encoding="utf-8")
    print(report(results))


if __name__ == "__main__":
    main()
