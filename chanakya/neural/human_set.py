"""The hand-written worry test set (task N1): load it and check it before anyone scores against it.

`data/neural/worry_lines_human.csv` is written by people, never by an LLM, and is never used for training,
tuning or calibration. How to write lines: `data/neural/README.md`.

    python -m chanakya.neural.human_set          # check the file and print counts per slice and author
"""

import csv
import sys
from collections import Counter
from pathlib import Path

from chanakya.brain.concern_bank import DATA, default_bank

PATH = DATA / "neural" / "worry_lines_human.csv"
COLUMNS = ["text", "concerns", "language", "slice", "author"]
LANGUAGES = {"hindi", "hinglish", "punjabi", "english"}
SLICES = {"hinglish_roman", "negation", "no_worry", "punjabi", "other"}
NONE = "none"


def load(path: Path = PATH) -> list[dict]:
    """Rows with ``concerns`` split into a list (empty for ``none``)."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["concerns"] = [] if row["concerns"].strip() == NONE else [c.strip() for c in row["concerns"].split(";")]
    return rows


def problems(path: Path = PATH) -> list[str]:
    """Everything wrong with the file; empty when it is ready to score against."""
    with path.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle), [])
    if header != COLUMNS:
        return [f"header must be {','.join(COLUMNS)}"]
    found, seen, ids = [], set(), set(default_bank().ids)
    for number, row in enumerate(load(path), start=2):
        where = f"line {number}"
        text = (row["text"] or "").strip()
        if not text:
            found.append(f"{where}: empty text")
        key = " ".join(text.lower().split())
        if key in seen:
            found.append(f"{where}: duplicate text")
        seen.add(key)
        found += [f"{where}: unknown concern {c!r}" for c in row["concerns"] if c not in ids]
        if row["language"] not in LANGUAGES:
            found.append(f"{where}: language must be one of {', '.join(sorted(LANGUAGES))}")
        if row["slice"] not in SLICES:
            found.append(f"{where}: slice must be one of {', '.join(sorted(SLICES))}")
        if row["slice"] == "no_worry" and row["concerns"]:
            found.append(f"{where}: a no_worry line must have concerns none")
        if row["slice"] == "punjabi" and row["language"] != "punjabi":
            found.append(f"{where}: the punjabi slice needs language punjabi")
        if not (row["author"] or "").strip():
            found.append(f"{where}: author is required")
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(problem)
    rows = load()
    print(f"{len(rows)} lines; by slice {dict(Counter(r['slice'] for r in rows))}; "
          f"by author {dict(Counter(r['author'] for r in rows))}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
