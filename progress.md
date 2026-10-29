# Session Progress Log

## Current State

**Last Updated:** 2026-10-29
**Active Feature:** none in progress. Track A merged on main (PRs #15-#17); B11 coach mode UI is done on `feat/B11-coach-ui`.

| Track | Owner | Done | Open |
|---|---|---|---|
| B: missions, actions, humans, frontend | Gurnoor Singh Pannu | F0.2, B1-B9, B11, B14, B15 | B10, B12, B13 roadmap |
| A: brain, sim, eval, voice | Durvish Khurana | A1-A8, A10, A11 (on `feat/track-a-on-main`) | A9 (forest built, no measured gain), F0.3 (CI green on main not yet seen) |
| Integration | both | I2 measured results in `docs/results/` | I1, I3, I4 |

## Status

### What's Done

- [x] F0.1 bootstrap, F0.2 shared contracts (`chanakya/core`)
- [x] B1 mock systems and typed tool registry, B2 safety gate and audit, B3 mission ledger and state machine
- [x] B4 handoff cards and queue, B5 API and live event stream, B6 three-door mission intake and queue
- [x] B7 verification and reminders, B8 Mission Control, B9 Live Call View, B14 mock product and onboarding pages
- [x] B15 landing page (design-taste and landing-page skills)
- [x] `scripts/demo/e2e_track_b.py`: the whole Track B flow against a live backend, 17 checks
- [x] B11 coach mode UI: `/coach` replays the recorded telecaller call through the A11 engine (`/api/coach`, behind `COACH_ENABLED`), with the suggestion card, how to answer from the Concern Bank with sourced pages, the concern meter, and a hand-off card when the engine says to escalate; the telecaller can also type lines
- [x] Track A (Durvish), on `feat/track-a-on-main`:
  - A1 Concern Bank (13 concerns in Hindi, Hinglish, Punjabi, English, resolved only by sourced knowledge nodes), trigger priors, 68 seeded personas split planning/evaluation
  - A2 Twin-A and Twin-B with a deterministic judge and walk-away calibration (untreated agent loses 64-67%)
  - A3 Bayesian belief tracker with LLM or lexical evidence and hesitation cues
  - A4 typed moves with hard preconditions and the baseline planner; A6 NRPA look-ahead planner (consent 0.920 vs 0.670 baseline on 300 Twin-A calls, 0.953 vs 0.847 on 150 held-out calls; seed-stable since `fix/A6-planner-seed-stability`)
  - A5 LLM realizer with safety fallbacks, BrainAgent in voice calls behind `PLANNER_ENABLED`; live voice calls verified with the flag on and off
  - A7 planning while listening behind `PLANNING_WHILE_LISTENING` (p50 1065 -> 457 ms with fake delays; off by default)
  - A8 evaluation harness; A10 safety suite (zero violations offline and online); A11 coach engine
  - I2 measured results in `docs/results/README.md`
- [x] Groq works end to end (core LLM client, voice agent, twins, judge) while OpenRouter credits are arranged

### What's In Progress

- [ ] A9 Strategy Forest (blocked): built and wired as the candidate prior, lookup 1-4 ms, but no measured gain (harness 0.96/0.98 with and without; look-ahead consent 0.920 vs 0.917 and 0.953 vs 0.953); needs harder twins or real transcripts
- [ ] F0.3 CI: `.github/workflows/ci.yml` runs `FULL=1 ./init.sh` on every push and PR; check the Actions tab once merged

### What's Next

1. Done: `fix/windows-dev-setup`, `feat/track-a-on-main` and `feat/brain-core-adapters` are merged on main (PRs #15-#17)
2. Connect the brain to the mission runtime: `feat/brain-core-adapters` exposes the planner, belief tracker and realizer through the core protocols and turns brain events into `turn_completed`, `belief_updated` and `plan_computed` ledger events; still to do is writing them through the ledger (or `POST /api/missions/{id}/events`) so the Live Call View renders live calls, checking the payload shapes it expects, and using the real ActionGate instead of the mock gate
3. A9: richer transcripts or concern-history features before claiming a gain; repeated objections need a "no worry left" outcome in the belief (see Decisions)
4. Track B: optional B10, B12, B13. Together: I1 demo scenarios, I3 phone demo or backup video, I4 README and deck numbers

## Blockers / Risks

- [ ] OpenRouter account shows $0 credits and the key expires 2026-11-04 with a $50/day limit; Groq is in use meanwhile, and its free tier (8,000 tokens per minute on the main model) rules out full online evaluations
- [ ] Twilio trial accounts block Media Streams, so live phone calls may not work. Browser voice is the safe demo path
- [ ] All Track B PRs (#1-#14) were self-merged at the owner's request without Durvish's review; the Track A PRs need Gurnoor's review, especially the `core:` change
- [ ] Live calls show empty planner panels until the brain's events reach the ledger; `/call/demo` is a labelled scripted recording until then
- [ ] Concern ids differ: intake uses `swipe_charges`, `device_reliability` and `cash_flow`; the Concern Bank uses `per_swipe_charges` and `device_issue`, and `cash_flow` is mapped to `rental_cost` in the adapters for now
- [ ] The old stacked branches (`fix/windows-init` ... `feat/I2-results`) were built on the pre-merge core; they are superseded and must not be merged
- [ ] The frontend production build downloads Google Fonts, so it needs network access
- [x] Planner seed sensitivity found in coach mode is fixed on `fix/A6-planner-seed-stability`: "baad mein" is no longer a busy cue, sampled merchants are stratified and 12 are sampled; see `docs/results/README.md` section 2a
- [ ] Coach sessions live in backend memory (at most 50) and are lost on restart; the hand-off card is copied as text, not sent to the hand-off queue, because a coached call has no mission in the ledger

## Decisions Made

- **Track A ported onto main's core (2026-10-29):** Gurnoor merged F0.2 and Track B while Track A was being built on a separate contracts branch. Track A's own types moved to `chanakya/brain/contracts` (personas, consent-aware dialogue state, typed brain events, fakes), and its LLM calls now go through `chanakya.core.llm`, which gained a Groq provider in a separate `core:` change. Offline evaluation and safety numbers were identical before and after the port
- **Twin realism fix found by the evaluation:** the first twin voiced worries too often and let merchants agree with worries open, so an answer-and-ask-repeatedly agent reached 98% against Chanakya's 91-92%. The twin now holds worries back (arXiv 2605.22240), each open worry multiplies the chance of a yes by 0.35, and re-asking after a no is pressure. Even so actions-only (0.99) and Chanakya (0.97) are within noise offline; do not claim Chanakya beats actions-only on success
- **Repeated objections, follow-up:** a merchant who raises an answered worry again gets a consent question instead of a second answer. Reopening answered worries by damping the belief regressed the evaluation (0.97 -> 0.19-0.95) because the belief has no "no worry left" state, so it was reverted
- **Planning while listening is off by default:** live on Groq's free tier it added calls and rate-limit waits; enable only on a paid tier

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
