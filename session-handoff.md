# Session Handoff

## Current Objective

- Goal: build Chanakya as specified in `docs/IDEA.md`, task by task from `feature_list.json`
- Current status: Tracks A and B and Phase 4 (except the I3 backup video) are on `main`. Phase 5, the neural brain, is under way with one owner per network: N1 (Gurnoor) in progress, N2 and N3 (Durvish) not started, N4 (Gurnoor) after them
- Branch / commit: N1 work is on `feat/N1-worry-scorer` (pushed, not merged); this handoff is from `docs/phase5-harness`

## Completed This Session

- [x] N0 baselines and labelled lines (#24); revised N1 spec after Durvish's review (#25); `WORRY_SCORER` setting (#26)
- [x] Phase 5 split, one owner per network (#28); N0-N4 entries restored after #23 dropped them (#29)
- [x] On `feat/N1-worry-scorer`: ONNX encoder, 13-sigmoid worry head with calibration, `EmbeddingScorer` and `select_scorer`, training script, hand-written set file, guide and checker, tests
- [x] Harness files updated to the final Phase 5 plan: `docs/TASKS.md`, `feature_list.json`, `progress.md`, this file, README, a Phase 5 section in `CLAUDE.md`

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| Everything on main | `SKIP_INSTALL=1 ./init.sh` | passed | 292 pytest after #26 |
| Neural tests (N1 branch) | `python -m pytest chanakya/neural` | 10 passed | fake encoder, no network |
| ONNX vs PyTorch encoder | encoder comparison on four lines | cosine 1.0 | 2.4 ms per line |
| Worry head (N1 branch) | `python -m chanakya.neural.train_worry --seed 7` | embedding 0.536, lexical 0.394 | N0 test split, 14 labels; calibration error 0.0049 after scaling |
| Encoder fine-tuning probe | scratch experiment, 10 epochs | validation 0.72, test 0.55 | learns the training model's style; not adopted |

## Files Changed

- Phase 5 docs: `docs/TASKS.md`, `feature_list.json`, `progress.md`, `session-handoff.md`, `README.md`, `CLAUDE.md`
- N1 branch: `chanakya/neural/` (encoder, head, scorer, train_worry, human_set and tests), `data/neural/`, `requirements*.txt`

## Decisions Made

- One owner per neural network; settings `WORRY_SCORER`, `PLANNER_MEMORY`, `PLANNER_VALUE` with defaults that keep today's behaviour
- The encoder runs on ONNX Runtime; numpy is a base requirement; encoder weights are never committed
- `WORRY_SCORER` unset keeps today's choice (LLM scorer on live calls when an LLM is configured), so the new default never downgrades live calls
- The hand-written test set is Gurnoor's to write, by hand, and is never used for training, tuning or calibration

## Blockers / Risks

- N1 accuracy (0.536) is well short of the LLM (0.777); the next lever is training lines from more model families, not a bigger model
- The hand-written test set is empty, and N1 cannot be marked done without it
- The first three #19 review fixes are still on `fix/I1-review-fixes`, not merged
- Closing the laptop lid pauses long runs

## Next Session Startup

1. Read `CLAUDE.md`, including the Phase 5 rules in section 7.
2. Read `feature_list.json`, `progress.md` and Phase 5 in `docs/TASKS.md`.
3. Review this handoff.
4. Run `./init.sh`; for neural work, `pip install -r requirements-neural.txt` and `python -m chanakya.neural.encoder --download`.

## Recommended Next Step

- N1: generate training lines from Mistral and one more model family, retrain, then the belief tracker change, the lines voice and full-call results
- Durvish: N3 first (it needs nothing from N1), then N2 once the lines voice lands
