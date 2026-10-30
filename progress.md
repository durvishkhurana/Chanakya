# Session Progress Log

## Current State

**Last Updated:** 2026-10-30
**Active Feature:** Phase 6 (Durvish): D1, F1, W0, W1, W2 and P1 done on six stacked branches, rebased onto main at `8de04f8` and pushed; PRs not opened yet (see `session-handoff.md`). N1 neural worry scorer is next on Gurnoor's side.

| Track | Owner | Done | Open |
|---|---|---|---|
| B: missions, actions, humans, frontend | Gurnoor Singh Pannu | F0.2, B1-B9, B11, B14, B15 | B10, B12, B13 roadmap |
| A: brain, sim, eval, voice | Durvish Khurana | A1-A8, A10, A11, F0.3 (merged on main) | A9 (forest built, no measured gain) |
| Integration | both | I1 demo scenarios, I2 measured results in `docs/results/` | I3 (needs a phone or a backup video), I4 |
| N: neural brain | Gurnoor Singh Pannu | N0 baselines, labelled lines, encoder choice | N1 worry scorer, N2 semantic memory, N3 value network, N4 demo |
| W: review fixes, win-back, permission-first | Durvish Khurana | D1 specs, F1 #19 review fixes, W0 contracts, W1 win-back missions, W2 win-back brain, P1 permission-first | PRs to open and review |

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
- [x] I1 demo scenarios (Durvish), on `feat/I1-demo-scenarios`:
  - `chanakya/brain/mission_call.py`: `MissionCall` runs the brain on a real mission; every turn, belief and plan goes to the ledger in the core shapes, AI disclosure and explicit consent are recorded where the gate checks them, writes go through Track B's `ActionGate` and mock systems, distress opens an urgent hand-off, a clear no closes the mission
  - `chanakya/brain/scenarios.py` and `scripts/demo/scenarios.py`: the four IDEA section 8 scenarios from one command, 4/4 passing
  - `chanakya/brain/calls_api.py` (`/api/calls`, behind `MISSIONS_ENABLED`): run a scenario or speak as the merchant; Mission Control has a "Run scenario" control and the Live Call View a "Speak as the merchant" box; `/api/calls/<id>/voice` runs a spoken browser call on the mission ("Talk by voice instead")
- [x] N0 neural baselines (Gurnoor): 2,123 labelled merchant lines from two model families (`data/neural/worry_lines.jsonl`); on 668 held-out lines the lexical scorer gets 0.388 of 14 labels, `multilingual-e5-small` with no training 0.437 at about 5 ms, the LLM scorer 0.777 at about 2 s; e5-small chosen as the shared encoder (`docs/results/neural-baseline/`)
- [x] F0.3 CI: `.github/workflows/ci.yml` runs `FULL=1 ./init.sh`; green on main for #16, #17 and #18 (runs 23, 25, 28)
- [x] Groq works end to end (core LLM client, voice agent, twins, judge) while OpenRouter credits are arranged

### Phase 6: review fixes, win-back and permission-first (Durvish)

