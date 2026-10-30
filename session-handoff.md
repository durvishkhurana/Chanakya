# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Tracks A and B and Phase 4 (except the I3 backup video) are on `main`. Phase 5: N1 (Gurnoor) is merged and working, waiting only for the hand-written test set; N2 and N3 (Durvish) not started; N4 (Gurnoor) after them. Phase 6 (Durvish: the #19 review fixes, win-back missions, the permission-first opening) is merged; see the Phase 6 section below
- Branch / commit: N1 merged from `feat/N1-worry-scorer`

## Completed This Session

- [x] N0 baselines and labelled lines (#24); revised N1 spec after Durvish's review (#25); `WORRY_SCORER` setting (#26)
- [x] Phase 5 split, one owner per network (#28); N0-N4 entries restored after #23 dropped them (#29)
- [x] On `feat/N1-worry-scorer`: ONNX encoder, 13-sigmoid worry head with calibration, `EmbeddingScorer` and `select_scorer`, training script, hand-written set file, guide and checker, tests
- [x] Harness files updated to the final Phase 5 plan: `docs/TASKS.md`, `feature_list.json`, `progress.md`, this file, README, a Phase 5 section in `CLAUDE.md`

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Everything on main | `SKIP_INSTALL=1 ./init.sh` | passed | 292 pytest after #26 |
| Neural tests (N1 branch) | `python -m pytest chanakya/neural` | 10 passed | fake encoder, no network |
| ONNX vs PyTorch encoder | encoder comparison on four lines | cosine 1.0 | 2.4 ms per line |
| Worry head | `python -m chanakya.neural.train_worry --seed 7` | embedding 0.648, lexical 0.388 | three families plus Concern Bank and template lines; 668 held-out test lines; calibration error 0.0052 |
| Full calls, held-out lines | `python -m chanakya.eval.harness --merchants 100 --seed 7/13 --variants chanakya,chanakya_embedding --voice test` | success 0.84/0.77 vs 0.62/0.62 | walk-away 0.12/0.22 vs 0.34/0.36; belief top-1 0.50/0.53 vs 0.26/0.29; template voice 0.91/0.96 vs 0.96/0.98 |
| Encoder fine-tuning probe | scratch experiment, 10 epochs | validation 0.72, test 0.55 | learns the training model's style; not adopted |

## Files Changed

- Phase 5 docs: `docs/TASKS.md`, `feature_list.json`, `progress.md`, `session-handoff.md`, `README.md`, `CLAUDE.md`
- N1 branch: `chanakya/neural/` (encoder, head, scorer, train_worry, human_set and tests), `data/neural/`, `requirements*.txt`

## Decisions Made

- One owner per neural network; settings `WORRY_SCORER`, `PLANNER_MEMORY`, `PLANNER_VALUE` with defaults that keep today's behaviour
- The encoder runs on ONNX Runtime; numpy is a base requirement; encoder weights are never committed
- `WORRY_SCORER` unset keeps today's choice (LLM scorer on live calls when an LLM is configured), so the new default never downgrades live calls
- The hand-written test set is Gurnoor's to write, by hand, and is never used for training, tuning or calibration

## Blockers / Risks

- N1 (0.648) is still below the LLM scorer (0.777), which is too slow for live turns; fine-tuning the encoder added under 2 points
- The hand-written test set is empty, and N1 cannot be marked done without it
- Closing the laptop lid pauses long runs

## Phase 6 (Durvish): merged

- Tasks D1, F1, W0, W1, W2 and P1, each on its own branch (`docs/winback-permission-specs`, `fix/I1-review-fixes`, `core/winback-contracts`, `feat/W1-winback-missions`, `feat/W2-winback-brain`, `feat/P1-permission-first`), stacked and merged through their PRs
- F1: one brain per mission while a scenario runs; a link yes covers only the link and the fixed-text `send_onboarding_reminder`; the callback scenario never moves the shared clock; turns are locked and shielded; every decline is recorded and closes the mission; the link carries the recommended product; a typed `Move.end_reason`
- W0: win-back and permission-first contracts in `chanakya/core` and the brain contracts; `WINBACK_ENABLED` and `PERMISSION_FIRST_ENABLED`, both off
- W1: churn detection (`chanakya/missions/churn.py`), a 20% seeded holdout, DONE only on system confirmation, Mission Control holdout and reasons-for-leaving cards. B12 should reuse `leaving_reasons()`
- W2: listen first, act only on a clear reason, never an offer; measured offline in `docs/results/winback/` (held-out reason accuracy 0.94 / 0.88, fix rate 0.90 / 0.83 on seeds 7 / 13, with the caveats listed there)
- P1: lead-list calls ask for two minutes before anything else; safety suite 15 scenarios, 0 violations
- Verification before the merge: `SKIP_INSTALL=1 FULL=1 ./init.sh` passed on the top branch (pytest 397 before N1 landed; re-run after merging #31, see below)
- Reviews owed: merged at the owner's request without Gurnoor's review. He should still review F1, W0 and W1 (Track B directories and shared contracts). W2 added a three-line read branch to `agent/brain_agent.py`; N1's wiring there should keep it
- Open risks: the win-back evidence rule was tuned after reading evaluation seed 7 traces; live calls do not pass answer pauses into the brain, so the long-pause "haan" rule only works where a pause is known; win-back is measured offline only; `scripts/demo/e2e_track_b.py` was updated but not re-run live

## Next Session Startup

1. Read `CLAUDE.md`, including the Phase 5 rules in section 7.
2. Read `feature_list.json`, `progress.md` and Phase 5 in `docs/TASKS.md`.
3. Review this handoff.
4. Run `./init.sh`; for neural work, `pip install -r requirements-neural.txt` and `python -m chanakya.neural.encoder --download`.

## Recommended Next Step

- N1: Gurnoor writes the hand-written test set by hand, then `python -m chanakya.neural.train_worry --seed 7` adds its per-slice results; mark N1 done with that evidence
- Durvish: N3 value network (needs nothing), then N2 semantic memory, which can use `LinesVoice` with the train split (`chanakya/sim/voice.py`) to build memory and `--voice test` to evaluate; re-measure win-back with the embedding scorer (`python -m chanakya.eval.winback`)
