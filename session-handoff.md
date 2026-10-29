# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Track A and Track B are merged on `main` (Track A in PRs #15-#17). B11 coach mode UI is done on `feat/B11-coach-ui`
- Branch / commit: `feat/B11-coach-ui`, cut from `main` at `844da64`

## Completed This Session

- [x] Pulled Track A onto local main; `FULL=1 ./init.sh` passed (271 pytest)
- [x] B11 coach mode UI: `chanakya/humans/coach_api.py` (`/api/coach`, behind `COACH_ENABLED`) runs the A11 `CoachEngine` turn by turn; `frontend/src/app/coach/` shows the call, the suggested next move with how to answer and its sourced pages, the concern meter and a hand-off card

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Everything | `SKIP_INSTALL=1 FULL=1 ./init.sh` | passed | agent 104 OK, backend 98 OK, pytest 277, Ruff clean, frontend 22 tests, lint, build |
| Coach API | `python -m pytest chanakya/humans` | 11 passed | recorded fixture replay, pinned seed, distress hand-off, bad input |
| Browser | `/coach` at 1440 and 375 px | verified | recorded call end to end; typed distress line drafted the hand-off card; no page overflow |

## Files Changed

- `chanakya/humans/coach_api.py`, `chanakya/humans/tests/test_coach_api.py`, `backend/main.py` (appended mount)
- `frontend/src/app/coach/`, `frontend/src/lib/coachView.mjs` and its test, `frontend/src/components/missions/` (nav item, icon), `frontend/src/lib/missionView.mjs` (three worry labels)
- `README.md`, `feature_list.json`, `docs/TASKS.md`, `progress.md`, this file

## Decisions Made

- The recorded call pins the planner seed (mission id `coach_recorded`) so every replay shows the same suggestions; typed calls use a random id
- The hand-off card is copied as text; coached calls are not ledger missions, so nothing is sent to the hand-off queue

## Blockers / Risks

- The NRPA planner's choice varies a lot with its seed on the recorded call (see `progress.md`, Blockers); this is Track A (A6)
- OpenRouter has no credits; Groq's free tier rate limits make full online evaluations impossible

## Next Session Startup

1. Read `CLAUDE.md`.
2. Read `feature_list.json` and `progress.md`.
3. Review this handoff.
4. Run `./init.sh` before editing.

## Recommended Next Step

- Write the brain's `turn_completed`, `belief_updated` and `plan_computed` events into the ledger during live calls so the Live Call View shows real calls, and align the concern ids between intake and the Concern Bank
