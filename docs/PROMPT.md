# Kickoff prompt for a coding session on Chanakya

Copy everything inside the box into a new coding session opened at the root of your local clone of `https://github.com/durvishkhurana/Chanakya`. Replace `<TASK_ID>` with the task you are taking from `docs/TASKS.md` (for example `A3` or `B1`) and `<TRACK>` with `A` or `B`.

---

```text
You are working on Chanakya, an AI merchant-success teammate for the Paytm AI Hackathon, Track 3:
"Build AI teammates that don't just respond; they get the job done."

Before writing any code, read these in full and follow them strictly:
1. CLAUDE.md                 - rules (git attribution, branches, ownership, safety, tests)
2. docs/IDEA.md              - the complete product idea, architecture, tech stack, research foundation
3. docs/TASKS.md             - the feature list, owners, branches, dependencies
4. The existing code you will touch, plus chanakya/core (shared contracts and fakes)

Understand the research behind the design. For the task you take, open the relevant papers from
docs/IDEA.md section 9 and use their methods faithfully:
- Hidden concerns and user simulation: arXiv 2605.22240 (Unlocking Proactivity in Task-Oriented Dialogue)
- Strategy Forest from expert transcripts: arXiv 2604.11427 (METRO)
- Look-ahead planning: arXiv 2511.21706 (NRPA-GD) and arXiv 2606.13683 (UP-NRPA); Rosin 2011 (NRPA)
- Ending dead calls: arXiv 2511.01181 (Learning When to Quit in Sales Conversations)
- Walk-away calibration of simulators: arXiv 2606.20708 (Simulated Customers Never Walk Away)
- Planning while listening: arXiv 2610.26233 (Heartbeat Thinking), arXiv 2510.06917 (SHANKS)
- Policy-compliant actions: arXiv 2608.19861 (PolicyGuide), arXiv 2607.01426 (reconsideration),
  arXiv 2610.25954 (CXBench, process compliance)
- Human hand-off: arXiv 2605.14830 (Alibaba human-in-the-loop field evidence)
- Tool-agent-user evaluation: arXiv 2406.12045 (tau-bench)
If a paper cannot be opened, work from the summary in docs/IDEA.md and say so in the PR description.
Do not cite any source that is not listed in docs/IDEA.md section 9.

My track is <TRACK>. My task is <TASK_ID>.

Do the following, in order:
1. Confirm the task's dependencies in docs/TASKS.md are merged on origin/main. If not, tell me
   which ones are missing and propose working against the fakes in chanakya/core/fakes.py.
2. git fetch origin and create the branch named in the task from origin/main.
3. Write a short plan: files to add or change (only inside the directories the task owns),
   contracts from chanakya/core you will use, tests you will write, any config flag you will add.
   Show me the plan and wait for my go-ahead.
4. Implement the task in small, meaningful Conventional Commits. Use Pydantic v2 schemas from
   chanakya/core for anything crossing a module boundary. Put new behaviour behind its feature flag.
5. Write tests in the task's package. Make simulations deterministic with explicit seeds.
   Never place real calls or send real messages in tests.
6. Run Ruff, the full pytest suite, the inherited unittest suites, and frontend lint/build if the
   frontend changed. Fix failures without weakening existing tests.
7. Tick the task's checkbox in docs/TASKS.md and update README.md if you added commands or flags.
8. Rebase on origin/main, push the branch, and open a PR to main with gh pr create.
   PR body: what changed, why, how it was tested, "Closes task <TASK_ID>".

Hard rules (also in CLAUDE.md):
- Never mention Claude, Anthropic or AI assistance in commits, branch names, PRs, comments or docs.
  No Co-Authored-By trailers or "Generated with" lines. Use the machine's existing git identity.
- Never push to main, never force-push shared branches, never add collaborators or change repo settings.
- Edit only the directories your task owns. Contract changes go in a separate small "core:" PR.
- Never commit secrets, .env files, phone numbers or personal data.
- All Paytm-like systems are mocks and must be labelled as mocks. Never claim affiliation with Paytm.
- Product facts only from data/knowledge with source URLs. Never invent prices, offers or timelines.
- Keep the agent's safety behaviour: disclose it is an AI, never ask for OTP/UPI PIN/CVV/passwords/
  identity documents, stop on a no, no write action without explicit consent.
- Report only measured numbers.

When the PR is open, give me: the PR link, a summary of what was built, test results,
and anything the other track needs to know (new events, contract changes, flags).
```

---

## Notes

- One session per task. Start a fresh session for the next task so context stays clean.
- If two tasks in your track have no dependency between them, you may run them in two sessions on two branches, as long as they own different directories.
- Before merging, the other member reviews the PR, especially anything touching `chanakya/core`, shared files or safety rules.
