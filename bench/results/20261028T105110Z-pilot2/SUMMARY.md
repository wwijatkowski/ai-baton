# Pilot 2 (2026-10-28): missing or stale handoff; nothing / pasted reply / AI Baton

Protocol: `bench/PROTOCOL-2.md` (design reviewed by Codex). A = Codex (gpt-6.1-sol, medium) did part 1 once per task;
B = Claude Code (sonnet, medium), one run per cell, order randomized (seed 20261028). Raw rows: `runs.jsonl`;
versions in `plan.json`.

| task | handoff | nothing | pasted reply | AI Baton |
|---|---|---|---|---|
| habits | missing | 28,128 / $0.198 | 34,136 / $0.238 | 34,956 / $0.256 |
| habits | stale | 28,447 / $0.192 | 27,257 / $0.182 | 27,436 / $0.174 |
| pricing | missing | 20,606 / $0.117 | 21,867 / $0.135 | 23,849 / $0.148 |
| pricing | stale | 18,979 / $0.114 | 19,565 / $0.114 | 32,982 / $0.219 |

Tokens: uncached input + cache writes + output; cost as the CLI reports it. All 12 runs succeeded (hidden and repo
tests); all reconciled exactly with the CLI's usage. One run per cell: differences of a few thousand tokens are within
the run-to-run spread seen in pilot 1.

## Findings
- No saving from AI Baton in these conditions; "nothing transferred" was cheapest in 3 of 4 cells. With the task's
  intent written down in the repo (ISSUE.md with a work split), code and git history are enough for a cheap
  orientation (20-28k tokens); extra notes only add context.
- With a stale handoff, AI Baton's newer checkpoint plus the neutral "check notes against the code" rule led to more
  verification in one case (pricing: 14 tool calls vs 5).
- No run failed, so there was no success to rescue either.

## Conclusion
On tasks whose intent lives in the repository, AI Baton does not save tokens; no token-saving claim should be
published from pilots 1-2. Its possible value lies where these tasks give none: context that exists only in the
previous conversation (decisions made with the user, rejected approaches) and the person's time (no re-explaining or
copying), which a no-human benchmark does not measure. A pilot 3 would test continuation when the agreed details are
only in A's conversation, with success as the primary outcome.
