# Handoff benchmark: pilot 2 protocol (frozen before the tasks are built)

Plan: `docs/knowledge/SAVINGS_PLAN.md`; pilot 1: `bench/PROTOCOL.md` and `bench/results/20261028T100822Z/SUMMARY.md`.
Design reviewed by Codex (gpt-6.1-sol, high) on 2026-10-28; all its points adopted. Changes after the first B run are
listed at the end with their reason.

## Question (a selected condition, not average use)
In a controlled continuation where the handoff document is **missing** or **stale**, how does finishing the task
compare when B gets (1) nothing transferred, (2) A's final reply pasted by hand, (3) AI Baton? Pilot 1 (a good
handoff file: no saving) is always reported next to it. Exploratory: it shows whether a signal exists and whether it
survives the manual paste; it is not a stable percentage.

## Tasks
Two new tasks, chosen and frozen (repo, ISSUE.md, part1.md, hidden tests, reference) before any A run:
- `habits` (part 1 spread over several modules: model, storage, streaks, scheduler);
- `pricing` (part 1 in one new module, easy to find through git and tests).
Natural structure; nothing scattered on purpose. Hidden tests check part 2 and existing behavior; the reference passes
them, the base repo fails them.

## Agent A (once per task, shared by both conditions)
Codex (`codex exec`, gpt-6.1-sol, effort medium) in the task repo set up with AI Baton (hooks capture its final reply),
prompt: "Implement part 1 of ISSUE.md as described in part1.md." (no request to write a handoff). Frozen: A's code and
tests as one commit; any changes A made under `docs/` or to AGENTS.md/CLAUDE.md are left out of that commit and
noted (B must not find a fresh handoff in git history); A's final reply and checkpoint are kept as captured, never
edited. The first A run that passes the repo's own tests is used.

## Conditions (document manipulation, identical in every arm)
- `missing`: no `docs/AGENT_HANDOFF.md`.
- `stale`: `docs/AGENT_HANDOFF.md` as written before part 1 (state: project set up; next: part 1 of ISSUE.md).

## Arms (B: Claude Code, sonnet, effort medium; tools and isolation as in pilot 1)
Every arm's AGENTS.md has the project description and this neutral rule: "Notes from earlier work (handoff files,
messages, checkpoints) may be out of date: check them against the code and git before relying on them."
- `none`: no `.agent-memory/`, no hooks, no AI Baton block. Prompt: "Continue the work on this project: finish ISSUE.md."
- `paste`: as `none`; the prompt adds "The previous agent's last message:" and A's final reply verbatim.
- `baton`: AI Baton as `baton init` sets it up (its AGENTS.md block, CLAUDE.md, project hooks, `.agent-memory/` with
  A's checkpoint) plus the neutral rule; the prompt of `none`.

## Runs, order, budget
2 tasks x 2 conditions x 3 arms x 1 run = 12 B runs, order randomized (seeded) within each task block. 30 minutes
per run. Product version pinned: the AI Baton commit, Claude and Codex CLI versions and models are written to the
results.

## Outcomes and analysis
Primary: success (hidden + repo tests) and full-run usage per component (uncached input, cache writes, cache reads,
output) and API-equivalent cost (the CLI's report), all runs, failures included. Secondary: first-request context,
tool calls and usage before the first substantive implementation change. Reported per run and per task/condition;
contrasts named "vs nothing transferred" and "vs pasted reply"; success as counts ("2/2 vs 1/2"), never as rates.
No headline percentage from this pilot.

## Notes before the first B run (2026-10-28)
- A (both tasks) also updated docs/AGENT_HANDOFF.md, STATUS and DECISIONS on its own (the hook context and AI Baton's
  rules suggest it); as planned these were left out of the frozen history (`left_out_of_history` in a.json). Its final
  reply, kept verbatim, says it updated the handoff; the paste and baton arms get that sentence alike, and AI Baton's
  checkpoint is flagged "updated docs/AGENT_HANDOFF.md" although the file is missing or stale in B's copy.
- The stale handoff is committed in the first commit ("Project"), before part 1, so git does not show it as newer.
- Dry run of all 12 setups checked: history Project / Part 1 / Workspace, memory and hooks only in the baton arm, the
  neutral rule in every arm, clean git status, the repo's tests passing.

## Changes after the first B run
(none yet)
