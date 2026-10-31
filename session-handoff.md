# Session Handoff

## Current Objective

- Goal: a demo that shows every feature in one go, with you speaking as the merchant on your own phone (I3)
- Current status: **Connect phone** and **Save run log** are built on `feat/I3-phone-link` and tested through a real Cloudflare tunnel. Left: a spoken call on a real phone microphone, then the backup video. A9 and N4 stay blocked on measured results (see `progress.md`)
- Branch: `feat/I3-phone-link`, from `origin/main` at 1a4ea8d

## Latest (2026-10-31, Durvish, `feat/I3-send-link`)

- [x] Consent: a clear yes ("Yes", "Haan ji", "Ji haan", "Bilkul", "Zaroor") straight after the consent question is consent (`consent_reply` in `chanakya/brain/moves.py`, used in `agent/brain_agent.py` and `core_adapters.py`); bare "Haan", "Ok", "Achha" still are not
- [x] The call page shows the sent onboarding link as a message card with **Open the onboarding link**
- [x] `backend/link_email.py`: with `LINK_EMAIL_ENABLED=true`, each link sent on a live call is emailed to `LINK_EMAIL_TO` only (Gmail app password in `SMTP_PASSWORD`); demo scenarios never email
- [ ] Not verified: a real email (needs the SMTP values in `.env`). Phone audio fix is on `fix/phone-voice-playback` (rebased on main, not pushed); this branch alone does not have it
- Known: `test_backend_mounts_routes_only_when_enabled` fails whenever the local `.env` sets `MISSIONS_ENABLED=true` (`agent/graph.py` loads `.env` with `override=True`), on main too
- Open: a "No" to a probe question is read as the worry not being needed (belief 0.999)

## Completed This Session (2026-10-31, Durvish)

- [x] Twilio checked: trial accounts strip `<Stream>`, which the Twilio path needs, so the phone path runs in the browser instead (`docs/PHONE_DEMO.md`, path C)
- [x] `init.sh` failed at once on Windows when no Python 3.12 was on PATH; it now accepts the existing 3.12 `.venv`
- [x] `backend/phone_link.py`: `POST /api/phone-link/start|stop`, `GET /api/phone-link`; one cloudflared quick tunnel to the frontend (`PHONE_LINK_PORT`, default 3000). The Next.js `/api` proxy forwards WebSockets too, so one tunnel carries pages, REST, the ledger stream and voice. Requests that came through the tunnel (Cloudflare headers) cannot start, stop or save
- [x] `backend/run_log.py`: backend log file `.state/logs/backend.log`; `POST /api/run-logs` writes `.state/runs/<time>/` with `missions.json`, `transcript.md`, `report.md` and checks for AI disclosure, write without consent, slow replies, rule breaks in Chanakya's lines (the sim judge's `safety_violations`), mixed Latin and Devanagari, and log errors
- [x] Both mounted in `backend/main.py` behind `DEMO_TOOLS_ENABLED` (off by default); the tunnel closes on shutdown
- [x] Frontend: `wsBase()` in `chanakyaApi.js` (same-origin WebSockets off localhost), `allowedDevOrigins` for `*.trycloudflare.com`, `components/call/PhoneLink.js` (QR code via the `qrcode` package) on the Live Call View, laptop only
- [x] Runbook with the demo flow, the tested phone script, logs and a rehearsal loop: `docs/PHONE_DEMO.md`; README section "Demo on your phone"

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| Baseline before changes | `SKIP_INSTALL=1 ./init.sh` (after the init fix) | agent 105 OK, backend 98 OK, pytest 477 passed, Ruff clean, frontend 30 passed |
| New tests | `python -m unittest backend.test_demo_tools` | 8 OK |
| Full | `FULL=1 SKIP_INSTALL=1 ./init.sh` | passed: agent 105 OK, backend 106 OK, pytest 477 passed, Ruff clean, frontend lint and tests, build compiled |
| Demo scenarios | `python scripts/demo/scenarios.py` | 6/6 |
| End to end | `scripts/demo/e2e_track_b.py http://127.0.0.1:8020` with `DEMO_TOOLS_ENABLED=true` | 18/18 |
| Through a real tunnel, mobile viewport | Connect phone on the laptop, the trycloudflare URL in a 375 px tab | page, ledger stream and voice socket connect; a typed call with Groq replied in 1.1-1.9 s; link sent on consent; mock onboarding completed on the "phone"; mission DONE; start/stop/save through the tunnel return 403 |
| Live scenarios + run log | all six scenarios via the API, then Save run log | 8 calls, 0 problems, no log errors, median reply 1.3-1.4 s |

## Decisions Made

- One tunnel to the frontend instead of two: measured, the Next.js dev proxy forwards WebSocket upgrades
- `DEMO_TOOLS_ENABLED` is read in `backend/main.py` like `MISSIONS_ENABLED`, not added to `chanakya/core/config.py`, so no `core:` PR is needed; it only mounts backend routes
- A frontend change in Track B's Live Call View (`PhoneLink` panel, `wsBase`) was needed for the button; Gurnoor should review it

## Blockers / Risks

- Not tried with a real phone microphone yet: the voice socket connects through the tunnel, but the spoken audio path on a phone is untested
- While the link is open anyone with the URL can use the demo and the API keys; disconnect after each demo
- Demo traps: an OTP offer closes a sale mission; consent must answer Chanakya's question; demo on a fresh ledger (see `docs/PHONE_DEMO.md`)
- The model sometimes mixes Hinglish and Devanagari in one reply; the run report flags it, not fixed

## Next Session Startup

1. Read `CLAUDE.md`, `progress.md` and this file; run `./init.sh`.
2. Open the PR for `feat/I3-phone-link` if it is not open yet.

## Recommended Next Step

- Durvish: follow `docs/PHONE_DEMO.md` path C with your phone, Save run log, read `report.md`, then record the backup video and mark I3 done with that evidence
