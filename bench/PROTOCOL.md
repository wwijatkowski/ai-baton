# Handoff benchmark: pilot protocol (draft, frozen before the first B run)

Plan and reasoning: `docs/knowledge/SAVINGS_PLAN.md`. This file fixes what the pilot does, so its results cannot be
shaped after the fact. Changes after the first B run are listed at the end with their reason.

## Question
A new conversation of Claude Code continues a task that Codex started. Does AI Baton (hooks deliver Codex's checkpoint;
the AI Baton rules in AGENTS.md) change the cost and success of finishing it, compared with the common practice without
AI Baton (a handoff file the previous agent was asked to keep up to date)?

## Tasks (`bench/tasks/<name>/`)
Each task: `repo/` (the project before part 1), `ISSUE.md` (the full requirements and acceptance criteria, in the repo,
for every arm), `part1.md` (what A is asked to do), `hidden/` (acceptance tests B never sees; existing behavior too).
- `shelf` (orientation-heavy): a small Python CLI package of several modules; tags for items. Part 1: model and
  storage (backward compatible). Part 2: CLI options, filtering, report grouping, tests.
- `textstats` (local): one Python module; word frequencies. Part 1: counting and `top`. Part 2: stopwords, case folding,
  punctuation rules from the issue.

## Agent A (once per task, frozen)
Codex (`codex exec`, model gpt-6.1-sol, effort medium), in the task repo set up with AI Baton (its global hooks save the
checkpoint), prompt: "Implement part 1 of ISSUE.md as described in part1.md. Follow AGENTS.md." Frozen afterwards as a
git commit: the code, `docs/AGENT_HANDOFF.md` as A left it, and `.agent-memory/` (A's checkpoint). A's usage is
recorded (preparation cost). Never rerun or edited after the first B run; a failed A run (part 1 tests failing) is
replaced before any B run, and that is noted.

## Agent B (the measured runs)
Claude Code (`claude -p`, model sonnet for the pilot, effort medium, `--permission-mode acceptEdits` with the same tool
allow-list in both arms: file tools, `python3`, `ls`, `cat` and read-only git; `--setting-sources project,local` so no
user settings or hooks of this machine apply), a fresh copy of the frozen repo per run, prompt in every arm:
"Continue the work on this project: finish ISSUE.md. Part 1 is done." No human input. Limit: 30 minutes; a run that
hits it is a failure with its usage counted.

Arms (the difference is AI Baton as a user would have it):
- `file`: AGENTS.md as A left it, with AI Baton's block replaced by the plain rule "the previous agent's handoff is in
  docs/AGENT_HANDOFF.md; read it, keep it up to date"; `.agent-memory/` and `.baton.json` removed; no hooks.
- `baton`: AGENTS.md and CLAUDE.md as `baton init` writes them (CLAUDE.md imports AGENTS.md and the handoff);
  `.agent-memory/` with A's checkpoint; AI Baton's Claude hooks in the project's `.claude/settings.json` (from this
  checkout's `bin/baton`).
  The file arm's CLAUDE.md is `@AGENTS.md` (how Claude Code reads AGENTS.md).
Everything else identical: code, ISSUE.md, docs/AGENT_HANDOFF.md, git history.

## Order and isolation
3 repeats x 2 arms x 2 tasks = 12 runs. Each repeat block holds both arms of a task in random order (seeded, the seed
in the results). Each run: its own temporary folder under `/tmp/baton-bench-*` (so no run sees another's files or
memory); its Claude transcript is moved into the results and removed from `~/.claude/projects`.

## Outcomes
Primary, per run: success (hidden tests and the repo's own tests pass after B ends) and full-run usage per component
(uncached input, cache writes, cache reads, output), from the transcript via `baton/metrics.py` (`parse_claude`),
reconciled by hand with the CLI's `--output-format json` usage for all 12 runs. API-equivalent cost with the prices
archived in the results.
Secondary, descriptive: tool calls and usage before the first file edit, wall time, injected context size.

## Analysis (pilot)
Per task and arm: success count, median and range of full-run tokens (uncached input + cache writes + output) and of
cost; both arms side by side; successful-only medians labelled as conditional. No significance test, no headline
percentage: the pilot checks the harness, the accounting and the spread, and sizes the study.

## Changes after the first B run
(none yet)

Before the first B run (2026-10-28): B model sonnet instead of opus for the pilot (the user's weekly Claude limit;
the pilot tests the harness, not the claim). No `--max-turns` in this Claude CLI: the 30-minute limit only.
Frozen A runs edited before any B run (2026-10-28): the part 1 commit had `__pycache__` files (the task repos had no
.gitignore; added) and named the project after A's temporary folder (`baton-bench-A-...`, replaced by the task name in
the files and the checkpoint). A's code, tests, handoff and checkpoint text are otherwise unchanged. The file arm keeps
A's AGENTS.md content (it had first replaced the whole file, which would also have removed A's project overview).
