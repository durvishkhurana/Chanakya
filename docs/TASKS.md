# Chanakya: features and work split

Two members work in parallel, each with their own coding session, on separate feature branches. The split is by **directory ownership**, so two branches never edit the same files. Modules talk only through the contracts in `chanakya/core`.

- **Track A, Conversation Brain and Simulation:** `chanakya/brain/`, `chanakya/sim/`, `chanakya/eval/`, `agent/`, `backend/` (voice), `data/concerns/`, `data/personas/`, `data/transcripts/`, `data/forest/`
- **Track B, Missions, Systems and Experience:** `chanakya/missions/`, `chanakya/actions/`, `chanakya/humans/`, `chanakya/insights/`, `frontend/`, `data/knowledge/`

Suggested owners: **Member A: Durvish Khurana**, **Member B: Gurnoor Singh Pannu**. Swap freely; keep tracks whole.

Rules for every task are in `CLAUDE.md`. Branch name format: `feat/<ID>-<slug>`.

---

## How to run two sessions without clashes

1. Phase 0 must merge first: it creates the repo skeleton and the shared contracts.
2. After that, each member takes the next unchecked task in their own track, in order.
3. Need something from the other track that is not merged yet? Code against the interface in `chanakya/core/interfaces.py` and use the fake in `chanakya/core/fakes.py`.
4. Contract changes go in a tiny separate `core:` PR, announced to the other member, merged before the feature that needs it.
5. Shared files (`requirements.txt`, `.env.example`, `backend/main.py` router list, `frontend/package.json`) accept appended lines only.
6. Rebase on `main` before every PR. Merge order inside a phase does not matter unless "Depends on" says so.
7. Integration tasks (Phase 4) are done together, one branch at a time.

---

## Phase 0: Foundation (merge before anything else)

### [x] F0.1 Repository bootstrap and import of the existing voice agent
- **Branch:** `feat/F0.1-bootstrap`
- **Owner:** Member A
- **Owns:** repo root, `backend/`, `agent/`, `frontend/`, `data/knowledge/`
- **Build:**
  - Import the existing voice-agent code: FastAPI backend, voice session, Sarvam STT/TTS, interruption classifier, Twilio transport, LangGraph agent, PageIndex retrieval, prompts, frontend, product knowledge JSON.
  - Exclude `.env`, `.venv`, `node_modules`, `.next`, `__pycache__`, `__MACOSX`, `.gstack`, logs.
  - Rename the assistant persona and product name to Chanakya in prompts, UI and README.
  - Move product knowledge to `data/knowledge/` and update the loader path.
  - `.gitignore`, `.env.example` (blank values), `README.md` with run instructions, `pyproject.toml` with Ruff config.
- **Done when:** backend starts, `/api/health` responds, the browser voice page loads, and the inherited unit tests pass.

### [x] F0.2 Shared contracts
- **Branch:** `feat/F0.2-core-contracts`
- **Owner:** Member B (reviewed by Member A before merge)
- **Owns:** `chanakya/core/`
- **Build:**
  - `schemas.py`: `Merchant`, `MerchantSignal`, `Mission`, `MissionState`, `MissionEvent`, `Concern`, `BeliefState`, `Move`, `MoveType`, `PlanResult`, `ToolCall`, `ToolResult`, `ActionDecision`, `HandoffCard`, `Turn`, `Transcript`.
  - `interfaces.py`: Protocols for `BeliefTracker`, `Planner`, `Realizer`, `ToolRegistry`, `SafetyGate`, `MissionStore`, `MerchantTwin`, `EventBus`.
  - `events.py`: in-process async event bus with typed events; every event persisted through `MissionStore`.
  - `config.py`: settings from env with feature flags (`PLANNER_ENABLED`, `ACTIONS_ENABLED`, `MISSIONS_ENABLED`, `COACH_ENABLED`), all default false.
  - `llm.py`: thin LLM client wrapper (OpenRouter) with model roles `main`, `rollout`, `twin_a`, `twin_b`, `judge`; injectable fake.
  - `fakes.py`: in-memory fakes for every interface, used by tests of both tracks.
