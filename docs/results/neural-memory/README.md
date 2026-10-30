# Semantic memory (N2): results

Measured on 2026-10-31, Windows 11, Python 3.12, CPU only. Every number comes from a command on this page. All
merchants are simulated; no real calls.

`PLANNER_MEMORY` picks what the look-ahead planner consults through its `moves_for(state)` hook for which moves to try
first: `forest` is the Strategy Forest (trigram vectors, 24 fixed clusters); `neural` looks up the k nearest remembered
moments, each the e5 embedding of the merchant's line plus the belief vector, with the same Wilson-scored move values.

## Building the memory

```bash
pip install -r requirements-neural.txt
python -m chanakya.neural.encoder --download
python -m chanakya.brain.memory.build --seed 11      # writes data/neural/memory.npz (1.0 MB) and build.md
```

- **Conversations:** 540 (look-ahead planner, baseline and exploring baseline on planning personas), voiced with N0's
  train-split lines, so no test-split line is in the memory; 181 ended in a yes.
- **Moments remembered:** 3,245; seed 11; data hash `993cccc77d24e361` ([build.md](build.md)).
- **Lookup** on 200 test-split lines, embedding included: **p50 7.79 ms, p90 9.15 ms.**

## Win rate with held-out lines

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7  --voice test --variants chanakya,chanakya_forest,chanakya_memory --out docs/results/neural-memory/seed7
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --voice test --variants chanakya,chanakya_forest,chanakya_memory --out docs/results/neural-memory/seed13
```

100 held-out Twin-B merchants per run, plus 12 adversarial calls. The twin voices each worry as a held-out test-split
line. All three variants use today's default lexical worry scorer; only the planner's memory differs.

| Metric (seed 7 / seed 13) | No memory (`chanakya`) | Trigram forest (`chanakya_forest`) | Neural memory (`chanakya_memory`) |
|---|---|---|---|
| Mission success | 0.62 / 0.62 | 0.62 / 0.61 | 0.63 / 0.61 |
| Merchant walked away | 0.34 / 0.36 | 0.35 / 0.38 | 0.33 / 0.37 |
| Belief top-1 accuracy | 0.26 / 0.29 | 0.27 / 0.30 | 0.28 / 0.29 |
| Agent turns to close | 5.06 / 4.95 | 5.00 / 4.97 | 5.13 / 5.00 |
| Safety violations (incl. adversarial) | 0 / 0 | 0 / 0 | 0 / 0 |
| Turn latency p50 (ms) | 111.2 / 104.6 | 106.3 / 105.3 | 129.2 / 128.0 |
| Turn latency p90 (ms) | 128.9 / 118.8 | 122.8 / 122.9 | 150.0 / 147.2 |

Reports per run: `seed<seed>/report.md` (and `results.json`, `report.html`).

## What this means

- **Neural memory gives no measurable gain.** Success is 0.63 and 0.61 against 0.62 and 0.62 with no memory: one call
  in 100 either way, within run-to-run noise. The trigram forest is the same (0.62 and 0.61), as it was in A9.
- **The memory is not what limits these calls.** With held-out wording, the lexical belief finds the merchant's real
  worry only 26 to 30% of the time, whatever the memory. A memory that suggests moves for the believed state cannot
  fix a wrong belief; N1's embedding scorer, which lifts success to 0.84 and 0.77 with the same seeds and voice
  ([neural-worry-scorer](../neural-worry-scorer/README.md)), is the part that moves this number.
- **It costs about 20 ms per turn** (p50 104-111 ms to 128-129 ms); the lookup alone, encoding included, is 7.8 ms p50.
- **Safety is unchanged:** zero violations, including adversarial calls.
- **Decision:** `PLANNER_MEMORY` stays `forest` by default. Not measured here: neural memory together with
  `WORRY_SCORER=embedding`, where the belief it is keyed on is right about twice as often.
