# Win-back calls: measured results (task W2)

Offline only: template twin voices, Chanakya's lexical belief tracker, the look-ahead planner (its win-back rules are forced, never searched) and the template realizer. Mock systems, fictional former-customer personas, no network. Measured on 2026-10-30.

## Commands

```bash
python -m chanakya.eval.winback --seed 7  --repeats 5 --out docs/results/winback/evaluation-seed7
python -m chanakya.eval.winback --seed 13 --repeats 5 --out docs/results/winback/evaluation-seed13
python -m chanakya.eval.winback --seed 7  --repeats 5 --split planning --out docs/results/winback/planning-seed7
python -m chanakya.eval.winback --seed 13 --repeats 5 --split planning --out docs/results/winback/planning-seed13
python -m chanakya.eval.safety --mode offline --out docs/results/winback/safety-offline
```

Each folder has `report.md` and `results.json` (every call, with its moves, executed tools and outcome).

## Headline numbers

| Split, seed | Calls | Reason accuracy | Fix rate (fixable reasons) | Pitches when the hidden reason is "not needed" | Writes when "not needed" | Pitches or writes when Chanakya identified "not needed" | Safety violations |
|---|---|---|---|---|---|---|---|
| evaluation, 7 | 50 | 0.94 (47/50) | 0.90 (27/30) | 1 (15 calls) | 0 | 0 (14 calls) | 0 |
| evaluation, 13 | 50 | 0.88 (44/50) | 0.83 (25/30) | 2 (15 calls) | 0 | 0 (15 calls) | 0 |
| planning, 7 | 40 | 0.90 (36/40) | 0.76 (19/25) | 2 (10 calls) | 0 | 0 (9 calls) | 0 |
| planning, 13 | 40 | 0.93 (37/40) | 0.68 (17/25) | 2 (10 calls) | 0 | 0 (10 calls) | 0 |

The safety suite (`safety-offline/report.md`): 12 scenarios, 0 violations.

What the columns mean:
- **Reason accuracy:** the reason Chanakya acted on (or, if it never acted, its final top belief) is the twin's hidden reason, which is the persona's first hidden concern.
- **Fixable reasons** are `device_issue` and `settlement_delay` (a ticket), `rental_cost`, `hidden_charges`, `per_swipe_charges` and `setup_hassle` (an answer from the sourced pages, then a sales visit), and `just_busy` (a callback). **Fixed** means the right tool ran with the merchant's explicit consent (for a settlement, the settlement read and then the ticket), or the busy merchant accepted a callback.
- **Pitches** are `RECOMMEND`, `RESOLVE_CONCERN` or `CONFIRM_CONSENT` moves.

## Where it does badly

- **No zero for "not needed" by hidden reason.** When Chanakya identifies "not needed" it never pitches and never writes, because the move preconditions forbid it (0 in every run). But in 1 to 2 calls per run, the twin's hidden reason was "not needed" or "customers pay cash" and Chanakya acted on another worry the twin also voiced, usually trust in the caller. It then answered that worry once (counted as a pitch) and ended politely. It made no consent request and no write in those calls.
- **Two-worry twins confuse the reason.** Most reason misses are personas with a second hidden worry (for example `eval_former_02`, device issue plus trust in caller; `eval_former_08`, cash plus trust) who voice the second one first.
- **The fix rate on the planning split is lower (0.68 to 0.76)** because two planning twins hold a second worry (hidden charges) that lowers their chance of saying yes to the ticket, even with the right reason (device issue fixed 2/5 and 3/5, settlement 1/5 and 2/5 on planning).
- **Competitor QR is never "fixed" by design:** Chanakya answers once and accepts the merchant's choice.
- **The belief tracker swings on filler words.** On "Haan ji, boliye?" alone the lexical scorer raises `device_issue` from 0.27 to 0.71, and a single "hmm, sochna padega" can wipe out a reason the merchant gave a turn earlier. The win-back rules therefore ask why first, count only a real answer (not "achha" or "hmm") as evidence, keep that evidence on the next move, and drop worries the merchant denied after a probe. The scorer itself is in `chanakya/brain/belief.py`, which the neural worry scorer (N1) replaces, so it was not changed here.
- **These are not clean held-out numbers.** The evidence rule above was written after reading traces of evaluation seed 7 (first run: reason accuracy 0.84 on seed 7 and 0.74 on seed 13, fix rate 0.77 and 0.60). The planning-split rows are reported for that reason. A fresh set of former-customer personas, or the LLM twins online, would be the honest next check.
- **Offline only.** The twins speak Concern Bank phrasings, which the lexical scorer matches well. No online run was made (Groq free-tier limits, see `docs/results/README.md`).

## With the trained worry scorer (`WORRY_SCORER=embedding`)

Measured on 2026-10-31 (Windows 11, CPU), same harness and personas, only the belief tracker's scorer changed:

```bash
WORRY_SCORER=embedding python -m chanakya.eval.winback --seed 7  --repeats 5 --out docs/results/winback/embedding-evaluation-seed7
WORRY_SCORER=embedding python -m chanakya.eval.winback --seed 13 --repeats 5 --out docs/results/winback/embedding-evaluation-seed13
```

| Evaluation split, seed | Scorer | Reason accuracy | Fix rate (fixable reasons) | Pitches when the hidden reason is "not needed" | Writes when "not needed" | Safety violations |
|---|---|---|---|---|---|---|
| 7 | lexical (above) | 0.94 (47/50) | 0.90 (27/30) | 1 (15 calls) | 0 | 0 |
| 7 | embedding | 0.90 (45/50) | 0.93 (28/30) | 4 (15 calls) | 0 | 0 |
| 13 | lexical (above) | 0.88 (44/50) | 0.83 (25/30) | 2 (15 calls) | 0 | 0 |
| 13 | embedding | 0.84 (42/50) | 0.83 (25/30) | 1 (15 calls) | 0 | 0 |

**No gain on win-back.** Reason accuracy drops by 4 points on both seeds; the fix rate is one call better on seed 7
and equal on seed 13. Most new misses are "not needed" merchants read as `device_issue` (4 of 10 on seed 7). These twins
speak Concern Bank phrasings, which the lexical scorer is built from, so this is the setting where it is strongest; the
held-out-lines comparison that favours the embedding scorer is in `docs/results/neural-worry-scorer/`.

The demo scenario `winback_device_fix` also fails with `WORRY_SCORER=embedding`: on "Soundbox theek se kaam nahi karta
tha, baar baar band ho jaata tha, isliye wapas kar diya" the head scores rental cost 0.35 and device issue 0.34 (the
lexical scorer: device issue 0.49), so the belief never reaches the 0.5 a win-back fix needs, and Chanakya probes rent
instead. It passes with the default scorer. The win-back rules were not changed to make it pass, and the head was not
retrained on this line.
