# Chanakya

An AI merchant-success teammate for the Paytm AI Hackathon, Track 3: *"Build AI teammates that don't just respond; they get the job done."*

Chanakya takes in missions through three doors (a merchant raises a hand, the merchant's data says so, or a colleague hands the work over). It calls the merchant in their own language, works out what they are really worried about, plans its next move, takes safe actions across business systems, checks the outcome happened, and brings in a human only when that is the better move.

The full idea is in [docs/IDEA.md](docs/IDEA.md). Tasks and owners are in [docs/TASKS.md](docs/TASKS.md); live status is in [feature_list.json](feature_list.json).

> Independent project, not affiliated with Paytm. Paytm systems are represented by labelled mock services; product facts come from curated public Paytm for Business pages with source URLs and review dates.

## Status

This is the pilot. It contains the existing multilingual voice sales agent that Chanakya is built on:

- Streaming speech-to-text (Sarvam `saaras:v3-realtime`) with automatic language detection
- Streaming text-to-speech (Sarvam `bulbul:v3`)
- Interruption handling, conversation memory and inactivity check-ins
- LangGraph agent with multi-path PageIndex retrieval over `data/knowledge/`
- Browser voice client (Next.js) and Twilio Media Streams transport

On top of it, the teammate layer is in place (Track B):

- Mission intake through three doors, mission cards with starting worries, and a priority queue
- A mission ledger and state machine; every step is an event, and any mission can be replayed
- Typed tools on labelled mock business systems, behind a safety gate (AI disclosure, explicit consent, calling hours, do not call, no sensitive data, audit trail)
- Verification and reminders: a mission is done only when a system confirms it
- Handoff cards and a human queue
- Mission Control, the Live Call View, a mock product page, a mock onboarding page and the landing page

The Chanakya brain (belief tracker, Strategy Forest, look-ahead planner), merchant twins and evaluation are Track A and are being added task by task. See `progress.md`.

## Run locally

Requires Python 3.12 and Node.js 20 or newer.

1. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` and `SARVAM_API_KEY`. The Chanakya modules can use Groq instead: set `GROQ_API_KEY` (and `LLM_PROVIDER=groq` if both keys are present); `MODEL_<ROLE>` overrides a role's model.
2. Install and verify everything:

   ```bash
   ./init.sh
   ```

3. Start the backend:

   ```bash
   .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```

   On Windows, run `./init.sh` from Git Bash and use `.venv/Scripts/python.exe` in place of `.venv/bin/python`.

4. In a second terminal, start the frontend:

   ```bash
   cd frontend && npm run dev
   ```

5. Open http://localhost:3000 and select **Talk to Chanakya**. Microphone access requires localhost or HTTPS.

The backend starts without keys and reports missing configuration at `/api/health`. Keys stay on the server; never put them in `frontend/.env.local`.

### Optional telephone transport

Twilio is disabled by default. Set the `TWILIO_*` values in `.env` with a streaming-capable account, an HTTPS public backend origin and your own allowlisted number. Tests never place real calls.

```bash
.venv/bin/python -m backend.call_chanakya --help
```

### Missions and dashboards

The mission, action and handoff APIs are off by default. Turn them on in `.env`:

```bash
MISSIONS_ENABLED=true
CALLING_HOURS=0-24   # only for testing at night; the default is 9-21 Asia/Kolkata
```

Then, with the backend and frontend running:

| Page | What it shows |
|---|---|
| `/` | Landing page with the live "try a merchant's line" demo |
| `/demo/soundbox` | Mock product page: "Request a callback" opens a mission |
| `/missions` | Mission Control: queue, mission cards, concern meter, ledger, handoffs, demo clock |
| `/call/demo` | A scripted recorded call, played back event by event |
| `/call/<mission id>` | The live call view of a real mission |
| `/demo/onboard/<session>` | Mock onboarding page behind the SMS link |

State lives in `.state/` (ignored by git); delete it to start fresh. An end-to-end check of the whole flow against a running backend:

```bash
.venv/bin/python scripts/demo/e2e_track_b.py http://127.0.0.1:8000
```

### Feature flags

New Chanakya features are wired in behind flags in `.env`, all `false` by default: `PLANNER_ENABLED`, `ACTIONS_ENABLED`, `MISSIONS_ENABLED`, `COACH_ENABLED`. With `PLANNER_ENABLED=true` the voice call runs the planning brain (`agent/brain_agent.py`: belief tracker, look-ahead planner, realizer); with it off, the original retrieval agent answers. Writes stay blocked unless `ACTIONS_ENABLED=true` and a safety gate is wired in. `PLANNING_WHILE_LISTENING=true` also prepares the planner's next turn from partial transcripts; measure with `python -m chanakya.brain.speculative` (add `--live` for the configured provider). Shared contracts live in `chanakya/core/`; Track A's own brain, simulation and evaluation types are in `chanakya/brain/contracts/`.

### Evaluation

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7   # deterministic, no network
python -m chanakya.eval.harness --mode online --merchants 3 --max-turns 6  # uses the configured LLM provider
python -m chanakya.sim.calibration                                         # twin walk-away calibration
python -m chanakya.eval.safety --mode offline                              # adversarial and safety suite (also --mode online)
python -m chanakya.brain.forest.generate --seed 11                         # regenerate transcripts and the Strategy Forest
```

Reports (JSON, Markdown, HTML) go to `.state/eval/<mode>-<seed>/` unless `--out` is given. Measured results, with their commands and seeds, are in [docs/results/](docs/results/README.md).

## Verify

```bash
./init.sh                # Python unit tests, pytest, Ruff, frontend tests and lint
FULL=1 ./init.sh         # also the frontend production build
SKIP_INSTALL=1 ./init.sh # skip dependency installation
```

## Repository layout

```
backend/          FastAPI app, voice session, Sarvam and Twilio transports
agent/            LangGraph agent, PageIndex retrieval, prompts
frontend/         Next.js voice client and dashboards
data/knowledge/   sourced product knowledge (PageIndex JSON)
chanakya/         brain, missions, actions, humans, sim, eval (being added)
docs/             IDEA.md, TASKS.md, PROMPT.md
```

## Working on this repo

Read [CLAUDE.md](CLAUDE.md) first: ownership rules, branch naming, safety rules, the session workflow and the definition of done. Every session starts with `progress.md`, `session-handoff.md` and `./init.sh`.
