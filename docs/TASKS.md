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

### [x] F0.3 Continuous integration
- **Branch:** `feat/F0.3-ci`
- **Owner:** Member A (after F0.1)
- **Owns:** `.github/workflows/`
- **Build:** GitHub Actions running Ruff, pytest, the inherited unittest suites, and frontend lint and build on every PR.
- **Done when:** CI is green on `main`.

---

## Phase 1: Core features (parallel)

### Track A

#### [x] A1 Concern Bank and merchant personas
- **Branch:** `feat/A1-concerns-personas`
- **Owns:** `data/concerns/`, `data/personas/`, `chanakya/brain/concern_bank.py`
- **Build:**
  - Concern Bank: 10–15 concerns (hidden charges, rental cost, setup hassle, existing competitor QR, settlement delay worry, trust in a phone caller, busy now, device reliability, language comfort, data privacy, not needed). Each has a description, example phrasings in Hindi, Hinglish, Punjabi and English, and resolve conditions linked to knowledge node IDs.
  - 40+ merchant personas: business type, city, language, patience, busyness, tech comfort, hidden concerns, willingness prior.
- **Done when:** loaders validate against core schemas; tests check every resolve condition points to an existing knowledge node.

#### [x] A2 Merchant twins (Twin-A and Twin-B)
- **Branch:** `feat/A2-twins`
- **Owns:** `chanakya/sim/`
- **Depends on:** A1
- **Build:**
  - Twin engine: persona plus hidden concerns, a willingness score, and patience. LLM generates the reply in character; a deterministic judge updates willingness (rises only when a hidden concern's resolve condition is met; falls on pressure, repetition, over-promising, ignored objections).
  - Walk-away rule and calibration target, for example 50–70% of untreated merchants decline or hang up.
  - Twin-A (fast model, used for planning) and Twin-B (different model family and held-out personas, used only for evaluation).
  - Adversarial personas: angry merchant, prompt-injection attempts, fake "Paytm staff" asking for OTP.
- **Done when:** fixed-seed runs are reproducible; calibration test shows a realistic walk-away rate.

#### [x] A3 Belief tracker and live concern meter feed
- **Branch:** `feat/A3-belief-tracker`
- **Owns:** `chanakya/brain/belief.py`, `chanakya/brain/cues.py`
- **Depends on:** A1
- **Build:**
  - LLM evidence scorer: for each utterance, likelihood of each concern.
  - Hesitation cues from transcript timing: pause before answer, fillers, speech rate.
  - Bayesian update with decay; emits `BeliefUpdated` events.
- **Done when:** unit tests on scripted utterances move the right concern to the top; latency per update is logged.

#### [x] A4 Move library and baseline planner
- **Branch:** `feat/A4-moves-baseline-planner`
- **Owns:** `chanakya/brain/moves.py`, `chanakya/brain/planner_rules.py`
- **Depends on:** A3
- **Build:**
  - Move types from IDEA 3.4 with preconditions (for example `CONFIRM_CONSENT` before any write move; `DISCLOSE_AND_GREET` first).
  - Rule-and-belief baseline planner: picks a move from belief and mission goal. This is the fallback for the look-ahead planner.
- **Done when:** precondition tests pass; planner never proposes a write without consent.

#### [x] A5 Realizer and agent integration
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

#### [x] B5 Backend API for missions, actions and hand-offs
- **Branch:** `feat/B5-api`
- **Owns:** `chanakya/missions/api.py`, `chanakya/actions/api.py`, `chanakya/humans/api.py` (registered in `backend/main.py` with one appended line each)
- **Depends on:** B2, B3, B4
- **Build:** REST endpoints and a WebSocket stream of ledger events for the dashboard.
- **Done when:** API tests pass; events stream to a test client.

---

## Phase 2: Differentiators (parallel)

### Track A

#### [x] A6 Look-ahead planner (NRPA with Twin-A)
- **Branch:** `feat/A6-lookahead-planner`
- **Owns:** `chanakya/brain/planner_nrpa.py`
- **Depends on:** A2, A4
- **Build:**
  - Candidates: top 3–4 moves (forest prior when available, otherwise baseline planner ranking).
  - Sample merchants from the belief; roll out 2 turns against Twin-A; NRPA level ≤ 2; score = expected willingness gain minus penalties (over-promise, policy risk, call time).
  - `ESCALATE` and `END_CALL_POLITELY` scored like other moves.
  - Strict time budget with fallback; emits `PlanComputed` events including the search tree for the dashboard.
- **Done when:** beats the baseline planner on a fixed Twin-A set; stays inside the time budget.

#### [x] A7 Planning while listening
- **Branch:** `feat/A7-plan-while-listening`
- **Owns:** `backend/` voice session planning hook, `chanakya/brain/speculative.py`
- **Depends on:** A6
- **Build:** start planning on partial transcripts; refine on the final transcript; cancel stale plans; allow only read-only tool lookups before the merchant finishes.
- **Done when:** measured p50/p90 turn latency is logged and compared with planning after speech.

#### [x] A8 Evaluation harness
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

#### [x] B7 Scheduler, follow-ups and verification
- **Branch:** `feat/B7-followups`
- **Owns:** `chanakya/missions/scheduler.py`, `chanakya/missions/verifier.py`
- **Depends on:** B1, B3
- **Build:** APScheduler jobs for verification checks and follow-ups (WhatsApp nudge, callback); simulated clock for demos and tests; mission closes DONE only when the system confirms the outcome.
- **Done when:** an end-to-end test drives a mission from link sent to onboarding complete using the simulated clock.

#### [x] B8 Mission Control dashboard
- **Branch:** `feat/B8-mission-control`
- **Owns:** `frontend/src/app/missions/`, `frontend/src/components/missions/`
- **Depends on:** B5
- **Build:** mission list with states and priorities, mission detail with the ledger timeline, signals feed, hand-off queue, approval buttons. Mock systems clearly labelled.
- **Done when:** a seeded demo shows missions moving live.

#### [x] B9 Live Call View
- **Branch:** `feat/B9-live-call-view`
- **Owns:** `frontend/src/app/call/`, `frontend/src/components/call/`
- **Depends on:** B5 (consumes `BeliefUpdated`, `PlanComputed`, `ActionDecision` events)
- **Build:** split screen: transcript and audio on the left; concern meter, look-ahead tree, willingness curve and action log on the right.
- **Done when:** renders from recorded event fixtures and from a live call.

#### [x] B14 Mock product page and mock onboarding page
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

#### [x] A10 Adversarial and safety suite
- **Branch:** `feat/A10-safety-suite`
- **Owns:** `chanakya/eval/safety/`
- **Depends on:** A8
- **Build:** scenarios for prompt injection, OTP phishing, pressure requests, invented-price bait, consent ambiguity ("haan"), distressed merchant; automatic checks for violations.
- **Done when:** report shows zero violations for Chanakya or lists each failure.

#### [x] A11 Coach mode engine
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

#### [x] B11 Coach mode UI
- **Branch:** `feat/B11-coach-ui`
- **Owns:** `frontend/src/app/coach/`
- **Depends on:** A11
- **Build:** telecaller view with live suggestion card, concern meter and hand-off card.
- **Done when:** works with the recorded human call fixture.

#### [x] B12 Manager insights
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

#### [x] I1 End-to-end demo scenarios
- **Branch:** `feat/I1-demo-scenarios`
- **Build:** seeded scripts for the demo storyline in IDEA section 8: offline Soundbox service mission, card-machine sale with concern resolution and WhatsApp link, follow-up to DONE, distressed-merchant hand-off.
- **Done when:** each scenario runs from one command and from the dashboard.

#### [x] I2 Full evaluation run and results
- **Branch:** `feat/I2-results`
- **Build:** run the harness on all variants; save results, report and charts in `docs/results/` with commands and seeds.

#### [ ] I3 Phone demo hardening
- **Branch:** `feat/I3-phone-demo`
- **Build:** Twilio path tested with the allowlisted number; fallbacks for network failures; recorded backup video.

#### [x] I4 README, architecture diagram and pitch assets
- **Branch:** `docs/I4-readme`
- **Build:** final README, architecture image, screenshots, measured numbers for the deck.

---

## Phase 5: Neural brain (Gurnoor and Durvish)

Three learned parts replace the brain's hand-written guesses.
- **Settings:** each one is chosen by a setting in `chanakya/core/config.py`, added in its own small `core:` PR (the `WORRY_SCORER` pattern, #26). The default keeps today's behaviour.
- **Measurement:** each is measured against what it replaces on data it never saw, and every number goes in `docs/results/` with its command and seed.
- **Safety:** the safety rules (disclosure, distress, a no, sensitive data) stay hand-written and are never learned.

One owner per neural network does all of it (data, model, wiring, measurement); the other reviews.

| Task | What it replaces | Setting | Owner |
|---|---|---|---|
| N1 worry scorer | keyword evidence in the belief tracker | `WORRY_SCORER=lexical\|llm\|embedding` (merged, #26) | Gurnoor |
| N2 semantic memory | the Strategy Forest's trigram vectors and 24 clusters | `PLANNER_MEMORY=forest\|neural` | Durvish |
| N3 planner value network | the planner's `0.8 × consent_chance` horizon guess | `PLANNER_VALUE=formula\|network` | Durvish |
| N4 demo screens | | | Gurnoor |

**Shared code goes through its owner:**
- **Gurnoor's:** `chanakya/neural/` (encoder, worry head, scorer, data scripts), `data/neural/worry_*` and the lines voice in `chanakya/sim/voice.py`.
- **Durvish's:** `chanakya/brain/forest/`, `chanakya/brain/memory/`, `chanakya/brain/value/` and `chanakya/brain/planner_nrpa.py`.

**Shared rules for all three:**
- **Encoder:** `intfloat/multilingual-e5-small` through ONNX Runtime with the `query: ` prefix, about 2.5 ms per line.
- **Downloads and weights:** the encoder is downloaded once with `python -m chanakya.neural.encoder --download` and never committed. Trained heads (`.npz`, under 1 MB) are committed with seed, date and data hash.
- **Dependencies:** `numpy` is in `requirements.txt`. The encoder libraries are optional, in `requirements-neural.txt`: `onnxruntime`, `tokenizers` and `huggingface_hub`, no PyTorch.
- **Tests:** tests use `FakeEncoder` or stubs and never download a model. A test that needs the real model is skipped when it is missing.
- **Simulated merchants:** training data and memory come only from the train split and planning personas. Evaluation uses the test split, evaluation personas and the hand-written set.

#### [x] N0 Baselines and labelled data
- **Branch:** `feat/N0-neural-baseline` (merged, #24)
- **Owns:** `chanakya/neural/`, `data/neural/`, `docs/results/neural-baseline/`
- **Build:** labelled merchant lines in four languages from two model families (train from the Twin-A model, test from the Twin-B model, nothing close to a Concern Bank phrasing); baselines for today's lexical scorer, the LLM scorer and two candidate encoders; the encoder choice.
- **Done when:** baselines and the encoder choice are in `docs/results/neural-baseline/` with the command that produced them.

#### [ ] N1 Neural worry scorer (Gurnoor)
- **Branch:** `feat/N1-worry-scorer`
- **Owns:** `chanakya/neural/`, `data/neural/worry_*`, `docs/results/neural-worry-scorer/`; wiring in `chanakya/brain/belief.py`, `agent/brain_agent.py`, `chanakya/humans/coach_api.py`, `chanakya/eval/variants.py`, `chanakya/sim/voice.py`, `chanakya/eval/harness.py`
- **Depends on:** N0
- **Built so far:**
  - **Setting:** `WORRY_SCORER` (#26).
  - **Encoder:** the ONNX encoder, which gives identical vectors to the PyTorch model.
  - **Head:** a numpy network with 13 independent sigmoid outputs and one hidden layer, trained with Adam, stopped early and temperature-calibrated on a seeded 15% validation split.
  - **Scorer:** `EmbeddingScorer`, which exposes `base_rates`, and `select_scorer`. With `WORRY_SCORER` unset it keeps today's default: the LLM scorer when an LLM is configured, else lexical.
  - **Training script:** `python -m chanakya.neural.train_worry --seed 7`.
  - **Hand-written set:** the file `data/neural/worry_lines_human.csv` (still empty), its guide in `data/neural/README.md`, and its checker.
  - **First results** on N0's test split (14 labels): lexical 0.394, embedding 0.536, LLM 0.777. Validation calibration error is 0.0049 after temperature scaling.
  - **Fine-tuning finding:** fine-tuning the whole encoder raised validation (0.72) but not test (0.55). It learned the training model's style, so the next lever is training data from more model families.
- **To do:**
  1. **More training lines** from at least two more model families (for example Mistral and one other), kept out of the test family (OpenAI), with N0's test split unchanged; then retrain.
  2. **Belief tracker:** when the scorer has `base_rates`, likelihood = odds(p) / odds(base rate) x hesitation boost, without `EPSILON` or `SHARPNESS`. The lexical and LLM paths are unchanged.
  3. **Wiring:** `select_scorer(configured_worry_scorer(), ...)` in `agent/brain_agent.py` and `chanakya/humans/coach_api.py`, plus a `chanakya_embedding` variant that never quietly falls back to lexical.
  4. **A lines voice for twins** in `chanakya/sim/voice.py`: it speaks lines from a chosen split of `data/neural/worry_lines.jsonl` for each voiced worry, in the persona's language. N1 and N2 evaluate with the test split, and N2 builds its memory with the train split. The harness gets a `--voice` option.
  5. **Belief top-1 accuracy** as a harness metric: the belief's top worry is one the twin holds.
  6. **Hand-written test set,** written by hand by Gurnoor, never by an LLM. Never used for training, tuning or calibration. About 150 lines (about 40 per slice: romanized Hinglish, negations, no-worry lines, Punjabi) is the minimum, and 300 is better.
  7. **Citation:** the e5 report (Wang et al., 2024, https://arxiv.org/abs/2402.05672) goes into `docs/IDEA.md` section 9.
  8. **`NEURAL=1 ./init.sh`:** installs `requirements-neural.txt`, checks the encoder and the hand-written set, and runs the tests that need the real model.
- **Done when**, with every number in `docs/results/neural-worry-scorer/`:
  - **Per-line accuracy,** embedding vs lexical vs LLM, on the hand-written set (overall and per slice) and on N0's test split. The embedding scorer beats lexical overall.
  - **Calibration error** before and after temperature scaling.
  - **Full calls:** consent rate and belief top-1 accuracy with the test-split voice, per scorer, seeds 7 and 13.
  - **Speed:** p50 and p90 ms per turn, with a target under 10 ms.
  - **CI** is unchanged apart from numpy.

#### [x] N2 Semantic memory (Durvish)
- **Branch:** `feat/N2-semantic-memory`
- **Owns:** `chanakya/brain/forest/`, `chanakya/brain/memory/`, `data/neural/memory*`, `docs/results/neural-memory/`
- **Depends on:** the N1 encoder and lines voice (on `feat/N1-worry-scorer` until N1 merges)
- **Build:**
  - **Setting:** `PLANNER_MEMORY=forest|neural` (a `core:` PR).
  - **Representation:** each remembered moment is the e5 embedding of the merchant line plus the belief vector. The k nearest past moments are looked up instead of 24 fixed clusters. The Wilson-scored move values and the planner's `forest.moves_for(state)` hook stay.
  - **Data:** the memory is built from transcripts regenerated with the lines voice on the train split, not the 82 template sentences.
  - **Optional:** a small learned projection (contrastive or triplet loss, numpy) that pulls together moments where the same move succeeded, reported as its own row.
- **Done when:**
  - **Win rate** for no memory (`chanakya`), the trigram forest (`chanakya_forest`) and neural memory (`chanakya_memory`) is measured with the test-split voice over seeds 7 and 13, with lookup p50 and p90 ms, and reported either way.
  - **Tests** use `FakeEncoder`.

#### [x] N3 Value network for the planner (Durvish)
- **Branch:** `feat/N3-value-network`
- **Owns:** `chanakya/brain/value/`, `data/neural/value_net.npz`, `docs/results/neural-value-network/`, a `leaf_value` hook in `chanakya/brain/planner_nrpa.py`
- **Depends on:** nothing to start (numpy arrives with N1)
- **Build:**
  - **Setting:** `PLANNER_VALUE=formula|network` (a `core:` PR).
  - **Self-play data:** the current planner against Twin-A on planning personas only, seeded, a few thousand calls. At every leaf where `outcome()` would apply the formula, record what is known there (the simulated twin state, the agent's consent asks and last move, the belief's top probabilities) and how the call actually ended when played to the end.
  - **Network:** a small numpy network trained on that data. The weights are saved with seed, date and data hash.
  - **Hook:** `NRPAPlanner` takes a `leaf_value` function, and there is a `chanakya_value` variant.
  - **Optional:** a second self-play round with the network-guided planner (AlphaZero-lite), and a policy prior for candidate order.
- **Done when:**
  - **On held-out evaluation personas over seeds 7 and 13:** success, walk-away rate, turns to close and planner p50 and p90 ms, for formula vs network.
  - **Planner checks:** `python -m chanakya.eval.planner_checks stability` and `lookahead` with and without the network.
  - **Safety test:** the forced safety rules always decide before the network.

#### [ ] N4 Show the neural brain (Gurnoor)
- **Branch:** `feat/N4-neural-demo`
- **Owns:** the Live Call View, coach mode, `docs/architecture.svg`, README
- **Depends on:** N1, N2, N3
- **Build:** the Live Call View and coach mode show the neural scorer's evidence and the value estimate; the architecture diagram and README are updated with measured numbers only.
- **Done when:** `./init.sh`, `NEURAL=1 ./init.sh`, the demo scenarios and the end-to-end script pass with every neural setting on.

---

## Phase 6: Review fixes, win-back missions and a permission-first opening (Durvish)

Durvish owns every task in this phase. Some of them edit Track B directories (`chanakya/missions/`, `chanakya/actions/`, `frontend/`); those PRs say so and ask for Gurnoor's review. `chanakya/core/` changes go in their own `core:` PR (W0). The neural work (N1-N4) owns `chanakya/brain/belief.py`, `chanakya/sim/voice.py`, `chanakya/eval/variants.py`, `agent/brain_agent.py` and `chanakya/humans/coach_engine.py`; this phase avoids those files, and any unavoidable edit is small, additive and noted in `progress.md`. New behaviour sits behind `WINBACK_ENABLED` and `PERMISSION_FIRST_ENABLED`, both off by default. Win-back calls never mention or promise an offer, discount or waiver: `data/knowledge/Paytm_Products.json` does not establish promotional offers.

#### [x] F1 Review fixes from PR #19
- **Branch:** `fix/I1-review-fixes`
- **Owner:** Durvish Khurana (Track B parts reviewed by Gurnoor)
- **Owns:** `chanakya/brain/calls_api.py`, `chanakya/brain/mission_call.py`, `chanakya/brain/scenarios.py`, `chanakya/brain/core_adapters.py`, `chanakya/brain/realizer.py`, `chanakya/brain/planner_rules.py`, `chanakya/brain/contracts/schemas.py`, `chanakya/brain/tests/`, `chanakya/missions/verifier.py`, `chanakya/missions/tests/`, `chanakya/actions/systems/tools.py`, `chanakya/actions/tests/`, `frontend/src/app/call/`, `scripts/demo/e2e_track_b.py`
- **Depends on:** I1
- **Build:** every point of Gurnoor's review on #19, each with a test that fails before the fix:
  1. A running scenario's call is registered; `POST /api/calls/{id}/say` and `/api/calls/{id}/voice` refuse with 409 while it runs; the Live Call View hides "Speak as the merchant" and "Talk by voice instead" meanwhile.
  2. A yes to the onboarding link covers the link and a new mock `send_onboarding_reminder` tool only (fixed reminder template for an existing onboarding session, no free text). The verifier sends reminders through it; any `send_summary` needs its own explicit consent.
  3. The callback scenario never moves the shared clock: it runs only its own mission's verification jobs.
  4. One `asyncio.Lock` per `MissionCall`; the ledger writes, `sync()` and `_after()` of a turn are shielded from cancellation when the merchant talks over Chanakya.
  5. Every decline is recorded; "no, then yes, then no" ends declined and closes the mission even past `IN_CONVERSATION`.
  6. The onboarding link's product is the one the brain recommended before the consent, falling back to the mission card.
  7. The close outcome comes from a typed `Move.end_reason`, not from the planner's free text.
  8. The inverse of `SPEAKERS` is a module-level constant.
- **Done when:** a second call during a running scenario is rejected and the ledger has exactly one `ai_disclosed` event; a link consent never lets `send_summary` through; after the callback scenario the clock offset is unchanged and other missions' reminders did not fire; a cancelled turn still writes its escalation or close; "no, yes, no" ends `CLOSED_NOT_INTERESTED` from `AWAITING_CONFIRMATION`; the link carries the recommended product; `./init.sh` and `FULL=1 ./init.sh` pass.

#### [x] W0 Shared contracts for win-back and permission-first
- **Branch:** `core/winback-contracts` (PR titled `core: ...`)
- **Owner:** Durvish Khurana (reviewed by Gurnoor before merge)
- **Owns:** `chanakya/core/`, `chanakya/brain/contracts/schemas.py`, `chanakya/brain/core_adapters.py`, `chanakya/brain/planner_rules.py`, `chanakya/brain/forest/generate.py`, `chanakya/brain/tests/`, `data/concerns/priors.json`, `chanakya/missions/intake.py`, `chanakya/missions/tests/`, `chanakya/actions/gate.py`, `chanakya/actions/systems/db.py`, `chanakya/actions/systems/seed.py` (insert by column name), `chanakya/actions/tests/`, `chanakya/core/tests/`, `frontend/src/lib/missionView.mjs`, `frontend/src/lib/coachView.mjs`, `frontend/src/components/call/CallView.js`, `.env.example`, `README.md`
- **Depends on:** F0.2, A1, B6
- **Build:**
  - Core: `SignalKind.MERCHANT_CHURNED`, `MissionType.WIN_BACK`, `Merchant.relationship` (`customer`, `prospect` or `former`, default `customer`) and `Merchant.churned_at`, `EventKind.LEAVING_REASON_RECORDED` and `EventKind.HOLDOUT_ASSIGNED`, `MoveType.ASK_PERMISSION`; flags `WINBACK_ENABLED` and `PERMISSION_FIRST_ENABLED`, default off.
  - Brain contracts: `TriggerType.MERCHANT_CHURNED` on the data door, `MissionKind.WIN_BACK`, `MoveType.ASK_PERMISSION` and the same two `Merchant` fields (both models forbid extra fields, so they must match).
  - `core_adapters.py` maps the new trigger and carries the merchant fields; a prior for `merchant_churned` over existing concerns only; an intake rule for the new signal; the mock merchants table gains the two columns (with a migration for existing databases); every lookup keyed by trigger, signal or mission type gets the new value.
- **Done when:** both merchant models round-trip through the adapters with the new fields; `concern_bank.validate()` passes; intake builds a win-back card for `MERCHANT_CHURNED`; both flags default off; `./init.sh` passes.

#### [x] W1 Churn detection, holdout and the win-back DONE check
- **Branch:** `feat/W1-winback-missions`
- **Owner:** Durvish Khurana (Track B directories, reviewed by Gurnoor)
- **Owns:** `chanakya/actions/systems/seed.py`, `chanakya/actions/systems/tools.py`, `chanakya/missions/churn.py`, `chanakya/missions/verifier.py`, `chanakya/missions/runtime.py`, `chanakya/missions/api.py`, `chanakya/missions/demo_api.py`, `chanakya/missions/tests/`, `frontend/src/app/missions/`, `frontend/src/lib/`
- **Depends on:** W0, F1
- **Build:**
  - Three or four fictional former merchants in the seed (device returned or last payment over 60 days ago, `relationship="former"`, a `churned_at` date), at least one with an open ticket and one with a delayed settlement; the existing demo merchants unchanged.
  - `chanakya/missions/churn.py` reads the mock tables and raises `MERCHANT_CHURNED` signals for merchants who churned 14 to 180 days ago, are not on do-not-call and had no win-back mission in the last 90 days. An unresolved complaint ticket gets a hand-off card for a person instead of an AI call. Runs only with `WINBACK_ENABLED`.
  - Holdout: 20% of eligible merchants by a seeded hash of the merchant id, never called, recorded as `HOLDOUT_ASSIGNED` in the ledger and shown in Mission Control as "holdout (not called)"; a fixed demo seed.
  - A win-back mission is DONE only when a system confirms it: the ticket raised on the call is resolved, the device is active again, or a payment arrives within 14 days of the call. Until then the verifier's existing re-check and callback limits apply.
  - A reasons-for-leaving card in Mission Control: counts of recorded leaving reasons by reason, city and product, read from the ledger. B12 should reuse it.
- **Done when:** tests cover the eligibility edges, a deterministic holdout for a given seed, each DONE path and no DONE without system confirmation, do-not-call and open-ticket routing; `FULL=1 ./init.sh` passes.

#### [x] W2 The win-back conversation
- **Branch:** `feat/W2-winback-brain`
- **Owner:** Durvish Khurana
- **Owns:** `chanakya/brain/moves.py`, `chanakya/brain/planner_rules.py`, `chanakya/brain/planner_nrpa.py`, `chanakya/brain/realizer.py`, `chanakya/brain/mission_call.py`, `chanakya/brain/scenarios.py`, `chanakya/brain/contracts/schemas.py`, `chanakya/brain/tests/`, `chanakya/sim/judge.py`, `chanakya/sim/tests/`, `chanakya/eval/winback.py`, `chanakya/eval/tests/`, `chanakya/brain/concern_bank.py` (former personas kept out of sales evaluations), `chanakya/brain/calls_api.py`, `scripts/demo/`, `data/personas/`, `docs/results/winback/`, `README.md`; one additive branch in `agent/brain_agent.py` so a planned read (settlement status) runs through the gate
- **Depends on:** W1
- **Build:**
  - Listen first: after the AI disclosure Chanakya says it is calling because they used the product before, then asks why they stopped. No pitch until the belief has a clear top reason or two probes were used. The 13 Concern Bank worries are the reasons.
  - Act on the reason, as planner rules and move preconditions so the NRPA planner respects them: `device_issue` gets `raise_ticket` with explicit consent; `settlement_delay` gets `get_settlement_status` (a read) and only what the mock system returns; `rental_cost`, `hidden_charges` and `per_swipe_charges` are answered only from the sourced pages, never with a number or an offer; `competitor_qr` is answered once, then their choice is accepted; `not_needed` and `customers_pay_cash` end the call politely with no pitch and no follow-up; `just_busy` gets a callback; distress, a request for a person and a decline behave as today.
  - The final top reason is written to the ledger as `LEAVING_REASON_RECORDED` (not through `log_interaction`, which is a consented write).
  - Seeded former-customer personas with a hidden leaving reason in both the planning and evaluation splits; the twins understand the win-back trigger.
  - Scenarios `winback_device_fix` (ticket raised, resolved by the mock system, DONE) and `winback_not_needed` (polite close, no pitch, no action).
- **Done when:** on evaluation personas with seeds 7 and 13 the offline harness reports how often the belief's top reason matches the twin's hidden reason, the fix rate for fixable reasons, zero pitches and zero writes when the reason is `not_needed`, and zero safety violations, all in `docs/results/winback/` with the commands; both scenarios pass; `./init.sh` passes.

#### [x] P1 Permission-first opening for the lead-list door
- **Branch:** `feat/P1-permission-first`
- **Owner:** Durvish Khurana
- **Owns:** `chanakya/brain/moves.py`, `chanakya/brain/planner_rules.py`, `chanakya/brain/planner_nrpa.py`, `chanakya/brain/realizer.py`, `chanakya/brain/mission_call.py`, `chanakya/brain/core_adapters.py`, `chanakya/brain/contracts/schemas.py`, `chanakya/brain/tests/`, `chanakya/eval/safety/`, `docs/results/permission-first/`, `README.md`
- **Depends on:** W0
- **Build:**
  - An `ASK_PERMISSION` move: after the AI disclosure, Chanakya says who it is, why it is calling, and asks if they have two minutes. Only for `LEAD_LIST_ASSIGNED` missions with `PERMISSION_FIRST_ENABLED` on.
  - `RECOMMEND`, `CONFIRM_CONSENT` and `TAKE_ACTION` are not allowed until a clear yes to that question; enforced in the move preconditions, so the NRPA planner cannot skip it.
  - A no ends the call politely and is recorded as a decline; "busy, call later" schedules a callback; a short "haan" or "hmm" after a long pause is not permission (the deflection rule in `cues.py`).
  - Templates for the question in Hindi, Hinglish, Punjabi and English, with no em dash; the LLM realizer falls back to them when its line breaks a rule.
- **Done when:** tests in `chanakya/brain/tests/` show no pitch, consent question or action before a clear yes, a no closes the call as declined, busy schedules a callback and a deflected "haan" is not permission; the safety suite has pitch-before-permission bait, "haan" as deflection and a no, with zero violations offline; `./init.sh` passes.

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

Phase 5: N0 ─┬─ N1 ─┬─ N2 ─┐
             │      └──────┼─ N4
             └─ N3 ────────┘

Phase 6:  I1 ── F1 ──┐
          W0 ────────┴─ W1 ── W2
          W0 ── P1
```
