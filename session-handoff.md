# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Track B is merged on `main`. Track A (A1-A8, A10, A11) and the I2 results are complete on `feat/track-a-on-main`, ported onto main's `chanakya/core`; A9 and F0.3 are in progress
- Branch / commit: `feat/track-a-on-main`, cut from `feat/core-llm-providers`, which is cut from `main` at `007f2a1` (after PR #14)

## Completed This Session

- [x] `fix/windows-dev-setup`: `init.sh` works in Git Bash on Windows (real Python 3.12, `.venv/Scripts`), `uvloop` skipped and `tzdata` installed on Windows
- [x] `feat/core-llm-providers` (core change): the core LLM client supports Groq, JSON mode, seeds and rate-limit retries; OpenRouter behaviour unchanged
- [x] `feat/track-a-on-main`: A1, A2, A3, A4, A5, A6, A7, A8, A10, A11, I2, CI workflow (F0.3), Groq for the voice agent

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Python unit tests | `./init.sh` steps | agent and backend suites OK | inherited suites plus BrainAgent, provider and speculation tests |
| pytest | `python -m pytest` | 265 passed | Track A and Track B together |
| Lint | `python -m ruff check .` | All checks passed | |
| Frontend | `npm test`, `npm run lint`, `npm run build` | 19 pass, lint clean, build compiled | build needs network for Google Fonts |
| Evaluation | `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7` | chanakya 0.97, actions_only 0.99, no_belief 0.54, reactive 0.00; 0 violations | identical before and after the port |
| Safety | `python -m chanakya.eval.safety --mode offline` and `--mode online` | 0 violations each | online used the Groq realizer |
| Track B end to end | `scripts/demo/e2e_track_b.py` against a live backend | 17/17 (Gurnoor, PR #14) | callback, link, mock onboarding, DONE |
| Live | voice WebSocket with Sarvam speech, `PLANNER_ENABLED` on and off | Hindi call transcribed, disclosed, answered from sources | done before the port; the port was re-checked with live Groq text turns |

## Files Changed

- Track A packages: `chanakya/brain/` (including `contracts/`, `forest/`), `chanakya/sim/`, `chanakya/eval/`, `chanakya/humans/coach_engine.py`
- Data: `data/concerns/`, `data/personas/`, `data/transcripts/`, `data/forest/`; results in `docs/results/`
- Voice: `agent/brain_agent.py`, `agent/models.py`, `agent/graph.py`, `agent/normal_llm.py`, `agent/languages.py`, `backend/main.py`, `backend/voice_session.py`
- Shared: `chanakya/core/config.py`, `chanakya/core/llm.py` (core change), `init.sh`, `requirements*.txt`, `.env.example`, `README.md`, `.github/workflows/ci.yml`

## Decisions Made

- See "Decisions Made" in `progress.md`: the port onto main's core, the twin recalibration, the reverted repeated-objection change, planning while listening off by default

## Blockers / Risks

- OpenRouter has no credits; Groq's free tier rate limits make full online evaluations impossible
- The old stacked Track A branches are superseded; merge only `fix/windows-dev-setup`, `feat/core-llm-providers`, `feat/track-a-on-main`

## Next Session Startup

1. Read `CLAUDE.md`.
2. Read `feature_list.json` and `progress.md`.
3. Review this handoff.
4. Run `./init.sh` before editing.

## Recommended Next Step

- Merge the three branches above after review, then connect the brain to the mission runtime through adapters for the core `Planner`, `BeliefTracker` and `Realizer` protocols and the real `ActionGate`
