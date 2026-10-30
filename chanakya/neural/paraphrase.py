"""Labelled merchant lines for training and testing a worry scorer (task N0).

Template twins speak the Concern Bank's own sentences, so they cannot test a scorer fairly: the lexical
scorer is built from those sentences, and a trained model would only memorise about a hundred lines.
These lines are fresh paraphrases from two model families, kept apart like Twin-A and Twin-B: the train
split comes from the ``twin_a`` model and the test split from ``twin_b``. Lines too close to a Concern Bank
phrasing, or to a line in the other split, are dropped.

    python -m chanakya.neural.paraphrase --seed 7      # writes data/neural/worry_lines.jsonl
    python -m chanakya.neural.paraphrase --seed 11 --extend-train mistralai/mistral-small-2603 --extend-train z-ai/glm-5.3-flash

``--extend-train`` adds train lines written by other model families (never the test family) and leaves the test
split untouched; new lines close to any test line are dropped.
"""

import argparse
import asyncio
import json
import random
import re
from pathlib import Path

from chanakya.brain.belief import dice, trigrams
from chanakya.brain.concern_bank import DATA, ConcernBank, default_bank
from chanakya.brain.contracts.llm import LLMError, complete_json

OUT = DATA / "neural" / "worry_lines.jsonl"
NONE = "none"  # a line that shows no worry: greetings, okays, yeses, questions about something else
LANGUAGES = {
    "hindi": "Hindi in Devanagari script",
    "hinglish": "Hinglish (Hindi and English mixed) in Latin script",
    "punjabi": "Punjabi in Gurmukhi script",
    "english": "Indian English",
}
SPLITS = {"train": ("twin_a", 24), "test": ("twin_b", 8)}  # role that writes the split, lines per concern and language
BUSINESSES = ["kirana store", "chemist", "tea stall", "mobile repair shop", "sweet shop", "garment shop", "dhaba"]
TONES = ["blunt", "polite", "indirect and hesitant", "rambling", "suspicious", "in a hurry"]
TOO_CLOSE = 0.85
NONE_BRIEF = ("says something on a sales call that shows no worry at all: a greeting, an okay, a yes to continue, "
              "asking who is calling, or small talk about the shop")


def prompt(brief: str, language: str, count: int, rng: random.Random) -> str:
    """One request for ``count`` varied merchant lines."""
    shops = ", ".join(rng.sample(BUSINESSES, 3))
    tones = ", ".join(rng.sample(TONES, 3))
    return (
        f"Write {count} different things an Indian small-shop owner ({shops}) might say on a phone call from a "
        f"payments company, when the merchant {brief}.\n"
        f"Language: {LANGUAGES[language]}. Mix tones ({tones}). One short spoken sentence each, as people really "
        "talk on the phone. Vary the wording a lot; do not repeat a sentence pattern. No prices, no numbers, "
        'no brand names, no em dashes.\nReturn JSON {"lines": ["...", "..."]}.'
    )


async def ask(llm, role: str, text: str, seed: int) -> list[str]:
    """The lines one request returns, or none if the model fails twice."""
    for attempt in range(2):
        try:
            reply = await complete_json(llm, role, [{"role": "user", "content": text}], max_tokens=1500,
                                        temperature=0.9, seed=seed + attempt)
            lines = [re.sub(r"\s*[\u2014\u2013]\s*", ", ", line).strip() for line in reply.get("lines", [])
                     if isinstance(line, str)]  # no em or en dashes in merchant lines, whatever the model writes
            return [line for line in lines if line]
        except LLMError:
            continue
    return []


def clean(rows: list[dict], bank: ConcernBank) -> list[dict]:
    """Drop duplicates, lines close to a Concern Bank phrasing, and test lines close to any train line."""
    reference = [trigrams(p) for cid in bank.ids for p in bank.phrasings(cid)]
    kept, seen = [], set()
    train = [trigrams(r["text"]) for r in rows if r["split"] == "train"]
    for row in rows:
        key = " ".join(row["text"].lower().split())
        grams = trigrams(row["text"])
        if key in seen or any(dice(grams, p) >= TOO_CLOSE for p in reference):
            continue
        if row["split"] == "test" and any(dice(grams, t) >= TOO_CLOSE for t in train):
            continue
        seen.add(key)
        kept.append(row)
    return kept


def extend(existing: list[dict], new: list[dict], bank: ConcernBank) -> list[dict]:
    """``existing`` plus the new train lines that repeat nothing and stay clear of the bank and of every test line."""
    reference = [trigrams(p) for cid in bank.ids for p in bank.phrasings(cid)]
    reference += [trigrams(r["text"]) for r in existing if r["split"] == "test"]
    seen = {" ".join(r["text"].lower().split()) for r in existing}
    kept = []
    for row in new:
        key = " ".join(row["text"].lower().split())
        if row["split"] != "train" or key in seen or any(dice(trigrams(row["text"]), p) >= TOO_CLOSE for p in reference):
            continue
        seen.add(key)
        kept.append(row)
    return existing + kept


async def generate(llm, seed: int, bank: ConcernBank | None = None, parallel: int = 4,
                   splits: dict | None = None) -> list[dict]:
    """Every (split, concern or none, language) batch, generated with a bounded number of requests at once."""
    bank = bank or default_bank()
    rng = random.Random(seed)
    jobs = []
    for split, (role, count) in (splits or SPLITS).items():
        for label in [*bank.ids, NONE]:
            brief = NONE_BRIEF if label == NONE else f"is worried that: {bank.concerns[label].description}"
            for language in LANGUAGES:
                jobs.append((split, role, label, language, prompt(brief, language, count + 4, rng), rng.randrange(10**6)))
    gate = asyncio.Semaphore(parallel)

    async def run(split, role, label, language, text, job_seed):
        async with gate:
            lines = await ask(llm, role, text, job_seed)
        return [{"text": line, "concern": label, "language": language, "split": split,
                 "model": llm.settings.models[role], "seed": seed} for line in lines]

    batches = await asyncio.gather(*(run(*job) for job in jobs))
    return clean([row for batch in batches for row in batch], bank)


def load(split: str | None = None, path: Path = OUT) -> list[dict]:
    """The labelled lines, optionally one split."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def main() -> None:
    from dotenv import load_dotenv

    from chanakya.brain.contracts.llm import default_llm

    parser = argparse.ArgumentParser(description="Generate labelled merchant lines for the worry scorer.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--extend-train", action="append", default=[], metavar="MODEL",
                        help="Add train lines from this model to the existing file; repeatable")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    if args.extend_train:
        import dataclasses

        from chanakya.core.config import Settings

        bank, rows, base = default_bank(), load(path=args.out), Settings.from_env()
        for number, model in enumerate(args.extend_train):
            llm = default_llm(dataclasses.replace(base, models={**base.models, "twin_a": model}))
            new = asyncio.run(generate(llm, args.seed + number, bank, splits={"train": SPLITS["train"]}))
            before = len(rows)
            rows = extend(rows, new, bank)
            print(f"{model}: {len(new)} generated, {len(rows) - before} kept")
    else:
        rows = asyncio.run(generate(default_llm(), args.seed))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    counts = {s: sum(r["split"] == s for r in rows) for s in SPLITS}
    print(f"{len(rows)} lines -> {args.out} {counts}")


if __name__ == "__main__":
    main()
