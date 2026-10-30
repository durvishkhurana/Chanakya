# Planner variants with the trained worry scorer

Measured on 2026-10-31, Windows 11, Python 3.12, CPU only. All merchants are simulated; no real calls.

N2 and N3 were first measured with the default lexical scorer, whose belief finds the merchant's real worry only about
a quarter of the time with held-out wording. This run asks whether the memories or the value network help once the
belief is better, with `WORRY_SCORER=embedding` (N1) for every variant:

```bash
WORRY_SCORER=embedding python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7  --voice test --variants chanakya,chanakya_forest,chanakya_memory,chanakya_value --out docs/results/neural-combined/seed7
WORRY_SCORER=embedding python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --voice test --variants chanakya,chanakya_forest,chanakya_memory,chanakya_value --out docs/results/neural-combined/seed13
```

100 held-out Twin-B merchants per run plus 12 adversarial calls; the twin voices each worry as a held-out test-split line.

| Metric (seed 7 / seed 13) | No memory (`chanakya`) | Trigram forest (A9) | Neural memory (N2) | Value network (N3) |
|---|---|---|---|---|
| Mission success | 0.84 / 0.77 | 0.84 / 0.79 | 0.83 / 0.80 | 0.74 / 0.81 |
| Merchant walked away | 0.12 / 0.22 | 0.11 / 0.21 | 0.11 / 0.18 | 0.17 / 0.13 |
| Belief top-1 accuracy | 0.50 / 0.53 | 0.51 / 0.52 | 0.54 / 0.52 | 0.49 / 0.55 |
| Agent turns to close | 5.20 / 4.94 | 5.30 / 4.96 | 5.23 / 4.92 | 5.69 / 5.32 |
| Safety violations (incl. adversarial) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Turn latency p50 (ms) | 120.9 / 121.5 | 119.3 / 121.1 | 144.1 / 144.9 | 173.8 / 180.8 |

## What this means

- **No consistent gain from any of the three.** The two seeds disagree: the value network is 10 calls worse on seed 7
  and 4 better on seed 13; neural memory is 1 worse and 3 better; the forest is equal and 2 better. With 100 merchants
  per run, differences of a few calls are within run-to-run noise, and a part that helps should help on both seeds.
- **The worry scorer is still the part that matters:** with it, every variant is at 0.74 to 0.84, against 0.61 to 0.63
  with the lexical scorer on the same seeds and voice (`docs/results/neural-memory/`).
- **Costs are as before:** about 23 ms per turn for neural memory and about 55 ms for the value network.
- **Decision:** the defaults stay (`PLANNER_MEMORY=forest`, `PLANNER_VALUE=formula`). A9's open question (does the
  forest beat the planner's own candidates?) gets the same answer with a better belief: not measurably.

Reports per run: `seed<seed>/report.md` (and `results.json`, `report.html`).
