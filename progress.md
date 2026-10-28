# Session Progress Log

## Current State

**Last Updated:** 2026-10-29
**Active Feature:** Track A stack (Durvish). F0.2 was built on Track A's side so Track A could start; Gurnoor reviews it before merge.

| Track | Owner | Active task | Status |
|---|---|---|---|
| A: brain, sim, eval, voice | Durvish Khurana | Track A tasks on stacked branches | in progress |
| B: missions, actions, humans, frontend | Gurnoor Singh Pannu | B1 onwards; review F0.2 first | not started |

### Stacked branches (merge in this order; each is cut from the one above)

1. `fix/windows-init`: `init.sh` works on Windows (Git Bash) and requires Python 3.12
2. `feat/F0.3-ci`: GitHub Actions runs `FULL=1 ./init.sh`
3. `feat/F0.2-core-contracts`: `chanakya/core` (needs Gurnoor's review: shared contracts)
4. `fix/voice-llm-provider`: voice agent runs on Groq while only `GROQ_API_KEY` is set; OpenRouter behaviour unchanged when its key is present
5. `feat/A1-concerns-personas`: Concern Bank (13 concerns), trigger priors, 68 fictional personas
6. `feat/A2-twins`: Twin-A and Twin-B with a deterministic judge, walk-away calibration, adversarial personas
7. `feat/A3-belief-tracker`: Bayesian belief tracker with lexical and LLM evidence scorers and hesitation cues
8. `feat/A4-moves-baseline-planner`: typed move library with preconditions and the rule-and-belief baseline planner
9. `feat/A5-realizer`: LLM and template realizers, BrainAgent voice integration behind PLANNER_ENABLED
10. `feat/A6-lookahead-planner`: NRPA look-ahead planner over belief-sampled Twin-A merchants, now the voice planner when PLANNER_ENABLED
11. `feat/A8-eval-harness`: evaluation harness (offline and online), plus twin realism, belief and rate-limit fixes it surfaced
12. `feat/A9-strategy-forest`: Strategy Forest mined from 540 synthetic multilingual transcripts; lookup under 50 ms; no measured win-rate gain yet
13. `feat/A10-safety-suite`: adversarial and safety suite, zero violations offline and online
14. `feat/A11-coach-engine`: coach mode engine for human telecaller calls (silent; suggestions only)
15. `feat/A7-plan-while-listening`: speculative turns from partial transcripts behind PLANNING_WHILE_LISTENING (default off)
16. `feat/I2-results`: measured offline evaluation (seeds 7 and 13), safety suite (offline and online), calibration and latency results in docs/results

## Status

### What's Done

- [x] F0.1 bootstrap: voice agent moved to the root layout (`backend/`, `agent/`, `frontend/`, `data/knowledge/`), persona renamed to Chanakya, README, `.gitignore`, Ruff config; pushed to `github.com/durvishkhurana/Chanakya` as the initial commit on `main`
- [x] Idea finalised in `docs/IDEA.md`, with Step A as a three-door mission intake
- [x] API keys verified: Sarvam STT/TTS round trip; OpenRouter with `deepseek/deepseek-v4-flash` and `openai/gpt-6-luna`
- [x] Harness: `CLAUDE.md`, `feature_list.json`, `progress.md`, `session-handoff.md`, `init.sh`
- [x] F0.2 core contracts: schemas, interfaces, typed event bus, settings with flags off, OpenRouter/Groq LLM client with five roles, fakes for every interface. Groq is the provider for now (`LLM_PROVIDER=groq`) while OpenRouter credits are arranged
- [x] Voice agent on Groq: live text turns verified (English greeting, Hindi Soundbox question answered from the source with no invented rental, fake-staff OTP request refused); Sarvam key verified with one Hindi TTS call; em dashes stripped from spoken text in code
- [x] A1 Concern Bank and personas: 13 concerns with Hindi, Hinglish, Punjabi and English phrasings; every resolve condition points to a real knowledge node and quotes no price; priors for all 11 triggers (IDEA rows copied exactly, others marked design_default); 68 seeded personas split planning/evaluation with disjoint cities and 8 adversarial
- [x] A2 merchant twins: deterministic judge (willingness rises only when a hidden concern is resolved without invented money claims; falls on pressure, repetition, ignored objections, sensitive-data requests), walk-away rule, template and LLM voices, Twin-B refuses planning personas; untreated agent loses 63% (planning) and 58% (evaluation) of merchants over 20 seeds
- [x] A3 belief tracker: starts from the mission card prior (smoothed 15% toward uniform), Bayesian update with decay, likelihood from an LLM scorer (Groq) or an offline trigram-and-cue-word scorer, hesitation from pause, fillers, speech rate and short deflections; BeliefUpdated events carry latency
- [x] A4 moves and baseline planner: preconditions (disclose first and once, write only with explicit consent for that exact tool, only closing moves after a clear no, unknown concerns/products/tools rejected), explicit-consent detector that never accepts a bare haan/okay, decline/distress/sensitive-request/denial signals; baseline planner wins 68.3% consent + 20.0% follow-up on Twin-A vs 38.7% consent for an untreated pitch
- [x] A5 realizer and agent integration: LLM realizer grounded in the move's knowledge nodes plus the agent's sales rules, every line checked (sensitive data, invented money, pressure, claimed actions, unasked consent) with reviewed templates as fallback; BrainAgent plugs into the existing voice session behind PLANNER_ENABLED; TurnCompleted events carry belief and move; live voice calls verified with the flag on and off
- [x] A6 look-ahead planner: candidates are the baseline move plus the strongest alternatives (consent question and stopping always included), merchants sampled from the belief, NRPA level 2 adapts the two-turn follow-up policy against Twin-A's judge, candidates scored by the mean of fresh rollouts (expected value, not a lucky best rollout); safety and consent rules bypass search; 300 ms budget with baseline fallback. On 300 Twin-A calls: consent 0.897 vs baseline 0.683 in 4.7 vs 6.7 agent turns
- [x] A8 evaluation harness: one command runs reactive, actions-only, Chanakya and Chanakya-without-belief on 100 held-out Twin-B calls plus 12 adversarial calls with fixed seeds and writes JSON/Markdown/HTML; offline (deterministic) and online (LLM agents, Twin-B LLM voice, judge-labelled moves) modes; actions run on labelled mocks until B1
- [x] A10 safety suite: 12 scripted scenarios (prompt injection, OTP phishing, pressure, invented-price bait, ambiguous 'haan' consent, distress, decline) checked turn by turn; zero violations offline and with the live Groq realizer; it also caught two planner bugs that are now fixed
- [x] A11 coach engine: belief tracker and look-ahead planner follow a human telecaller's call and suggest the next move with a one-line reason after each merchant turn, as CoachSuggestion events; never speaks or acts; tested on a fictional recorded call (chanakya/humans/coach_engine.py is the agreed Track A file in Track B's package; chanakya/humans/__init__.py was added with a docstring only)
- [x] A7 planning while listening: BrainAgent prepares the next turn on a copy of the state from partial transcripts (no writes, no events), commits it only if the final matches and the state has not moved on; voice session hook behind PLANNING_WHILE_LISTENING=false by default. With fixed fake model delays, median turn latency 1065 ms -> 459 ms; live on Groq's free tier the comparison is dominated by rate limits, so it stays off
- [x] I2 results: docs/results holds two seeded offline evaluations of all four variants, the safety suite offline and online (zero violations), twin calibration and planning-while-listening latency, each with its command, plus a README stating what the numbers do and do not support (Chanakya does not beat actions-only on success offline; belief is what separates it from the ablation)

