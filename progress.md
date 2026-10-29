# Session Progress Log

## Current State

**Last Updated:** 2026-10-29
**Active Feature:** none in progress. Track B's must-have tasks are done; Track A has not started.

| Track | Owner | Done | Next |
|---|---|---|---|
| 0 / B: missions, actions, humans, frontend | Gurnoor Singh Pannu | F0.2, B1–B9, B14, B15 | B11 coach UI waits on A11; I1 demo scenarios with Durvish |
| 0 / A: brain, sim, eval, voice | Durvish Khurana | F0.1 | A1 concern bank and personas (F0.2 is merged, nothing blocks it) |

## Status

### What's Done

- [x] F0.1 bootstrap, F0.2 shared contracts (`chanakya/core`)
- [x] B1 mock systems and typed tool registry, B2 safety gate and audit, B3 mission ledger and state machine
- [x] B4 handoff cards and queue, B5 API and live event stream, B6 three-door mission intake and queue
- [x] B7 verification and reminders, B8 Mission Control, B9 Live Call View, B14 mock product and onboarding pages
- [x] B15 landing page (design-taste and landing-page skills)
- [x] `scripts/demo/e2e_track_b.py`: the whole Track B flow against a live backend, 17 checks

### What's In Progress

- [ ] Nothing in progress

### What's Next

1. Track A: A1 concern bank and personas. The concern ids the intake already uses are listed in PR #6 and in `chanakya/missions/intake.py` (`RULES`)
2. Track A: A3 belief tracker → A4 moves → A5 hook into the voice session. A5 should write `turn_completed`, `belief_updated` and `plan_computed` events through `POST /api/missions/{id}/events` (or the ledger directly); the Live Call View already renders them
3. Track B: B11 coach mode UI after A11; optional B10, B12, B13 are roadmap candidates
4. Together: I1 demo scenarios, I2 eval run, I3 phone demo or backup video, I4 README and deck numbers

## Blockers / Risks

- [ ] OpenRouter account shows $0 credits. Calls still succeed, but may start failing with HTTP 402. Add credits before the eval run (I2)
- [ ] OpenRouter key expires 2026-11-04 and has a $50/day limit
- [ ] Twilio trial accounts block Media Streams, so live phone calls may not work. Browser voice is the safe demo path
- [ ] All Track B PRs (#1–#13) were self-merged at the owner's request without Durvish's review; he should read them before building on `chanakya/core`
- [ ] Live calls show empty planner panels until Track A emits brain events; `/call/demo` is a labelled scripted recording until then

## Decisions Made

- **Pitch: AI merchant-success teammate that gets the job done.** The voice agent was built earlier; the Chanakya brain plus missions and actions are the new work
- **Mission intake has three doors:** the merchant raises a hand, the data says so, a human hands it over. Each trigger seeds the belief tracker's starting worries
- **Consent can cover a named set of tools** (`tools: [...]` on `consent_given`); a decline naming no tool blocks every write
- **A mission is DONE only on system confirmation.** Two reminders at most, inside calling hours; "stop" ends with one passive check; then back to the queue as SCHEDULED with a callback time
- **Missions API is behind `MISSIONS_ENABLED`** and mounted with appended lines in `backend/main.py`; the frontend reaches it through a same-origin `/api` proxy, so the backend's CORS policy is unchanged
- **Design:** app screens use the framed-sheet style (IBM Plex Sans, green-grey frame); the landing page uses the well-kept board (League Spartan and Figtree, greys and mint). Styles are scoped (`.cx`, `.lp`) so they cannot collide
- **Model settings:** `deepseek/deepseek-v4-flash` with reasoning disabled; `openai/gpt-6-luna` with reasoning effort `none`
- **No AI attribution** in commits or PRs; every merge was checked on GitHub for co-authors

## Files Modified This Session

- `chanakya/core/`, `chanakya/actions/`, `chanakya/missions/`, `chanakya/humans/` with tests in each package
- `backend/main.py` (appended router mounts), `.env.example` (appended flags)
- `frontend/`: landing page, Mission Control, Live Call View, demo pages, shared styles, `public/charts.js`, `public/assets/` (credited photos)
- `docs/TASKS.md` (B1, B6, new B14), `README.md`, this file, `session-handoff.md`, `feature_list.json`

## Evidence of Completion

- [x] Tests pass: `SKIP_INSTALL=1 FULL=1 ./init.sh` on `main` at 8659d21 → agent 94 OK, backend 94 OK, pytest 129 passed, Ruff clean, frontend 19 passed, lint clean, build compiled
- [x] End to end: `scripts/demo/e2e_track_b.py` against a live backend → 17/17 checks, 0 server errors
- [x] Manual verification in a browser: callback → mission card → link sent through the gate → mock onboarding → DONE verified; Mission Control and the Live Call View update live; design inspector 0 FAIL on all three screens

## Notes for Next Session

`.env` holds the real keys and is ignored by git. To demo Track B at night set `CALLING_HOURS=0-24`. Delete `.state/` for a fresh ledger and mock systems.
