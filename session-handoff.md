# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Track A, Track B and coach mode (B11) are on `main`. Four PRs wait for Gurnoor's review, in merge order: #19 I1 demo scenarios, #20 A6 planner seed stability (with the A9 finding), #21 I3 live-call fallbacks and runbook, #22 I4 README
- Branch / commit: this note is on `docs/I4-readme`, cut from `main` at `688086c`; each PR branch was cut from the same commit

## Completed This Session

- [x] #19 `feat/I1-demo-scenarios`: the brain runs on real missions (`MissionCall`), four IDEA section 8 scenarios from one command and from Mission Control, typed and browser-voice calls on a mission, F0.3 closed with CI evidence
- [x] #20 `fix/A6-planner-seed-stability`: "baad mein" no longer a busy cue, stratified sampling with 12 merchants; results re-measured; `python -m chanakya.eval.planner_checks lookahead|stability|forest`; A9 recorded as blocked (no measured gain)
- [x] #21 `feat/I3-phone-demo`: `VOICE_LLM_TIMEOUT_MS` (default 4000) falls back to templates and lexical evidence on a stalled provider; `docs/PHONE_DEMO.md`
- [x] #22 `docs/I4-readme`: README "How it works", `docs/architecture.svg`, screenshots, Status rewritten

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| I1 | `FULL=1 SKIP_INSTALL=1 ./init.sh` on #19 | pytest 283, frontend 22, build compiled | scenarios 4/4; live backend checked from the dashboard |
| A6 | `SKIP_INSTALL=1 ./init.sh` on #20 | pytest 279 | harness seeds 7 and 13 regenerated into `docs/results`; stability 21/42 whole runs identical (was 13) |
| I3 | `SKIP_INSTALL=1 ./init.sh` on #21 | pytest 280 | live Groq turns 1.3-1.5 s, no fallback |
| I4 | `SKIP_INSTALL=1 ./init.sh` on #22 | pytest 277 | docs only |

## Decisions Made

- A6: common random numbers did not reduce the seed swing (the noise was in which merchants were sampled), so only stratified sampling and 12 samples were kept; the cost is planner p50 58 -> 111 ms
- A9 is blocked, not done: the forest changes nothing measurable (0.96/0.98 harness, 0.920 vs 0.917 and 0.953 vs 0.953 consent)
- The README quotes only numbers that #20 does not change and links `docs/results` for the rest

## Blockers / Risks

- I3 is done only with a call to the allowlisted number or a recorded backup video; both need Durvish with the phone (and an upgraded Twilio account for Media Streams). Steps are in `docs/PHONE_DEMO.md`
- Browser voice on a mission was checked up to `voice_ready`; a spoken turn with a microphone is not yet tried
- `gh` cannot be installed on this machine; PRs are opened in the browser
- OpenRouter has no credits; Groq's free tier rules out full online evaluations

## Next Session Startup

1. Read `CLAUDE.md`.
2. Read `feature_list.json` and `progress.md`.
3. Review this handoff.
4. Run `./init.sh` before editing.

## Recommended Next Step

- After the four PRs merge (resolve `progress.md`, `feature_list.json` and this file by keeping both sides' facts): record the backup video from `docs/PHONE_DEMO.md`, path A, and close I3 and I4
