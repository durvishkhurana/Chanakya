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

### What's In Progress

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
