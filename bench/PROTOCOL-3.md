# Handoff benchmark: pilot 3 protocol (frozen before the specifications, tests or A runs are used)

Plan: `docs/knowledge/SAVINGS_PLAN.md`; pilots 1-2: `bench/PROTOCOL.md`, `bench/PROTOCOL-2.md` and their SUMMARY.md
files (no token saving when the task's intent is in the repo). Design reviewed by Codex (gpt-6.1-sol, high), all
points adopted. Changes after the first A run are listed at the end with their reason.

## Question (a selected scenario; a workflow comparison)
The user specified a feature only in the first message to agent A (nothing of it in the repo); A did part 1; a new
conversation of agent B continues, with no user follow-up. How do completions compare between AI Baton's full
workflow (its rules and hooks for A and B) and an unstructured project, where the user transfers A's final reply or
the original request by hand? The treatment is the whole workflow, not the hooks alone.

## Tasks (frozen before any A run)
New features on the existing base repos, specified only in `bench/tasks3/<task>/spec.md` (sent to A as its first
message; never in the repo or history):
- `report` on habits: a weekly summary (part 1: computing it; part 2: the command, its text and JSON output).
- `bundles` on pricing: product bundles at a bundle price (part 1: the bundle rules; part 2: invoice lines, a listing
  command, an option to turn them off).
Each spec mixes behavior with a few justified exact contracts (output text, option names). Hidden tests check part 2
and existing behavior; a reference passes them; the base repo fails them.

## Agent A (2 independent pairs per task, 8 runs)
Codex (`codex exec`, gpt-6.1-sol, medium); first message: the spec, then "Please do part 1 now; part 2 will be done
later in another conversation." Pair = one `plain` run (AGENTS.md: project description only) and one `baton` run (the
repo set up with AI Baton; its hooks capture the final reply). Order inside each pair randomized. Everything A writes
is kept (code, tests, docs) and frozen as one commit "Work in progress" on top of the base. A run whose repo tests fail
is kept and used as it is (no reruns to get a better handoff); an A run that crashes (no reply) is rerun once, noted.

## Agent B (16 runs: one per frozen state and arm)
Claude Code (sonnet, medium; tools and isolation as before); prompt "Continue the work from the previous conversation."
- plain A's states: `none` (the prompt only: no transferred context, no user follow-up; a diagnostic),
  `paste` (+ "The previous agent's last message:" and plain A's final reply verbatim),
  `respec` (+ "The original request:" and the spec verbatim);
- baton A's states: `baton` (AI Baton as set up for A, project hooks, A's checkpoint delivered; the prompt only).
Order randomized within each task block (seeded). 30 minutes per run.

## Outcomes and reporting
Primary: completion (hidden + repo tests), counted per run and reported per task and A pair; the main contrast is
baton vs paste. Requirement-level failures from the hidden tests. Usage reported per component (uncached input, cache
writes, cache reads, output) and cost (CLI), all runs; A's preparation usage reported separately. Tokens per completed
run only as a secondary figure, undefined at zero completions, never a headline. Also: whether B asked a question and
stopped. After freezing A: an audit of where each requirement survived (code/tests, docs, final reply, checkpoint),
not used to select runs.

## Changes after the first A run
(none yet)
