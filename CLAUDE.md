# Rules for working on Chanakya

These rules apply to every coding session and every contributor.

- `docs/IDEA.md`: what we are building
- `docs/TASKS.md`: the full spec of every task, owner and directory
- `feature_list.json`: live status, dependencies and evidence for every task
- `progress.md`: current state of each track and the next step
- `session-handoff.md`: the note the last session left for the next one
- `./init.sh`: the one verification command

## 1. Git and attribution

- Never mention Claude, Anthropic, AI assistants or code generation anywhere in the repository history or content. This includes commit messages, branch names, PR titles and descriptions, code comments, docs and changelogs.
- Never add `Co-Authored-By` trailers, "Generated with" lines, bot signatures or emojis that imply tool authorship.
- Commit with the git identity already configured on the machine (`git config user.name` / `user.email`). Never change it.
- Never add collaborators, change repository settings, branch protection, secrets or webhooks.
- Never force-push to `main`. Never push directly to `main`; all work lands through pull requests.
- Never rewrite published history on a shared branch.

## 2. Branches and pull requests

- One feature per branch, named `feat/<task-id>-<short-slug>`, for example `feat/B1-mock-systems`. Fixes use `fix/<short-slug>`, docs use `docs/<short-slug>`.
- Always branch from the latest `main`: `git fetch origin && git switch -c feat/... origin/main`.
- Before opening a PR, rebase on `origin/main`, re-run all tests and resolve conflicts locally.
- Commit messages follow Conventional Commits: `feat(brain): add bayesian belief update`, `fix(actions): reject unknown tool names`, `test(sim): add walk-away calibration test`.
- Keep commits small and meaningful. No "wip" or "update" messages on the final branch.
- PR description: what changed, why, how it was tested, which task ID it closes. Tick the task's checkbox in `docs/TASKS.md` in the same PR.
- Open the PR with `gh pr create --base main`. Do not merge your own PR without the other member's review unless the task says it is safe to self-merge.

## 3. Ownership and avoiding clashes

- Edit only the directories listed under your task in `docs/TASKS.md`.
- `chanakya/core/` holds shared contracts (schemas, interfaces, event types). Change it only in a separate small PR titled `core: ...`, and tell the other member before merging. Never change a contract silently inside a feature branch.
- If your feature needs something from the other track that does not exist yet, code against the interface in `chanakya/core` and use a local fake in your tests. Do not implement the other track's module.
- Shared files (`requirements.txt`, `frontend/package.json`, `backend/main.py` router registration, `.env.example`) take additive one-line changes only. Append; do not reorder or reformat.
- New features are wired in behind config flags in `chanakya/core/config.py`, default off until integrated.

## 4. Secrets, data and safety

- Never commit `.env`, API keys, tokens, phone numbers, call recordings or personal data. Only `.env.example` with blank values.
- Tests and simulations must never place real calls or send real messages. Twilio stays disabled by default and limited to the allowlisted number.
- All Paytm-like systems are mocks. Label them clearly as mocks in code and UI. Never claim affiliation with Paytm.
- Product facts must come from `data/knowledge/` with a source URL and review date. Never invent prices, rental, charges, offers, cashback, eligibility or timelines in prompts, code, fixtures or docs.
- Preserve the agent's safety rules in every prompt and code path:
  - disclose that it is an AI assistant
  - never ask for OTP, UPI PIN, CVV, passwords, full card numbers or identity documents
  - stop when the merchant declines; a short acknowledgement is not consent
  - no write action without explicit consent captured in the transcript
- Unknown or unregistered actions must be rejected, never improvised.

## 5. Code standards

- Python 3.12, type hints everywhere, Pydantic v2 models for all data crossing module boundaries.
- Format and lint with Ruff before committing. Frontend uses ESLint.
- Keep modules small and focused. Public functions get a short docstring.
- No hidden network calls in tests. LLM and speech calls go through the clients in `chanakya/core` so they can be faked.
- Simulations and evaluations take an explicit random seed and are reproducible.
- User-facing agent text never uses the em dash character.

## 6. Tests

- Every feature ships with tests in its own package (`chanakya/<pkg>/tests/`) or in `tests/` for integration.
- Run before every commit:
  - `python -m pytest -q`
  - `python -m unittest discover -s agent -t .` and `python -m unittest discover -s backend -t .` for the inherited voice stack
  - `cd frontend && npm run lint && npm run build` when the frontend changes
- Do not delete or weaken an existing test to make a change pass.

## 7. Documentation and claims

- Research claims cite only the verified sources listed in `docs/IDEA.md`, section 9.
- Metrics in docs, README or slides come only from measured runs of the evaluation harness, with the command and seed that produced them.
- Update `README.md` when you add a command, a config flag or a new service.

## 8. Session workflow

### Startup Workflow

Before writing code:

1. Read this file, then `progress.md` and `session-handoff.md`.
2. Open `feature_list.json`. Pick the first task in your track whose `status` is `not-started` and whose `dependencies` are all `done`. If a dependency from the other track is missing, work against `chanakya/core/fakes.py`.
3. Set that task's `status` to `in-progress` and record yourself in `progress.md`.
4. Read the task's full spec in `docs/TASKS.md` and the code you are about to change.
5. Run `./init.sh`. If it fails before you have changed anything, fix or report that first.
6. Plan first: files to add or change, contracts used, tests to write. Show the plan, then implement.

### One feature at a time

- Each track has at most one task `in-progress`. Two members may work in parallel only because their tracks own different directories.
- Stay in scope: edit only the directories the task owns (`owns` in `feature_list.json`). Anything else becomes a note in `progress.md`, not a change.
- If a requirement is unclear or conflicts with these rules, stop and ask instead of guessing.

### Verification Commands

```bash
./init.sh                # Python unit tests, pytest, Ruff, frontend lint and tests
FULL=1 ./init.sh         # also runs the frontend production build
SKIP_INSTALL=1 ./init.sh # skip dependency installation
```


### Definition of Done

A task is done only when all of these hold:

- [ ] Every point in the task's `done_when` is met.
- [ ] `./init.sh` passes, and `FULL=1 ./init.sh` passes if the frontend changed.
- [ ] Tests for the new behaviour exist in the task's package.
- [ ] `feature_list.json` has `status: done` and `evidence` with the commands run and their result.
- [ ] The PR is open with the task ID, and the task's checkbox is ticked in `docs/TASKS.md`.

Never mark a task done on a claim. No evidence means not done.

### End of Session

Before ending, even when the task is unfinished:

1. Run `./init.sh` and note the result.
2. Update the task in `feature_list.json`: `status` and `evidence`, or `blocked` with the reason.
3. Update `progress.md` for your track: what changed, what is next, blockers.
4. Rewrite `session-handoff.md` so the next session can restart from a clean state without this conversation.
5. Commit work in progress on the feature branch; never leave edits only in the working tree.
