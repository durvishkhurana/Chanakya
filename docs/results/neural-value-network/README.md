# Value network for the planner (N3): results

Measured on 2026-10-31, Windows 11, Python 3.12, CPU only. Every number comes from a command on this page. All
merchants are simulated; no real calls. How the network was trained is in [training.md](training.md); the weights in
`data/neural/value_net.npz` were not retrained for these runs.

`PLANNER_VALUE=formula` (default) values the end of a simulated call as `0.8 x consent_chance`.
`PLANNER_VALUE=network` uses the value network instead. Everything else (belief tracker, realizer, safety rules) is the
same, and the forced safety rules decide before any leaf is valued.

## Full calls on held-out evaluation personas

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7  --variants chanakya,chanakya_value --out docs/results/neural-value-network/seed7
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --variants chanakya,chanakya_value --out docs/results/neural-value-network/seed13
```

100 held-out Twin-B merchants per run, plus 12 adversarial calls, template voice.

| Metric (seed 7 / seed 13) | Formula (`chanakya`) | Network (`chanakya_value`) |
|---|---|---|
| Mission success | **0.96 / 0.98** | 0.94 / 0.92 |
| Merchant walked away | **0.04 / 0.01** | 0.06 / 0.07 |
| Agent turns to close | **5.09 / 5.06** | 5.79 / 5.70 |
| Belief top-1 accuracy | 0.39 / 0.34 | 0.41 / 0.39 |
| Safety violations (incl. adversarial) | 0 / 0 | 0 / 0 |
| Turn latency p50 (ms) | 99.1 / 99.9 | 153.7 / 149.9 |
| Turn latency p90 (ms) | 116.2 / 115.7 | 181.0 / 176.8 |

Reports per run: `seed<seed>/report.md` (and `results.json`, `report.html`).

## Planner checks

```bash
python -m chanakya.eval.planner_checks lookahead                    # lookahead-formula.txt
python -m chanakya.eval.planner_checks lookahead --value network    # lookahead-network.txt
python -m chanakya.eval.planner_checks stability                    # stability-formula.txt
python -m chanakya.eval.planner_checks stability --value network    # stability-network.txt
```

**Look-ahead consent rate against Twin-A** (baseline rule-based planner 0.670 and 0.847):

| Personas | Formula | Network |
|---|---|---|
| Planning, 30 personas x seeds 0-9 (300 calls; the network trained on these personas) | 0.920 | **0.963** |
| Evaluation, 30 personas x seeds 0-4 (150 calls; never seen in training) | **0.953** | 0.927 |
| Planner time p50 / p90 (ms) | **113 / 118** | 181 / 203 |

**Seed stability** (the coach recording replayed with 42 mission ids):

| | Formula | Network |
|---|---|---|
| Whole call identical to the most common run | **21/42** | 5/42 |
| Turns where every run agrees | 3 of 5 | 1 of 5 |

With the network, the first suggestion splits between probing and resolving `competitor_qr` (24/42 vs 18/42), where
the formula resolves it 41/42 times.

## What this means

- **The network does not help on merchants it has not seen.** On held-out evaluation personas it closes 2 and 6
  fewer calls in 100 than the formula, has more walk-aways (0.06 and 0.07 vs 0.04 and 0.01), and takes 0.6 to 0.7 more
  turns to close.
- **It does help on the personas it was trained on** (0.963 vs 0.920 look-ahead consent), and the opposite on
  evaluation personas (0.927 vs 0.953). That pattern points to overfitting to the planning personas used for self-play:
  the low validation MSE in `training.md` (0.041 vs 0.278) was measured on four held-out planning personas, and it did
  not carry over to the evaluation split.
- **It is slower and less stable.** Each plan takes about 65 ms more (p50 113 to 181 ms), and the suggestion depends
  more on the seed (5/42 identical runs vs 21/42).
- **Safety is unchanged:** zero violations either way, including adversarial calls, because the forced safety rules
  run before any leaf value.
- **Decision:** `PLANNER_VALUE` stays `formula` by default. The network and its hook stay behind the setting for
  further work: self-play on more varied personas, or the optional second self-play round with the network-guided
  planner, both measured on the evaluation split before any change of default.