Specs for F1, W0, W1, W2 and P1 are in `docs/TASKS.md` (Phase 6) and `feature_list.json`. Win-back missions (W1): `chanakya/missions/churn.py` finds former merchants (CRM says former, a returned device, or no payment for 60 days), calls those who churned 14 to 180 days ago and had no win-back in 90 days, hands merchants with an open complaint to a person, and holds out 20% by a seeded hash (demo seed 2027 holds out Joginder). A win-back mission is DONE only on a resolved ticket, a device active again or a payment within 14 days of the call. **B12 (manager insights) should reuse `leaving_reasons()` in `chanakya/missions/churn.py` and the Mission Control reasons card, not rebuild them.** Order: F1 (the #19 review points), W0 (`core:` contracts and both flags), W1 (churn detection, holdout, DONE check), W2 (the win-back conversation), P1 (permission-first opening for lead-list missions). W1 and F1 edit Track B directories and need Gurnoor's review. This work stays out of the N1-N4 files (`belief.py`, `sim/voice.py`, `eval/variants.py`, `agent/brain_agent.py`, `coach_engine.py`), with one exception: W2 adds a three-line branch to `agent/brain_agent.py` (`_turn`) so a planned read tool such as `get_settlement_status` runs through the gate before the realizer speaks; Gurnoor's N1 wiring there should keep it. Win-back conversation (W2): listen first, act only on a clear reason, never an offer; measured offline in `docs/results/winback/` (reason accuracy 0.88-0.94 on held-out former customers, fix rate 0.83-0.90, with the caveats listed there). The lexical belief swings on filler words; N1's scorer should be re-measured on the win-back harness. Permission-first (P1): lead-list calls ask for two minutes before anything else. Live calls do not pass answer pauses into the brain's turns (only the core adapters carry `pause_ms`), so on a live call a bare "haan" counts as yes; the long-pause deflection rule applies where a pause is known.

### What's In Progress

- [ ] A9 Strategy Forest (blocked): built and wired as the candidate prior, lookup 1-4 ms, but no measured gain (harness 0.96/0.98 with and without; look-ahead consent 0.920 vs 0.917 and 0.953 vs 0.953); needs harder twins or real transcripts
- [ ] F0.3 CI: `.github/workflows/ci.yml` runs `FULL=1 ./init.sh` on every push and PR; check the Actions tab once merged

### What's Next

1. Gurnoor: N1 neural worry scorer on e5-small (sigmoid head, calibrated on a validation split, selected by `WORRY_SCORER` from a small `core:` PR, run through ONNX); first, Gurnoor and Durvish write the hand-written test set (about 150 lines each), plus a twin voice that speaks the held-out lines so the harness can measure it end to end
2. Then N2 semantic memory and N3 value network (both after N1), then N4 to show them in the Live Call View and coach mode
3. Durvish: the eight review points on #19 are still open on main; the first three matter for the demo (a second brain on a running scenario's mission, a link yes approving any `send_summary`, the callback scenario moving the live clock)
4. Try a spoken call on a mission with a real microphone; phone calls (Twilio) still run without a mission (I3)
5. Track B: optional B10, B12, B13

## Blockers / Risks

- [x] Review points on #19 fixed on `fix/I1-review-fixes` (F1): one brain per mission while a scenario runs, a link yes covers only the link and the new fixed-text `send_onboarding_reminder`, the callback scenario no longer moves the clock, turns are locked and shielded, every decline is recorded and closes the mission
- [ ] The neural parts need `requirements-neural.txt` (PyTorch through sentence-transformers) and a one-time model download of about 470 MB; `./init.sh` and CI do not install them

- [ ] OpenRouter account shows $0 credits and the key expires 2026-11-04 with a $50/day limit; Groq is in use meanwhile, and its free tier (8,000 tokens per minute on the main model) rules out full online evaluations
- [ ] Twilio trial accounts block Media Streams, so live phone calls may not work. Browser voice is the safe demo path
- [ ] All Track B PRs (#1-#14) were self-merged at the owner's request without Durvish's review; the Track A PRs need Gurnoor's review, especially the `core:` change
- [ ] Browser voice calls on a mission are wired but not yet tried with a microphone; phone calls are not tied to missions; `/call/demo` stays a labelled scripted recording
- [ ] A call left mid-way stays IN_CONVERSATION until someone speaks on it again
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
- **Consent can cover a named set of tools** (`tools: [...]` on `consent_given`); a decline naming no tool blocks every write. Chanakya's link question also asks about a reminder, so a yes to it is recorded for `send_onboarding_link` and `send_onboarding_reminder` (fixed template, no free text); `send_summary` always needs its own yes; every other consent covers only its own tool (F1)
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

- [x] I1: `FULL=1 SKIP_INSTALL=1 ./init.sh` on `feat/I1-demo-scenarios` → agent 104 OK, backend 98 OK, pytest 283 passed, Ruff clean, frontend 22 passed, lint clean, build compiled; `python scripts/demo/scenarios.py` → 4/4 scenarios passed; live backend with Groq: all four scenarios reached DONE, DONE, AWAITING_CONFIRMATION, ESCALATED from the dashboard and the API, and a typed call updated every Live Call View panel
- [x] Tests pass: `SKIP_INSTALL=1 FULL=1 ./init.sh` on `main` at 8659d21 → agent 94 OK, backend 94 OK, pytest 129 passed, Ruff clean, frontend 19 passed, lint clean, build compiled
- [x] End to end: `scripts/demo/e2e_track_b.py` against a live backend → 17/17 checks, 0 server errors
- [x] Manual verification in a browser: callback → mission card → link sent through the gate → mock onboarding → DONE verified; Mission Control and the Live Call View update live; design inspector 0 FAIL on all three screens

## Notes for Next Session

`.env` holds the real keys and is ignored by git. To demo Track B at night set `CALLING_HOURS=0-24`. Delete `.state/` for a fresh ledger and mock systems.
