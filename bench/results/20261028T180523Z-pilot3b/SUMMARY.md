# Pilot 3b (2026-10-28): the AI Baton arm again, with the "copy the user's requirements" rule

Protocol: `bench/PROTOCOL-3.md` (follow-up 3b: decided after pilot 3's results; a before/after on the AI Baton arm).
New baton A runs (2 per task) with AI Baton's changed AGENTS.md rule ("for work that is left, copy the user's
requirements as they gave them: exact formats, names, messages, options"); one B run each, as in pilot 3. All 4 runs
reconciled exactly with the CLI's usage.

| | completed |
|---|---|
| AI Baton, pilot 3 (old rule) | 2/4 |
| AI Baton, pilot 3b (new rule) | 3/4 (report 2/2, bundles 1/2) |
| pilot 3, for comparison: none / paste / respec | 0/4 / 0/4 / 4/4 |

- Audit: with the new rule all four A runs wrote every checked detail of part 2 into the handoff (5/5; bundles had
  4/5 before, missing the exact invoice line).
- The one failure (bundles, pair 1): the handoff held the spec's example verbatim; B read "two spaces between columns"
  as aligned columns and said so in its reply ("If you want a fixed two spaces for every code, it's a one-line
  change"). The hidden test expects a fixed two spaces: an ambiguity in the task's spec, counted as a failure as the
  protocol says.
- Tokens per run: 21-25k (cost $0.12-0.16), in line with pilot 3's AI Baton runs.

## Statement this supports (with pilots 1-3)
"In a small benchmark (Codex to Claude Code), when a feature had been specified only in the previous chat, the next
agent completed 3 of 4 continuations with AI Baton, 0 of 4 when the previous agent's final reply was pasted, and 0 of 4
with no context (4 of 4 when the user pasted the original request again). When the task was described in the
repository, AI Baton changed neither the result nor the token use. Method and data: bench/."
