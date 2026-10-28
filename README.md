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

The Chanakya brain (belief tracker, Strategy Forest, look-ahead planner), missions, actions, merchant twins and evaluation are being added task by task.

## Run locally

Requires Python 3.12 and Node.js 20 or newer.

1. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` and `SARVAM_API_KEY`. While OpenRouter is unavailable, the voice agent and the Chanakya modules can use Groq: set `GROQ_API_KEY` and leave `OPENROUTER_API_KEY` empty (or set `LLM_PROVIDER=groq`). The decisions and Jev retrieval modes still need their own keys.
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

### Feature flags

New Chanakya features are wired in behind flags in `.env`, all `false` by default: `PLANNER_ENABLED`, `ACTIONS_ENABLED`, `MISSIONS_ENABLED`, `COACH_ENABLED`. With `PLANNER_ENABLED=true` the voice call runs the planning brain (`agent/brain_agent.py`: belief tracker, planner, realizer); with it off, the original retrieval agent answers. Writes stay blocked unless `ACTIONS_ENABLED=true` and a safety gate is wired in. Shared contracts, the event bus, settings and the LLM client live in `chanakya/core/`; `chanakya/core/fakes.py` has in-memory fakes for tests.

### Evaluation

```bash
python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7   # deterministic, no network
python -m chanakya.eval.harness --mode online --merchants 3 --max-turns 6  # uses the configured LLM provider
python -m chanakya.sim.calibration                                         # twin walk-away calibration
python -m chanakya.eval.safety --mode offline                              # adversarial and safety suite (also --mode online)
```

Reports (JSON, Markdown, HTML) go to `.state/eval/<mode>-<seed>/` unless `--out` is given.

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