- **Done when:** schemas round-trip to JSON, fakes satisfy the protocols, tests pass.

### [ ] F0.3 Continuous integration
- **Branch:** `feat/F0.3-ci`
- **Owner:** Member A (after F0.1)
- **Owns:** `.github/workflows/`
- **Build:** GitHub Actions running Ruff, pytest, the inherited unittest suites, and frontend lint and build on every PR.
- **Done when:** CI is green on `main`.

---

## Phase 1: Core features (parallel)

### Track A

#### [ ] A1 Concern Bank and merchant personas
- **Branch:** `feat/A1-concerns-personas`
- **Owns:** `data/concerns/`, `data/personas/`, `chanakya/brain/concern_bank.py`
- **Build:**
  - Concern Bank: 10–15 concerns (hidden charges, rental cost, setup hassle, existing competitor QR, settlement delay worry, trust in a phone caller, busy now, device reliability, language comfort, data privacy, not needed). Each has a description, example phrasings in Hindi, Hinglish, Punjabi and English, and resolve conditions linked to knowledge node IDs.
  - 40+ merchant personas: business type, city, language, patience, busyness, tech comfort, hidden concerns, willingness prior.
- **Done when:** loaders validate against core schemas; tests check every resolve condition points to an existing knowledge node.

#### [ ] A2 Merchant twins (Twin-A and Twin-B)
- **Branch:** `feat/A2-twins`
- **Owns:** `chanakya/sim/`
- **Depends on:** A1
- **Build:**
  - Twin engine: persona plus hidden concerns, a willingness score, and patience. LLM generates the reply in character; a deterministic judge updates willingness (rises only when a hidden concern's resolve condition is met; falls on pressure, repetition, over-promising, ignored objections).
  - Walk-away rule and calibration target, for example 50–70% of untreated merchants decline or hang up.
  - Twin-A (fast model, used for planning) and Twin-B (different model family and held-out personas, used only for evaluation).
  - Adversarial personas: angry merchant, prompt-injection attempts, fake "Paytm staff" asking for OTP.
- **Done when:** fixed-seed runs are reproducible; calibration test shows a realistic walk-away rate.

#### [ ] A3 Belief tracker and live concern meter feed
- **Branch:** `feat/A3-belief-tracker`
- **Owns:** `chanakya/brain/belief.py`, `chanakya/brain/cues.py`
- **Depends on:** A1
- **Build:**
  - LLM evidence scorer: for each utterance, likelihood of each concern.
  - Hesitation cues from transcript timing: pause before answer, fillers, speech rate.
  - Bayesian update with decay; emits `BeliefUpdated` events.
- **Done when:** unit tests on scripted utterances move the right concern to the top; latency per update is logged.

#### [ ] A4 Move library and baseline planner
- **Branch:** `feat/A4-moves-baseline-planner`
- **Owns:** `chanakya/brain/moves.py`, `chanakya/brain/planner_rules.py`
- **Depends on:** A3
- **Build:**
  - Move types from IDEA 3.4 with preconditions (for example `CONFIRM_CONSENT` before any write move; `DISCLOSE_AND_GREET` first).
  - Rule-and-belief baseline planner: picks a move from belief and mission goal. This is the fallback for the look-ahead planner.
- **Done when:** precondition tests pass; planner never proposes a write without consent.

#### [ ] A5 Realizer and agent integration
- **Branch:** `feat/A5-realizer`
- **Owns:** `chanakya/brain/realizer.py`, `agent/`, `backend/` voice session hook
- **Depends on:** A4
- **Build:**
  - Realizer turns a chosen move into speech in the merchant's language using the existing PageIndex retrieval and safety prompts.
  - Hook into the voice session behind `PLANNER_ENABLED`: transcript → belief → planner → realizer → TTS. With the flag off, behaviour is unchanged.
  - Emit `TurnCompleted` events with belief and chosen move.
- **Done when:** a browser call works with the flag on and off; existing voice tests still pass.

### Track B

#### [x] B1 Mock business systems and tool registry
- **Branch:** `feat/B1-mock-systems`
- **Owns:** `chanakya/actions/systems/`, `chanakya/actions/registry.py`
- **Build:**
  - SQLite-backed mocks: Intake, CRM, Messaging (WhatsApp/SMS outbox), Onboarding, Field ops, Devices, Ticketing, Settlements (read-only). Configurable failure rates and delays.
  - Typed tools from IDEA 3.7 with Pydantic argument schemas; registry with membership check.
  - Seed script that creates merchants, devices, settlements and orders matching the personas.
- **Done when:** every tool has a happy-path and failure-path test; unknown tool names are rejected.

#### [x] B2 Safety gate, policy graph and audit log
- **Branch:** `feat/B2-safety-gate`
- **Owns:** `chanakya/actions/gate.py`, `chanakya/actions/policy.py`, `chanakya/actions/audit.py`
- **Depends on:** B1
- **Build:**
  - Read/write classification per tool; writes require a consent event in the transcript.
  - Policy graph: consent, AI disclosure done, calling hours, do-not-call, suitability, no sensitive-data requests.
  - Pre-write reconsideration hook (calls a `Planner.reconsider` interface).
  - Every attempt, block and execution written as `ActionDecision` events.
- **Done when:** tests cover blocked writes without consent, blocked calls outside hours, and audit entries for each path.

#### [x] B3 Mission ledger and state machine
- **Branch:** `feat/B3-missions`
- **Owns:** `chanakya/missions/ledger.py`, `chanakya/missions/state.py`
- **Build:**
  - Mission store on SQLite; append-only events; state machine from IDEA 3.1 with allowed transitions.
  - Mission API: create, advance, attach turn, attach action, close.
- **Done when:** illegal transitions raise; a full mission can be replayed from its events.

#### [x] B4 Hand-off cards
- **Branch:** `feat/B4-handoff`
- **Owns:** `chanakya/humans/handoff.py`
- **Depends on:** B3
- **Build:** build a `HandoffCard` from the mission: merchant profile, top concerns, tried moves, actions, one-line LLM summary; human queue with claim/resolve.
- **Done when:** card generation tested on a recorded mission; queue endpoints work.

#### [ ] B5 Backend API for missions, actions and hand-offs
- **Branch:** `feat/B5-api`
- **Owns:** `chanakya/missions/api.py`, `chanakya/actions/api.py`, `chanakya/humans/api.py` (registered in `backend/main.py` with one appended line each)
- **Depends on:** B2, B3, B4
- **Build:** REST endpoints and a WebSocket stream of ledger events for the dashboard.
- **Done when:** API tests pass; events stream to a test client.

---

## Phase 2: Differentiators (parallel)

### Track A

#### [ ] A6 Look-ahead planner (NRPA with Twin-A)
- **Branch:** `feat/A6-lookahead-planner`
- **Owns:** `chanakya/brain/planner_nrpa.py`
- **Depends on:** A2, A4
- **Build:**
  - Candidates: top 3–4 moves (forest prior when available, otherwise baseline planner ranking).
  - Sample merchants from the belief; roll out 2 turns against Twin-A; NRPA level ≤ 2; score = expected willingness gain minus penalties (over-promise, policy risk, call time).
  - `ESCALATE` and `END_CALL_POLITELY` scored like other moves.
  - Strict time budget with fallback; emits `PlanComputed` events including the search tree for the dashboard.
- **Done when:** beats the baseline planner on a fixed Twin-A set; stays inside the time budget.

#### [ ] A7 Planning while listening
- **Branch:** `feat/A7-plan-while-listening`
- **Owns:** `backend/` voice session planning hook, `chanakya/brain/speculative.py`
- **Depends on:** A6
- **Build:** start planning on partial transcripts; refine on the final transcript; cancel stale plans; allow only read-only tool lookups before the merchant finishes.
- **Done when:** measured p50/p90 turn latency is logged and compared with planning after speech.

#### [ ] A8 Evaluation harness
- **Branch:** `feat/A8-eval-harness`
- **Owns:** `chanakya/eval/`
- **Depends on:** A2, B1 (uses fakes until B1 merges)
- **Build:**
  - Text-mode simulated calls between agent variants and Twin-B merchants (no audio), fixed seeds, parallel runs.
  - Variants: reactive baseline, actions only, Chanakya, Chanakya without belief.
  - Metrics from IDEA section 4; JSON results and a Markdown/HTML report with charts.
- **Done when:** one command produces a report on 100 Twin-B merchants plus the adversarial set.

### Track B

#### [x] B6 Mission intake: three doors, mission cards, priority queue
- **Branch:** `feat/B6-intake`
- **Owns:** `chanakya/missions/intake.py`, `chanakya/missions/queue.py`, `chanakya/missions/signals.py`
- **Depends on:** B3
- **Build:** the three doors from IDEA 3.2 (merchant raises a hand, data says so, human hands over); every signal becomes a mission card with goal, why-now reason, starting worries (priors over Concern Bank ids) and priority (chance x value); repeat signals refresh the open mission; do-not-call merchants are closed, never contacted; a queue ranks waiting missions and checks calling hours and the merchant's window; a simulated signal feed for the demo merchants.
- **Done when:** a callback request, a Door 2 signal and a Door 3 hand-over each open one mission card; duplicates update the existing mission; the queue orders by priority inside contact windows.

#### [ ] B7 Scheduler, follow-ups and verification
- **Branch:** `feat/B7-followups`
- **Owns:** `chanakya/missions/scheduler.py`, `chanakya/missions/verifier.py`
- **Depends on:** B1, B3
- **Build:** APScheduler jobs for verification checks and follow-ups (WhatsApp nudge, callback); simulated clock for demos and tests; mission closes DONE only when the system confirms the outcome.
- **Done when:** an end-to-end test drives a mission from link sent to onboarding complete using the simulated clock.

#### [ ] B8 Mission Control dashboard
- **Branch:** `feat/B8-mission-control`
- **Owns:** `frontend/src/app/missions/`, `frontend/src/components/missions/`
- **Depends on:** B5
- **Build:** mission list with states and priorities, mission detail with the ledger timeline, signals feed, hand-off queue, approval buttons. Mock systems clearly labelled.
- **Done when:** a seeded demo shows missions moving live.

#### [ ] B9 Live Call View
- **Branch:** `feat/B9-live-call-view`
- **Owns:** `frontend/src/app/call/`, `frontend/src/components/call/`
- **Depends on:** B5 (consumes `BeliefUpdated`, `PlanComputed`, `ActionDecision` events)
- **Build:** split screen: transcript and audio on the left; concern meter, look-ahead tree, willingness curve and action log on the right.
- **Done when:** renders from recorded event fixtures and from a live call.

#### [ ] B14 Mock product page and mock onboarding page
- **Branch:** `feat/B14-demo-pages`
- **Owns:** `frontend/src/app/demo/`, `chanakya/missions/demo_api.py`
- **Depends on:** B1, B5
- **Build:** a mock Soundbox page with "Request a callback" (opens a Door 1 mission) and a mock onboarding page at `/demo/onboard/<session>` (completing it updates the Onboarding system so the mission can verify DONE). Both clearly labelled as mocks.
- **Done when:** tapping the button opens a mission, and completing the form moves a mission waiting on onboarding to DONE.

---

## Phase 3: Depth (parallel)

### Track A

#### [ ] A9 Expert transcripts and Strategy Forest
- **Branch:** `feat/A9-strategy-forest`
- **Owns:** `data/transcripts/`, `data/forest/`, `chanakya/brain/forest/`
- **Depends on:** A1
- **Build:** generate expert-style transcripts (multilingual, labelled outcomes); embed and cluster states; record moves and outcomes; back-propagate values; Wilson lower bound; one-lookup retrieval of top moves; update from completed missions.
- **Done when:** forest lookup is under 50 ms and improves planner win rate over baseline candidates in eval.

#### [ ] A10 Adversarial and safety suite
- **Branch:** `feat/A10-safety-suite`
- **Owns:** `chanakya/eval/safety/`
- **Depends on:** A8
- **Build:** scenarios for prompt injection, OTP phishing, pressure requests, invented-price bait, consent ambiguity ("haan"), distressed merchant; automatic checks for violations.
- **Done when:** report shows zero violations for Chanakya or lists each failure.

#### [ ] A11 Coach mode engine
- **Branch:** `feat/A11-coach-engine`
- **Owns:** `chanakya/humans/coach_engine.py` (agreed exception: Track A owns this one file)
- **Depends on:** A6
- **Build:** run belief and planner on a human telecaller's live transcript; return the next best move with a one-line reason; never speaks.
- **Done when:** suggestions stream for a recorded human call.

### Track B

#### [ ] B10 Approval queue
- **Branch:** `feat/B10-approvals`
- **Owns:** `chanakya/humans/approvals.py`, frontend approval components
- **Depends on:** B2, B8
- **Build:** configurable high-risk actions pause for human approval; approve/reject from the dashboard; timeouts escalate.
- **Done when:** a high-risk action waits, is approved, then executes, all in the ledger.

#### [ ] B11 Coach mode UI
- **Branch:** `feat/B11-coach-ui`
- **Owns:** `frontend/src/app/coach/`
- **Depends on:** A11
- **Build:** telecaller view with live suggestion card, concern meter and hand-off card.
- **Done when:** works with the recorded human call fixture.

#### [ ] B12 Manager insights
- **Branch:** `feat/B12-insights`
- **Owns:** `chanakya/insights/`, `frontend/src/app/insights/`
- **Depends on:** B3
- **Build:** objection breakdown by product, language and time; mission funnels; best moves per concern; escalation reasons.
- **Done when:** charts render from a seeded ledger.

#### [ ] B13 Multi-channel messaging
- **Branch:** `feat/B13-messaging`
- **Owns:** `chanakya/actions/systems/messaging_channels.py`, frontend message preview
- **Depends on:** B1
- **Build:** WhatsApp-style and SMS templates per language; merchant replies in the simulated inbox feed back into the mission.
- **Done when:** a mission continues correctly after a simulated WhatsApp reply.

---

## Phase 4: Integration and demo (together, one branch at a time)

#### [ ] I1 End-to-end demo scenarios
- **Branch:** `feat/I1-demo-scenarios`
- **Build:** seeded scripts for the demo storyline in IDEA section 8: offline Soundbox service mission, card-machine sale with concern resolution and WhatsApp link, follow-up to DONE, distressed-merchant hand-off.
- **Done when:** each scenario runs from one command and from the dashboard.

#### [ ] I2 Full evaluation run and results
- **Branch:** `feat/I2-results`
- **Build:** run the harness on all variants; save results, report and charts in `docs/results/` with commands and seeds.

#### [ ] I3 Phone demo hardening
- **Branch:** `feat/I3-phone-demo`
- **Build:** Twilio path tested with the allowlisted number; fallbacks for network failures; recorded backup video.

#### [ ] I4 README, architecture diagram and pitch assets
- **Branch:** `docs/I4-readme`
- **Build:** final README, architecture image, screenshots, measured numbers for the deck.

---

## Dependency summary

```
F0.1 ─┬─ F0.3
F0.2 ─┤
      ├─ A1 ─┬─ A2 ─┬─ A6 ─┬─ A7
      │      │      │      └─ A11 ── B11
      │      ├─ A3 ─ A4 ─ A5
      │      └─ A9
      │      A8 (after A2) ── A10
      ├─ B1 ─┬─ B2 ─┬─ B10
      │      ├─ B7  │
      │      └─ B13 │
      ├─ B3 ─┬─ B4 ─┴─ B5 ─┬─ B8
      │      ├─ B6         └─ B9
      │      └─ B12
      └─ Phase 4 after both tracks
```
