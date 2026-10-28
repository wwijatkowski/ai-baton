# Pilot 3 (2026-10-28): the feature was specified only in the previous chat

Protocol: `bench/PROTOCOL-3.md` (Codex-reviewed design). Two tasks (`report` on habits, `bundles` on pricing); for each,
two independent pairs of A runs (Codex gpt-6.1-sol, medium): one in a plain project, one with AI Baton; A got the spec
only in its first message and did part 1. B = Claude Code (sonnet, medium), prompt "Part 1 of the feature from our
previous conversation is done. Please do part 2 now and finish it." One B run per frozen state and arm (16 runs; 4
earlier runs with a worse prompt are in `../20261028T141433Z-pilot3-discarded/`, see the protocol). All 16 runs
reconciled exactly with the CLI's usage.

| B arm | completed | tokens (median) | cost (median) |
|---|---|---|---|
| none: no context, no user follow-up | 0/4 | 17,580 | $0.101 |
| paste: A's final reply pasted | 0/4 | 13,674 | $0.073 |
| baton: AI Baton workflow | 2/4 (report 2/2, bundles 0/2) | 21,360 | $0.127 |
| respec: the original request pasted again | 4/4 | 18,403 | $0.104 |

Tokens: uncached input + cache writes + output. Completed: hidden tests (part 2 and existing behavior) and the repo's
own tests pass.

## What happened
- none / paste: B said it could not see the earlier conversation and guessed (e.g. a `week` command instead of
  `report`), or stopped and said it could not tell what part 2 was. A's final replies (about 300 characters) only said
  part 2 remained.
- baton: AI Baton's rules made A write what was left into the handoff and decisions (audit: report 5/5 of the checked
  details in A's docs, bundles 4/5). B completed `report` twice; for `bundles` it built the right feature but missed
  details A had not written down (the exact invoice line), so the hidden tests failed.
- respec: with the full request again, every run completed: the tasks are solvable and the prompt is clear.

## Conclusion
In this scenario AI Baton carried context the other transfers lacked (2/4 vs 0/4), but only as much as the previous
agent wrote down. Token use is not comparable across arms here: the cheaper arms did the wrong thing or nothing. A
bounded README statement this supports: "In a small Codex-to-Claude benchmark where a feature was specified only in the
previous chat, the next agent completed 2 of 4 continuations with AI Baton, 0 of 4 when the previous agent's final
reply was pasted, and 0 of 4 with no context. Method and data: bench/."

Product finding: the missing details were in the user's own message, which AI Baton does not keep (it keeps the
agent's reply). Keeping the user's request in the checkpoint should close most of the gap to "respec"; to be measured
with new A runs of that version.
