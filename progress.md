# Session Progress Log

## Current State

**Last Updated:** 2026-10-29
**Active Feature:** Track A ported onto main's core contracts on `feat/track-a-on-main`; needs Gurnoor's review (it also carries a small `core:` change and the Windows fixes).

| Track | Owner | Done | Open |
|---|---|---|---|
| A: brain, sim, eval, voice | Durvish Khurana | A1-A8, A10, A11 (on `feat/track-a-on-main`) | A9 (forest built, no measured gain), F0.3 (CI green on main not yet seen) |
| B: missions, actions, humans, frontend | Gurnoor Singh Pannu | F0.2, B1-B9, B14 (merged on main) | B10-B13 |
| Integration | both | I2 measured results in `docs/results/` | I1, I3, I4 |

## Status

### What's Done

- [x] F0.1 bootstrap, idea, harness (see Decisions)
- [x] Track B on main: shared contracts (F0.2), mock systems and registry, safety gate, ledger and state machine, hand-offs, APIs, intake and queue, follow-ups and verification, Mission Control, Live Call View, demo pages
- [x] Track A (Durvish), on `feat/track-a-on-main`:
  - A1 Concern Bank (13 concerns in Hindi, Hinglish, Punjabi, English, resolved only by sourced knowledge nodes), trigger priors, 68 seeded personas split planning/evaluation
  - A2 Twin-A and Twin-B with a deterministic judge and walk-away calibration (untreated agent loses 64-67%)
  - A3 Bayesian belief tracker with LLM or lexical evidence and hesitation cues
  - A4 typed moves with hard preconditions and the baseline planner; A6 NRPA look-ahead planner (consent 0.943 vs 0.670 baseline on 300 Twin-A calls)
  - A5 LLM realizer with safety fallbacks, BrainAgent in voice calls behind `PLANNER_ENABLED`; live voice calls verified with the flag on and off
  - A7 planning while listening behind `PLANNING_WHILE_LISTENING` (p50 1065 -> 457 ms with fake delays; off by default)
  - A8 evaluation harness; A10 safety suite (zero violations offline and online); A11 coach engine
  - I2 measured results in `docs/results/README.md`
- [x] Groq works end to end (core LLM client, voice agent, twins, judge) while OpenRouter credits are arranged

### What's In Progress

- [ ] A9 Strategy Forest: built and wired as the planner's candidate prior, lookup 1-4 ms, but no win-rate gain in the harness (0.97 with and without)
- [ ] F0.3 CI: `.github/workflows/ci.yml` runs `FULL=1 ./init.sh` on every push and PR; check the Actions tab once merged

### What's Next

1. Gurnoor: review and merge, in order, `fix/windows-dev-setup`, `feat/core-llm-providers` (core change), then `feat/track-a-on-main`
2. Connect the brain to the mission runtime: adapters from `chanakya.core` PlanContext/BeliefTracker/Realizer to the Track A planner, belief tracker and realizer, and the real ActionGate instead of the mock gate
3. A9: richer transcripts or concern-history features before claiming a gain; repeated objections need a "no worry left" outcome in the belief (see Decisions)
4. Track B: B10-B13; together: I1, I3, I4

## Blockers / Risks

- [ ] OpenRouter account shows $0 credits and the key expires 2026-11-04; Groq is in use. Groq's free tier allows 8,000 tokens per minute on the main model, so full online evaluations are not possible on it
- [ ] Twilio trial accounts block Media Streams; browser voice is the safe demo path
- [ ] The old stacked branches (`fix/windows-init` ... `feat/I2-results`) were built on the pre-merge core; they are superseded by `feat/track-a-on-main` and should not be merged
- [ ] The frontend production build downloads Google Fonts, so it needs network access

## Decisions Made

- **Track A ported onto main's core (2026-10-29):** Gurnoor merged F0.2 and Track B while Track A was being built on a separate contracts branch. Track A's own types moved to `chanakya/brain/contracts` (personas, consent-aware dialogue state, typed brain events, fakes), and its LLM calls now go through `chanakya.core.llm`, which gained a Groq provider in a separate `core:` change. Offline evaluation and safety numbers were identical before and after the port
- **Twin realism fix found by the evaluation:** the first twin voiced worries too often and let merchants agree with worries open, so an answer-and-ask-repeatedly agent reached 98% against Chanakya's 91-92%. The twin now holds worries back (arXiv 2605.22240), each open worry multiplies the chance of a yes by 0.35, and re-asking after a no is pressure. Even so actions-only (0.99) and Chanakya (0.97) are within noise offline; do not claim Chanakya beats actions-only on success
- **Repeated objections, follow-up:** a merchant who raises an answered worry again gets a consent question instead of a second answer. Reopening answered worries by damping the belief regressed the evaluation (0.97 -> 0.19-0.95) because the belief has no "no worry left" state, so it was reverted
- **Planning while listening is off by default:** live on Groq's free tier it added calls and rate-limit waits; enable only on a paid tier

- **Pitch: AI merchant-success teammate that gets the job done.** The voice agent was built earlier; the Chanakya brain plus missions and actions are the new work
- **Mission intake has three doors:** the merchant raises a hand, the data says so, a human hands it over. Each trigger seeds the belief tracker's starting worries
  - Alternatives considered: signal-only triggers with device repair and settlement missions. Rejected as not demonstrable and not believable on a call
- **Model settings:** `deepseek/deepseek-v4-flash` with reasoning disabled (default mode garbled a simple answer); `openai/gpt-6-luna` with reasoning effort `none`
- **Python 3.12** for all code; the inherited code runs on it unchanged
- **Initial commit went straight to `main`** because the repository was empty; everything after goes through PRs

## Files Modified This Session

- Root layout created from the old `sales_agent/` folder; `call_mira.py` renamed to `call_chanakya.py`
- `agent/documents.py`, `agent/tools.py`, `backend/test_voice_api.py` - three Ruff findings fixed without changing behaviour
- `requirements.lock.txt` - removed comment lines with another machine's local paths
- Planning drafts moved out of the repository to `../paytm-archive/`

## Evidence of Completion

- [x] Tests pass: `FULL=1 ./init.sh` → agent 94 OK, backend 94 OK, Ruff clean, frontend 9 pass, lint clean, build compiled
- [x] Manual verification: backend `/api/health` returns `configured: true`; the built page shows "Talk to Chanakya"
- [ ] Live browser voice call with the new keys not yet tried

## Notes for Next Session

`.env` holds the real keys and is ignored by git. On macOS, `agent/` and `Agent/` look the same to the filesystem; imports must use lowercase `agent.` so they also work on Linux.
