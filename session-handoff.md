# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Tracks A and B, I1, I2 and I4 are on `main`. Phase 5 (neural brain, Gurnoor) has started: N0 is done on `feat/N0-neural-baseline`
- Branch / commit: `feat/N0-neural-baseline`, cut from `main` at `b8f591e`

## Completed This Session

- [x] N0: labelled merchant lines (`chanakya/neural/paraphrase.py`, `data/neural/worry_lines.jsonl`), baselines (`chanakya/neural/baseline.py`), encoder choice (`intfloat/multilingual-e5-small`), tasks N0-N4 in `docs/TASKS.md` and `feature_list.json`

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Everything | `SKIP_INSTALL=1 ./init.sh` | passed | agent 104 OK, backend 98 OK, pytest 291, Ruff clean, frontend 22 |
| Neural tests | `python -m pytest chanakya/neural` | 3 passed | fake LLM, no network |
| Labelled lines | `python -m chanakya.neural.paraphrase --seed 7` | 2,123 lines | 1,455 train (DeepSeek), 668 test (GPT-6 Luna) |
| Worry scorers | `python -m chanakya.neural.baseline --seed 7 --llm-sample 112` | lexical 0.388, e5-small 0.437, LLM 0.777 | 14 labels on held-out lines |
| Planner | `python -m chanakya.eval.harness --mode offline --merchants 100 --seed 7/13 --variants chanakya,chanakya_forest` | 0.96 / 0.98 | forest makes no difference |

## Files Changed

- `chanakya/neural/` (new package and tests), `data/neural/`, `docs/results/neural-baseline/`, `requirements-neural.txt`
- `README.md`, `docs/results/README.md`, `docs/TASKS.md`, `feature_list.json`, `progress.md`, this file, `.gitignore`

## Decisions Made

- Test lines come from a different model family than train lines (Twin-B vs Twin-A models), and nothing close to a Concern Bank phrasing is kept, so no scorer is graded on sentences it was built from
- `multilingual-e5-small` is the shared encoder: best of the two on held-out lines (0.437) and on Punjabi (0.52), about 5 ms per line
- The neural libraries are optional (`requirements-neural.txt`); tests use fakes and never download a model, so CI stays light
- Gurnoor owns all of phase 5, including the small wiring edits in Durvish's `chanakya/brain/`

## Blockers / Risks

- The offline harness's template twins speak Concern Bank phrasings, so a better worry scorer cannot show up there; N1 needs a twin voice that speaks the held-out lines
- Closing the laptop lid pauses long background runs (it stalled the first baseline run)
- The review points on #19 are still open on main (see `progress.md`)

## Next Session Startup

1. Read `CLAUDE.md`.
2. Read `feature_list.json` and `progress.md`.
3. Review this handoff.
4. Run `./init.sh` before editing; `pip install -r requirements-neural.txt` for the neural parts.

## Recommended Next Step

- N1: train a calibrated 13-worry head on e5-small embeddings of the train lines, expose it as `EmbeddingScorer` behind `NEURAL_BELIEF_ENABLED`, and measure it on the test lines against 0.388 (lexical) and 0.777 (LLM)
