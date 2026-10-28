# Measuring what AI Baton saves

Goal: claims we can publish (README, Marketplace, posts) that survive a skeptical reader: they name the comparator,
tasks, direction, models, full-run metric and success counts, and ship with the method and raw data. Plan of
2026-10-28, revised after a Codex critique (gpt-6.1-sol, high).

## The question
What does AI Baton add when a new conversation (another agent, or the same one in a new chat) continues work?
Two different questions, kept apart:
- **Workflow benefit:** no saved handoff vs an ordinary handoff file vs AI Baton.
- **Delivery benefit (AI Baton's own claim):** the same saved information in a handoff file the agent may read vs
  delivered by AI Baton's hooks. This is the main comparison.
AI Baton's other advantage is that the information exists at all: its Stop hook saves every turn's state without the
agent spending tokens or discipline on a handoff file. That is measured as preparation cost and as a stale-handoff
scenario (below), not assumed.

## Evidence so far
Claude transcripts on disk (2026-10-28): 24 sessions with prompts, oldest 2026-10-17 (Claude deletes after 30 days).
With AI Baton context and an edit: n=9, median 12 tool calls and 80k tokens before the first edit; without: n=2. One
project, different tasks: a hint, never a claim.

## Benchmark (`bench/`, the source of the claims)
- **Tasks:** real-looking repos, each with a feature split in two; part 1 done (a git commit) by agent A in a real run,
  its outputs (final reply, AI Baton checkpoint, handoff file) frozen before any B run and never tuned afterwards.
  Requirements and acceptance criteria live in the repo for every arm (an issue file); the handoff adds progress,
  locations, decisions, what is left. Chosen up front to vary the expected benefit: a local change, a change across
  several components, one where the handoff adds little; later a stale or incomplete handoff.
- **Run:** agent B, new conversation, identical neutral prompt in every arm, no human help. Isolated: its own HOME,
  checkout and agent config (like `tests/e2e_hooks.py` and `tests/live/`), so no run sees another's memory or
  transcripts. Arm order randomized and balanced within each task/repeat block; launch times and cache use recorded.
- **Arms:** cold (no handoff; project docs otherwise identical), file (A's handoff in `docs/AGENT_HANDOFF.md`, no
  hooks), baton (hooks deliver A's checkpoint; the same file present). Manual paste: optional, later.
- **Outcomes, primary:** success (frozen hidden tests, existing behavior included, run after B ends) and full-run
  usage per provider component (uncached input, cache writes, cache reads, output), cost as API-equivalent with
  archived prices. **Secondary, descriptive:** tool calls and tokens until the first agent-made source or test edit
  (shell edits detected; hook and handoff writes excluded; runs without an edit reported apart), wall time, hook time.
- **Accounting:** provider-native usage kept raw, normalized by versioned adapters built on `baton/usage.py`'s parsers
  (Claude message dedup, Codex cumulative deltas); checked by hand on the pilot's transcripts. Unknown is unknown, not 0.
- **Protocol frozen before running** (`bench/PROTOCOL.md`): budgets (tokens, time, tool calls), failures and timeouts,
  infrastructure retries (original attempt kept), primary comparison and metric, aggregation (task-level medians and
  aggregate totals named as such), stopping rule. Costs always shown with success; successful-only costs as a labelled
  conditional view.
- **Net saving** = baseline continuation cost − baton continuation cost − incremental preparation cost (A's handoff
  writing vs AI Baton's local capture). Injected context is already inside the continuation cost: not subtracted again.
- A small blinded patch audit (arm labels hidden) on a subset; no model judge for every run.

### Pilot first (a test of the harness, not a publishable number)
12 B runs: 2 frozen tasks (one orientation-heavy, one local change) x 2 arms (file vs baton) x 3 repeats, one
direction (A = Codex, B = Claude, or the reverse), order balanced. Reconcile the 12 usage totals by hand. Then size
the study from the pilot's spread, preferring more tasks over more repeats; add the other direction and same-agent
continuation only when we want those claims.

## Field data (supporting, descriptive only)
- Ours only, never a product feature (user, 2026-10-28: no value for other users, and "collecting metrics" sounds bad):
  `bench/metrics.py collect` on our machine, daily by a macOS LaunchAgent (`bench/collect-daily.sh`); not in the
  extension or the CLI it bundles. Per conversation from the transcripts, incrementally and
  idempotently (resumed conversations not duplicated): agent, model, project id (hash), whether AI Baton context was
  configured and whether another agent's checkpoint was delivered, injected characters, usage components, tool calls,
  first-edit metrics, failures and sessions without edits included. Counts only, no text; stays on the machine.
- Run it now and regularly, so transcripts are summarized before Claude deletes them.
- Used for: real overhead (the injected context distribution, not "about 2k"), handoff frequency, reliability,
  associations. Never for causal savings claims.

## Claims to make, and to avoid
- Make (if the data supports it): "Continuing a task in a new conversation, Claude Code with AI Baton used X% fewer
  tokens over the whole run than with the same handoff as a file (median over N tasks, R runs each, A = Codex, models
  ...; success a/b vs c/d); method and data in bench/." Plus the measured overhead per new chat.
- Avoid: savings from first-edit metrics; cost savings from token counts or subscription logs; "fewer user messages"
  from a no-human benchmark; "avoids wrong turns" without a defined measure; "works across agents" from one direction;
  "no loss of correctness" from a few runs; any percentage from the observational data above.
