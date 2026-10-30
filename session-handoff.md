# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: everything planned is built. Left: Gurnoor's hand-written N1 test set, the I3 phone demo or backup video, a real-microphone call, and Gurnoor's review of work merged without it. A9 and N4 are blocked on measured results, not on code (see below)
- Branches: `fix/codebase-review` (bug fixes from a full review) and `feat/finish-remaining` (built on it: B10 UI, B13, N4, measurements, docs)

## Completed This Session (2026-10-31, Durvish)

- [x] N3 value network measured and merged (#36); N2 semantic memory built, measured and merged (#38)
- [x] Codebase review, on `fix/codebase-review`:
  - the N2/N3 merge left `backend/main.py` and `chanakya/brain/mission_call.py` unable to import and `PLANNER_VALUE` always None; the planner now gets both settings
  - the ledger, scheduler and hand-off queue shared one SQLite connection with unlocked reads across threads (the flaky scenario test); every use now holds the store's lock, and the mock systems database has the same lock
  - `get_ticket_status` could read another merchant's ticket; it now needs the merchant id
  - visit slots and callback times must be ISO date-times; device usage tolerates zone-less rows
- [x] On `feat/finish-remaining`:
  - B10: Gurnoor's approval queue merged in, plus the Mission Control Approvals tab
  - B13: `chanakya/actions/systems/messaging_channels.py` (templates per channel and language, simulated inbox, replies move the mission), `/api/messages`, thread and reply box on the mission detail
  - N4: `core:` beliefs carry the scorer's evidence and name; Live Call View and coach mode show what the scorer heard; coach mode shows each suggestion's look-ahead value and follows `PLANNER_VALUE` and `PLANNER_MEMORY=neural`; architecture diagram and README updated
  - win-back re-measured with the embedding scorer; every planner variant measured with the embedding scorer
  - README repaired after the N2 merge (duplicate rows and paragraphs); the demo script prints Hindi on Windows consoles

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| Everything, with the real encoder | `NEURAL=1 FULL=1 ./init.sh` on `feat/finish-remaining` | passed, 477 pytest, Ruff clean, frontend lint, tests and build |
| End to end, every neural setting on | backend with `MISSIONS_ENABLED=true CALLING_HOURS=0-24 WORRY_SCORER=embedding PLANNER_MEMORY=neural PLANNER_VALUE=network`, then `python scripts/demo/e2e_track_b.py http://127.0.0.1:8767` | 18/18 |
| Demo scenarios, every neural setting on | `WORRY_SCORER=embedding PLANNER_MEMORY=neural PLANNER_VALUE=network python scripts/demo/scenarios.py` | 5/6: `winback_device_fix` fails (see Blockers); 6/6 with the default scorer |
| Approvals and messages in the browser | live backend with `APPROVAL_TOOLS=book_field_visit`, `soundbox_service` scenario | the visit waited, was approved as Sunita and executed; the thread shows the SMS template |
| Planner variants with the embedding scorer | `docs/results/neural-combined/README.md` | no consistent gain from forest, memory or value network |
| Win-back with the embedding scorer | `docs/results/winback/README.md` | reason accuracy 0.90/0.84 vs 0.94/0.88; no gain |

## Decisions Made

- Defaults stay `WORRY_SCORER` unset (lexical), `PLANNER_MEMORY=forest`, `PLANNER_VALUE=formula`: N2 and N3 show no gain
- Coach mode keeps planning without the forest unless `PLANNER_MEMORY=neural`, so its replay is unchanged
- The N1 head was not retrained or tuned on the win-back demo line; N4 stays blocked until a head reads it

## Blockers / Risks

- N4 done-when needs all demo scenarios with every neural setting on; `winback_device_fix` fails with `WORRY_SCORER=embedding` (head: rental cost 0.35, device issue 0.34)
- A9 has no consistent measured gain with either scorer
- `gh` was installed on Durvish's machine, but its login had not completed, so the last two branches may be pushed without PRs; see the next step
- Work merged at the owner's request without Gurnoor's review: F1, W0, W1, the two `core:` settings, the codebase fixes, B10's UI, B13, N4

## Next Session Startup

1. Read `CLAUDE.md`, `progress.md` and this file; run `./init.sh` (and `NEURAL=1 ./init.sh` for neural work, with `HF_HOME` on a drive with space).
2. If `fix/codebase-review` and `feat/finish-remaining` have no PRs yet: `gh auth login`, then open and merge `fix/codebase-review` first, then `feat/finish-remaining` (it contains the fix branch, so no conflict).

## Recommended Next Step

- Gurnoor: the hand-written test set, then retrain or re-check N1 and re-run the demo scenarios with `WORRY_SCORER=embedding` to close N4
- I3: the backup video or the allowlisted phone call (`docs/PHONE_DEMO.md`)
