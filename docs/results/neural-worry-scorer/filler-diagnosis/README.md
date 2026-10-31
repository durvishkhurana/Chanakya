# Why N4's win-back demo fails with the embedding scorer

Measured on 2026-10-31 (macOS, CPU). Nothing here is merged into the code: every fix below was tried and reverted.
The patches are kept next to this file so each run can be repeated.

## The cause: filler lines move the belief

`winback_device_fix` fails with `WORRY_SCORER=embedding`. The head is only half of it. The belief tracker turns each
calibrated score into an odds ratio against the worry's training base rate (`BayesianBeliefTracker.likelihood` in
`chanakya/brain/belief.py`). A line that voices no worry, such as "Achha.", scores every worry below its base rate, some
less far below than others. With the current head, "Achha." gives `setup_hassle` 0.05 (base rate 0.071, ratio about
0.7) and `device_issue` about 0.005 (base rate 0.075, ratio about 0.06). Each "Achha." therefore multiplies setup
hassle by roughly 11 against device issue. The trace of the demo call:

| Merchant says | Top of the belief afterwards |
|---|---|
| "Soundbox theek se kaam nahi karta tha, baar baar band ho jaata tha, isliye wapas kar diya." | device issue 0.39, setup hassle 0.33 |
| Chanakya probes the device; merchant: "Achha." | **setup hassle 0.76**, device issue 0.11 |
| "Achha." | setup hassle 0.91 |

Chanakya then answers setup hassle and offers a visit instead of raising a ticket. `winback_not_needed` passes today
for the same reason in reverse: the "Achha." before the merchant's answer pushes `not_needed` to 0.45. The head reads
"mujhe iski zaroorat hi nahi thi" as setup hassle or device issue, not as not needed.

## What was tried

All runs: `python -m chanakya.eval.harness --mode offline --merchants 100 --seed <7|13> --variants chanakya,chanakya_embedding --voice <test|template>`
and `WORRY_SCORER=embedding python -m chanakya.eval.winback --seed <7|13> --repeats 5`. The demo check is
`WINBACK_ENABLED=1 WORRY_SCORER=embedding PLANNER_MEMORY=neural PLANNER_VALUE=network python scripts/demo/scenarios.py`.
Reports per run are in the folders here; "today" is `../full-calls/` and `../../winback/embedding-evaluation-seed*/`.

1. **Win-back lines for the head** (`winback-lines.diff`, folder `winback-head/`, together with the clamp below):
   2,170 extra train lines from the three train model families, written as former merchants saying why they left;
   lines close to a test line or a demo line were dropped. The head was retrained with `--seed 7`. Held-out per-line
   accuracy went from 0.648 to 0.653, but it did worse than the current head on almost every full-call measure.
   The lines and the head were not committed.
2. **Clamp** (`clamp.diff`, folder `clamp/`): a score below the base rate does not count against a worry,
   `max(1, ratio)`.
3. **Soft** (`soft.diff`, folder `soft/`): the ratio is raised to the power of the line's top score, so a line that
   voices no worry barely moves the belief.

Embedding variant, seed 7 / seed 13:

| Measure | Today | Clamp | Soft | Win-back head + clamp |
|---|---|---|---|---|
| Demo scenarios passed (all neural settings) | 5/6 | 5/6 | **6/6** | 4/6 |
| Success, held-out lines | **0.84 / 0.77** | 0.75 / 0.69 | 0.67 / 0.75 | 0.69 / 0.73 |
| Walk-away, held-out lines | **0.12 / 0.22** | 0.18 / 0.27 | 0.27 / 0.25 | 0.22 / 0.25 |
| Belief top-1, held-out lines | 0.50 / 0.53 | **0.73 / 0.69** | 0.64 / 0.70 | 0.70 / 0.74 |
| Success, template voice | **0.91 / 0.96** | 0.83 / 0.85 | 0.82 / 0.84 | 0.79 / 0.83 |
| Win-back reason accuracy | 0.90 / 0.84 | **0.96 / 0.92** | 0.94 / 0.94 | 0.86 / 0.80 |
| Win-back fix rate | 0.93 / 0.83 | 0.93 / 0.97 | 0.93 / 0.93 | 0.93 / 0.93 |
| Safety violations | 0 | 0 | 0 | 0 |

The lexical variant is unchanged in every run (0.62 / 0.62 held-out, 0.96 / 0.98 template).

## What it means

- **Stopping the filler swing makes the belief more accurate and the win-back better, but closes fewer sales calls**
  (8 to 17 points on held-out lines, 7 to 12 on the template voice). The soft version passes all six demo scenarios
  and still loses on sales, so none of these is merged.
- The likely reason, not yet tested: on a sales call the swing after a filler moves Chanakya on to another worry,
  which happens to help. If that is it, the planner should move on by design (a worry answered and met with "achha"
  counts as answered) and the tracker fix can then land without the loss.
- `winback_not_needed` also needs a head that reads "zaroorat nahi thi" as not needed; with the soft tracker it
  passes, with the clamp it does not.

N4 stays blocked. Next step: check, on the calls that flip from success to failure, whether Chanakya keeps answering
a worry it already answered.