### What's In Progress

- [ ] A9 Strategy Forest (`feat/A9-strategy-forest`): built and wired as NRPA's candidate prior; lookup 1-4 ms; but it does not yet improve win rate in the evaluation harness (0.97 with and without), so not done
- [ ] F0.3 CI (`feat/F0.3-ci`): workflow runs `FULL=1 ./init.sh` on every push and PR; passes locally, waiting for the first green GitHub Actions run on `main`

### What's Next

1. Gurnoor: review `feat/F0.2-core-contracts`, then start B1 against `chanakya/core`
2. Update `docs/TASKS.md` to match the new Step A: B1 tool list, B6 intake, new B14 demo pages (already reflected in `feature_list.json`)
3. From now on every change lands through a `feat/<ID>-<slug>` branch and a PR

## Blockers / Risks

- [ ] OpenRouter account shows $0 credits. Calls still succeed, but may start failing with HTTP 402. Add credits before the eval run (I2)
- [ ] OpenRouter key expires 2026-11-04 and has a $50/day limit
- [ ] Twilio trial accounts block Media Streams, so live phone calls may not work. Browser voice is the safe demo path
- [ ] `docs/TASKS.md` still describes the old trigger engine (B6) and tool set (B1); `feature_list.json` and `docs/IDEA.md` are newer
- [ ] Scope: 32 tasks is large for the time available. Tasks with "Roadmap candidate" notes are the first to cut

## Decisions Made

- **Pitch: AI merchant-success teammate that gets the job done.** The voice agent was built earlier; the Chanakya brain plus missions and actions are the new work
- **Mission intake has three doors:** the merchant raises a hand, the data says so, a human hands it over. Each trigger seeds the belief tracker's starting worries
  - Alternatives considered: signal-only triggers with device repair and settlement missions. Rejected as not demonstrable and not believable on a call
- **Model settings:** `deepseek/deepseek-v4-flash` with reasoning disabled (default mode garbled a simple answer); `openai/gpt-6-luna` with reasoning effort `none`
- **Python 3.12** for all code; the inherited code runs on it unchanged
- **Initial commit went straight to `main`** because the repository was empty; everything after goes through PRs

- **Twin realism fix found by the evaluation (2026-10-29):** with the first twin, an agent that only answered what it heard and asked repeatedly reached 98% consent offline, above Chanakya's 91-92%. The twin voiced its worries too often and an open worry barely blocked a yes, contrary to docs/IDEA.md and arXiv 2605.22240. The twin now holds worries back, each open worry multiplies the chance of a yes by 0.35, and re-asking after a no is pressure; the untreated agent stays calibrated at 64-66% decline. Even so, actions-only (0.99) and Chanakya (0.97) are within noise offline; Chanakya closes in fewer turns and its belief is what separates it from the no-belief ablation (0.54). Do not claim Chanakya beats actions-only on success from these runs
- **A6 numbers after the twin change:** on 300 Twin-A calls NRPA consent 0.943 vs baseline 0.670; on 150 held-out calls 0.933 vs 0.847

- **Repeated objections, follow-up:** when a merchant raises an already answered worry again (for example a second price question), Chanakya asks for consent instead of answering again. An attempt to reopen answered worries (damping the belief after an answer) regressed the evaluation from 0.97 to 0.19-0.95 because the belief has no 'no worry left' state, so it was reverted. Needs a 'none' outcome in the belief before retrying

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
