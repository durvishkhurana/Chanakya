# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Track A and Track B are merged on `main` (#15-#17), and B11 coach mode (#18). I1 demo scenarios is done on `feat/I1-demo-scenarios` and waits for review; A9 and F0.3 are in progress
- Branch / commit: `feat/I1-demo-scenarios`, cut from `main` at `844da64`, with `main` at `688086c` (B11) merged in

## Completed This Session

- [x] Adapter event payloads are exactly the core models (`BeliefState`, `PlanResult`, `Turn`), so the gate, hand-off cards and the Live Call View parse them
- [x] `chanakya/brain/mission_call.py`: `MissionCall` runs the brain on a real mission (ledger events, disclosure and consent records, Track B's `ActionGate`, hand-off on distress, close on a clear no)
- [x] `chanakya/brain/scenarios.py`, `scripts/demo/scenarios.py`: the four IDEA section 8 scenarios from one command
- [x] `chanakya/brain/calls_api.py` (`/api/calls`, mounted with the mission APIs): run a scenario, speak as the merchant; dashboard controls in Mission Control and the Live Call View
- [x] The onboarding-link consent question also asks about a reminder; the consent is recorded for `send_onboarding_link` and `send_summary` so the verifier's WhatsApp reminder passes the gate

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Full check | `FULL=1 SKIP_INSTALL=1 ./init.sh` | agent 104 OK, backend 98 OK, pytest 281 passed, Ruff clean, frontend 22 pass, lint clean, build compiled | build needs network for Google Fonts |
| Scenarios | `python scripts/demo/scenarios.py` | 4/4 passed | offline templates, SimClock at 15:00 IST |
| Live backend | `MISSIONS_ENABLED=true CALLING_HOURS=0-24` + `POST /api/calls/scenarios/<name>` | DONE, DONE, AWAITING_CONFIRMATION, ESCALATED | Groq realizer |
| Dashboard | "Run scenario" in `/missions`, "Speak as the merchant" on `/call/<id>` | call opened and played live; typed turns filled every panel | browser check |

## Files Changed

- `chanakya/brain/`: `core_adapters.py`, `realizer.py` (link consent and technician wording), new `mission_call.py`, `scenarios.py`, `calls_api.py`, tests in `tests/test_core_adapters.py`, `tests/test_scenarios.py`
- `scripts/demo/scenarios.py`
- Shared: `backend/main.py` (appended `calls_router` mount), `frontend/src/app/missions/page.js`, `frontend/src/app/call/[missionId]/page.js` (Track B pages; tell Gurnoor)
- Docs: `README.md`, `docs/TASKS.md` (I1 ticked), `feature_list.json`, `progress.md`, this file

## Decisions Made

- Scenario merchants are scripted but react to Chanakya's actual moves (worry when asked, explicit yes only to a consent question), so the real planner drives each call
- `POST /api/calls/scenarios/<name>` refuses (409) when the merchant already has a mission past SCHEDULED, so a scenario never takes over a call in progress

## Blockers / Risks

- The NRPA planner's choice varies with its seed (Gurnoor, B11; see `progress.md`, Blockers); Track A (A6) to look at
- Voice calls (`/ws/voice`) are not yet tied to a mission; only text calls and scenarios reach the Live Call View
- The callback scenario fast-forwards the shared demo clock by a day on a live backend
- OpenRouter has no credits; Groq's free tier rate limits make full online evaluations impossible
- `gh` cannot be installed on this machine (downloads reset); PRs are opened in the browser

## Next Session Startup

1. Read `CLAUDE.md`.
2. Read `feature_list.json` and `progress.md`.
3. Review this handoff.
4. Run `./init.sh` before editing.

## Recommended Next Step

- After the I1 review: give `/ws/voice` an optional `mission_id` that runs through `MissionCall`, so spoken calls show live in the Live Call View; then I3 phone demo hardening
