# Session Handoff

## Current Objective

- Goal: Phase 6 (Durvish): the review fixes from PR #19, win-back missions, and the permission-first opening for lead-list calls
- Current status: all six tasks (D1, F1, W0, W1, W2, P1) are coded, tested and committed locally, one branch per task, stacked in merge order, each with its own PR. `main` (up to #29) was merged into the top branch, and its PR brought the whole stack into `main`.
- Branches, each cut from the one before it (the first from `main` at `8de04f8`), in PR order:
  1. `docs/winback-permission-specs` (D1): specs in `docs/TASKS.md` and `feature_list.json`
  2. `fix/I1-review-fixes` (F1): the eight review points on #19
  3. `core/winback-contracts` (W0): `core:` contracts and both flags
  4. `feat/W1-winback-missions` (W1): churn detection, holdout, the win-back DONE check, Mission Control cards
  5. `feat/W2-winback-brain` (W2): the win-back conversation, twins, scenarios, measured results
  6. `feat/P1-permission-first` (P1): ask for two minutes before any pitch on lead-list calls

## Reviews still owed

- Merged at the owner's request without Gurnoor's review. He should still review, after the fact: F1 (verifier, mock tools, Live Call View, e2e script), W0 (the `core:` contracts, intake, mock DB, gate, dashboard labels) and W1 (seed, churn detector, verifier, missions API, Mission Control).
- W2 added a three-line read branch to `agent/brain_agent.py`; N1's wiring there should keep it.

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Clean main | `./init.sh` on `3350e09` | passed | agent 104, backend 98, pytest 291, Ruff, frontend 22 |
| Everything, last branch | `SKIP_INSTALL=1 FULL=1 ./init.sh` on `feat/P1-permission-first` after the rebase onto `8de04f8` | passed | agent 104, backend 98, pytest 397, Ruff clean, frontend 24, lint, build |
| Each branch after the rebase | `python -m pytest`, `ruff check .` | passed | D1 292, F1 308, W0 320, W1 335, W2 371 |
| Demo scenarios | `python scripts/demo/scenarios.py` | 6/6 passed | includes `winback_device_fix` and `winback_not_needed` |
| Win-back evaluation | `python -m chanakya.eval.winback --seed 7/13 --repeats 5` (both splits) | see `docs/results/winback/README.md` | evaluation reason accuracy 0.94 / 0.88, fix rate 0.90 / 0.83 |
| Safety suite | `python -m chanakya.eval.safety --mode offline` | 15 scenarios, 0 violations | three new permission-first cases |
| Sales evaluation unchanged | `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7 --variants chanakya,actions_only` | 0.96 / 0.99 | same before and after |
| Live check | backend with `MISSIONS_ENABLED=true WINBACK_ENABLED=true`, demo feed, `winback_device_fix` from the API | DONE by the ticketing system | Mission Control showed the holdout and reasons cards |
| e2e script | `scripts/demo/e2e_track_b.py` | not re-run | updated for the reminder tool (one new check) |

## Decisions Made

- A yes to the onboarding link covers the link and the new fixed-text `send_onboarding_reminder` only; `send_summary` always needs its own yes
- Demo scenarios run their own mission's verification jobs early (`OnboardingVerifier.run_mission_now`) instead of moving the shared clock
- Holdout merchants get no mission: a `HOLDOUT_ASSIGNED` event under `holdout_<merchant_id>`, listed in Mission Control, so mission counts stay honest
- Charges, rental and setup reasons are answered from the sourced pages, then a sales visit is offered with explicit consent; DONE needs a device active again or a payment within 14 days
- Win-back never offers a product: `RECOMMEND` is illegal on win-back missions, and any LLM line mentioning an offer, discount or waiver falls back to a template
- The win-back reason must come from a real answer after "why did you stop?" and is kept as evidence on the next move, because the lexical belief swings on fillers
- Permission-first is a field on the brain's mission card (`permission_first`), set from `PERMISSION_FIRST_ENABLED` at the adapter, so planners never read the environment

## Blockers / Risks

- The win-back rule for keeping evidence was written after reading evaluation seed 7 traces, so those numbers are not cleanly held out (stated in the results)
- Live calls do not pass answer pauses into the brain's turns, so the long-pause "haan" rule only works where a pause is known
- The win-back evaluation is offline only (template twins); no online run

## Next Session Startup

1. Read `CLAUDE.md`, `progress.md` and this file.
2. `git branch` should list the six branches above; `git log --oneline main..feat/P1-permission-first` shows six commits.
3. Run `./init.sh` on the branch you work on.

## Recommended Next Step

- Ask Gurnoor for the after-the-fact review of F1, W0 and W1
- Then: re-measure win-back with N1's scorer once it lands, add fresh former-customer personas for a clean held-out check, and let B12 reuse `leaving_reasons()` from `chanakya/missions/churn.py`
