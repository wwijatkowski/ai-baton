# Pilot 1 (2026-10-28): file handoff vs AI Baton

Protocol: `bench/PROTOCOL.md`. A = Codex (gpt-6.1-sol, medium) did part 1 once per task; B = Claude Code (sonnet, medium)
finished part 2, 3 repeats per task and arm, order randomized (seed 20261028). Raw rows: `runs.jsonl`.

| task | arm | success | tokens, median [min-max] | cache reads | tool calls | seconds | cost (CLI) |
|---|---|---|---|---|---|---|---|
| shelf | baton | 3/3 | 25,969 [23,900-26,587] | 216,998 | 5 | 53 | $0.157 |
| shelf | file | 3/3 | 24,021 [23,748-24,593] | 170,984 | 7 | 38 | $0.145 |
| textstats | baton | 3/3 | 22,915 [20,472-23,752] | 173,646 | 8 | 37 | $0.137 |
| textstats | file | 3/3 | 20,748 [19,868-23,032] | 199,323 | 11 | 35 | $0.130 |

Tokens: uncached input + cache writes + output (medians per cell). All 12 runs reconciled exactly with the CLI's own
usage report. Every baton run got one AI Baton delivery (about 1,500 characters).

## Findings
- The harness works: isolation (no user hooks or memory), accounting, hidden tests.
- Against a good handoff file, AI Baton saved nothing on these small tasks: about +8-10% tokens and cost, fewer tool
  calls. A (guided by AI Baton's rules) wrote a thorough handoff, which the file arm got too.
- In the baton arm the same information arrives three times: CLAUDE.md imports the handoff, the hook injects A's
  checkpoint, and the agent still reads the file (twice per run, partly to update it).
- The tasks are too small to show orientation savings (about 20k tokens for the whole continuation).

## Next
1. Remove the duplication (a checkpoint that does not repeat the handoff, or no handoff import when the hook runs) and
   measure the overhead again with the same tasks.
2. Pilot 2: scenarios where the information is missing or stale (no handoff written, an outdated handoff) on a larger
   task with real orientation cost.
