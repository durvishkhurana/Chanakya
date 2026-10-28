# Session Progress Log

## Current State

**Last Updated:** 2026-10-29
**Active Feature:** none. Next up: F0.2 (Track B, Gurnoor), then Track A starts A1 (Durvish)

| Track | Owner | Active task | Status |
|---|---|---|---|
| A: brain, sim, eval, voice | Durvish Khurana | A1 concerns and personas | waiting on F0.2 |
| B: missions, actions, humans, frontend | Gurnoor Singh Pannu | F0.2 core contracts | not started |

## Status

### What's Done

- [x] F0.1 bootstrap: voice agent moved to the root layout (`backend/`, `agent/`, `frontend/`, `data/knowledge/`), persona renamed to Chanakya, README, `.gitignore`, Ruff config; pushed to `github.com/durvishkhurana/Chanakya` as the initial commit on `main`
- [x] Idea finalised in `docs/IDEA.md`, with Step A as a three-door mission intake
- [x] API keys verified: Sarvam STT/TTS round trip; OpenRouter with `deepseek/deepseek-v4-flash` and `openai/gpt-6-luna`
- [x] Harness: `CLAUDE.md`, `feature_list.json`, `progress.md`, `session-handoff.md`, `init.sh`

### What's In Progress

- [ ] Nothing in progress

### What's Next

1. F0.2: shared contracts in `chanakya/core/`, including `MissionCard` with `why_now` and `starting_worries`
3. From now on every change lands through a `feat/<ID>-<slug>` branch and a PR

## Blockers / Risks

- [ ] OpenRouter account shows $0 credits. Calls still succeed, but may start failing with HTTP 402. Add credits before the eval run (I2)
- [ ] OpenRouter key expires 2026-11-04 and has a $50/day limit
- [ ] Twilio trial accounts block Media Streams, so live phone calls may not work. Browser voice is the safe demo path
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
