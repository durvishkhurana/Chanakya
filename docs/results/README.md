# Measured results

Every number here comes from a run in this folder, with the command and seed that produced it. All runs
are simulations: no real merchant, call or payment is involved, and the business systems are labelled
mocks. Measured on 2026-10-29 on Windows, Python 3.12.13.

## 1. Agent variants on held-out Twin-B merchants (offline)

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7  --out docs/results/offline-seed7
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 13 --out docs/results/offline-seed13
```

Offline means template voices and the moves each variant declares; it is deterministic and makes no
network calls. Each run has 100 calls over the 30 held-out evaluation personas plus 12 adversarial calls
(4 adversarial personas x 3). The per-call outcomes are in `results.json` (transcripts omitted to keep the
files small; rerun the command to get them), and `report.html` has bar charts.

| Metric | Reactive | Actions only | Chanakya | Chanakya without belief |
|---|---|---|---|---|
| Mission success, seed 7 | 0.00 | 0.99 | 0.96 | 0.40 |
| Mission success, seed 13 | 0.00 | 1.00 | 0.98 | 0.46 |
| Walked away, seed 7 / 13 | 0.07 / 0.07 | 0.01 / 0.00 | 0.04 / 0.01 | 0.58 / 0.51 |
| Agent turns to close, seed 7 / 13 | n/a | 5.49 / 5.12 | 5.09 / 5.06 | 4.40 / 4.39 |
| Escalation recall (distressed merchant) | 0 | 0 | 1.0 | 1.0 |
| Wrong actions, safety violations | 0, 0 | 0, 0 | 0, 0 | 0, 0 |
| Chanakya turn latency p50 / p90 (template realizer) | | | 99-100 / 115 ms | |

What these runs support:

- Belief tracking is what makes Chanakya work in this simulator: without it, success falls from 0.96-0.98 to
  0.40-0.46 and about half the merchants walk away.
- The reactive baseline never asks for consent, so it never closes; it is the "stops at the conversation"
  failure described in docs/IDEA.md section 1.
- Only the Chanakya variants escalate the distressed merchant. No variant broke a safety rule.

What they do not support: **Chanakya does not beat the actions-only agent on success here** (0.96-0.98 vs
0.99-1.00, within noise on 100 calls). In this offline simulator, an agent that answers whatever worry it
hears and asks for consent every other turn is nearly as good. Do not claim otherwise from these runs.

## 2. Look-ahead planner against the baseline planner (Twin-A and held-out personas)

```bash
python -m chanakya.eval.planner_checks lookahead
```

Text-mode calls (the `converse()` helper in `chanakya/brain/tests/test_planner_rules.py`) against the
template twin, after the twin recalibration in section 4 and the seed-stability fix in section 2a:

| Personas, seeds | Baseline planner consent | NRPA look-ahead consent |
|---|---|---|
| 30 planning personas x seeds 0-9 (300 calls) | 0.670 | 0.920 |
| 30 evaluation personas x seeds 0-4 (150 calls) | 0.847 | 0.953 |

Planner time per searched move with a 300 ms budget: p50 111 ms, p90 120 ms, max 185 ms over 1,460 plans,
no fallbacks. Before the fix (6 sampled merchants) the same command gave 0.943 and 0.933 with p50 58 ms. The Strategy Forest prior did not change success in the harness
(0.97 with and without, `--variants chanakya,chanakya_forest`), so it is not claimed as an improvement.
Re-measured after the seed-stability fix, it still makes no difference:

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --variants chanakya,chanakya_forest
python -m chanakya.eval.planner_checks forest
```

Harness success 0.96 vs 0.96 (seed 7) and 0.98 vs 0.98 (seed 13); look-ahead consent 0.920 vs 0.917 (300
planning calls) and 0.953 vs 0.953 (150 held-out calls). The forest's mined moves are mostly ones the planner
already considers, and both settings are close to their ceiling, so there is little left for a prior to add.

### 2a. Seed stability (A6)

```bash
python -m chanakya.eval.planner_checks stability
```

Coach mode replays a recorded call, and the planner seeds from the mission id, so the same call should get
the same suggestions whatever the id. Before the fix only 13 of 42 ids gave the same whole run: after
"Aur iska kiraya kitna hai? Baad mein koi extra charge toh nahi katega?" 16 suggested answering hidden
charges, 12 asking for consent and 12 answering "just busy". Two causes: the word "baad mein" counted as a
busy merchant, tying three worries, and the planner judged moves against only 6 merchants drawn
independently from that belief. Now "later" alone is not a busy cue, the sampled merchants are stratified,
and 12 are sampled. Result over 42 ids:

| Merchant turn | Suggestions |
|---|---|
| 1 "Haan boliye, par jaldi bataiye." | answer competitor QR 41, language comfort 1 |
| 2 "Mere paas pehle se dusra QR..." | answer competitor QR 42 |
| 3 "Aur iska kiraya kitna hai? Baad mein koi extra charge..." | answer rent 22, answer hidden charges 20 |
| 4 "Hmm... dekhiye... abhi sochna padega." | answer rent 42 |
| 5 "Haan, theek hai, aap official link bhej dijiye." | ask for explicit consent 42 |

The merchant asked two questions at turn 3, and every id now answers one of them; 21 of 42 whole runs are
identical (13 before). The cost is planner time (p50 58 ms to 111 ms) and turn latency in the harness.

## 3. Safety suite

```bash
python -m chanakya.eval.safety --mode offline --out docs/results/safety-offline
python -m chanakya.eval.safety --mode online    # Groq, openai/gpt-oss-120b realizer; copied to safety-online/
```

12 scenarios (prompt injection, OTP phishing, pressure, invented-price bait, ambiguous "haan" consent,
distress, decline). **Zero violations offline (34 turns) and online with the live LLM realizer (37 turns).**

## 4. Twin calibration

```bash
python -m chanakya.sim.calibration > docs/results/twin-calibration.txt
```

An untreated agent (pitches and asks without addressing any worry) loses 67.3% of planning merchants over
seeds 0-4 (66.2% over seeds 0-19 planning, 63.7% evaluation), inside the 50-70% target. The twin was
recalibrated during this work: the first version voiced its worries too often and let merchants say yes
with worries unanswered, which let the actions-only agent reach 0.98 against Chanakya's 0.91-0.92. The
current twin holds worries back (arXiv 2605.22240), multiplies the chance of a yes by 0.35 per open worry,
and treats re-asking after a no as pressure.

## 5. Planning while listening

```bash
python -m chanakya.brain.speculative --turns 40 --seed 3 > docs/results/latency-planning-while-listening.json
```

With fixed fake model delays (scorer 0.25 s, realizer 0.8 s), the partial transcript 0.6 s before the final,
and 25% of finals changed: turn latency p50 1065 ms after speech vs 457 ms while listening; p90 unchanged
(about 1070 ms) because changed finals are recomputed. A live run on Groq's free tier was dominated by
rate-limit waits (8-15 s per turn), so planning while listening stays off by default.

## Not measured

- A full online evaluation: Groq's free tier allows 8,000 tokens per minute on the main model, and a small
  online smoke run had 28 rate-limited turns for the reactive agent. Its numbers are not comparable.
- Speed to lead and cost per completed mission in currency: the text harness has no scheduler clock or
  billing data.
- Real merchants: twins are simulations.
