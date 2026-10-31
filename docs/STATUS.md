# Project status

## Goal
One place to switch between coding agents on a project without losing context or overspending tokens.

## Done
- CLI: `hook`, `init`, `status`, `usage`, `recall`.
- Shared memory through SessionStart / UserPromptSubmit / Stop hooks, tiered (hot / warm / cold).
- VS Code extension: agent cards, project docs, token usage chart, Claude and Codex plan limits, status bar, agent switcher (Cmd+Alt+A).
- English UI, new logo.
- Model and effort per agent from the panel (`baton models`, `baton set-model`), written to `~/.claude/settings.json` and `~/.codex/config.toml`.
- "Add agent": panel buttons Add agent / Find agents, `baton add-agent|remove-agent`; Remove on every card (built-ins are hidden, not deleted).
- Only installed agents are shown; init writes hooks only for them, so a single-agent setup works out of the box.
- Second opinions: `baton review` (agents run it on request; panel button "Ask for review"). Works without git (shadow snapshots, or a file list when git is not installed) and reviews a conversation's replies when no files changed.
- Memory hooks installed once in user settings (`baton install-hooks`); panel warns when hooks are missing or not approved in Codex.
- Stale plan limits greyed out with "Live in Claude"; collapsed "Recent work" section (one entry per agent session, all agents). "Show all" opens the full history in an editor tab with search and agent filter.

## In progress
- Dogfooding AI Baton on this repo.
- Removing private data from committed bench transcripts (redact, rewrite history; waits for the user's approval).
- Antigravity via MCP: server verified, client not yet.
- Next feature: context-size indicator and `/clear` suggestion in the panel.

## To do
1. Done: 0.4.1 published on the VS Code Marketplace and Open VSX by `release.yml` from a version tag, with no stored tokens (Azure managed identity, Open VSX trusted publishing). Left: publisher display name.
2. Shared memory for agents without hooks (Copilot, Cline, Gemini, Continue, ...), one approach for all:
   - Main path, done (0.5.0): `baton mcp --agent ID`, a local stdio MCP server with `baton_context`, `baton_checkpoint` and `baton_recall` (DECISIONS 2026-10-27). Copilot gets it through VS Code's MCP provider API (Connect memory / Disconnect on its card; no settings file edited). Verified: Claude Code as a real MCP client (CI), Copilot Free live (UI test rounds 8 and 9: it called the tools by itself, saved a checkpoint, Disconnect removed them). Copilot loads by itself but did not save by itself after ordinary work (round 9, B3); the tool description and baton_context's result now ask it to save before ending a turn with changes (not yet re-tested). Native Copilot hooks (branch copilot-hooks): context at SessionStart and the reply saved at Stop, verified live with the real Copilot by `tests/live/run.js` (2026-10-27/28, 7 messages a round: context every turn, after a reload and in a new chat, replies saved once, hooks with the MCP tools, hooks removed and installed with a chat open; only in Copilot CLI chats); released in 0.5.1 (2026-10-28), UI round 10 all PASS; other agents' MCP configs (Cline, Gemini, Continue) once they can be tested.
   - Fallback: the extension infers a checkpoint when the handoff doc or git changes while a hook-less agent was the last one opened (marked as inferred).
   - Per agent, use native hooks where they exist (check each agent's docs when adding it).
3. Done (unreleased): an agent gets its own latest checkpoint from its other conversations (new chat, or one running in parallel); review by any agent with a model and effort for that review only. Released in 0.4.2. Small ideas left: let the panel take a model id typed by hand (the CLI already does); a review run should not count as Claude's "last used" model (`models.claude_last_model` reads the newest transcript, which can be the reviewer's); the CLI installer (`cli-install.js`) should compare the bundled CLI's content, not only its version, so a test .vsix with an unchanged version still updates `~/.ai-baton` (UI test round 7).
4. More reviewers for `baton review`: agents with a headless CLI (check Gemini CLI, Copilot CLI) get a runner in `review.py` and `"review"` in the registry; panel-only agents (Cline, Continue) cannot review.
5. Done (0.4.0): Windows support, CI on Linux/Windows/macOS (unit tests plus the extension in a real VS Code), extension.js flow tests with a fake VS Code API, activity per conversation. Left: a manual check with the real Claude and Codex extensions on Windows.
6a. Windows (reported from a real setup, 2026-10-27): the panel's Install hooks and a terminal `baton install-hooks` can write different Python interpreters (Microsoft Store Python through the py launcher vs the python.org one running the CLI); pick one consistently, honouring `aiBaton.python`. Also check whether Codex's hook `cwd` follows the agent's `cd` the way Claude's did (fixed for Claude with CLAUDE_PROJECT_DIR in 0.5.0).
6. Measure what AI Baton saves, credibly enough to publish: plan in `docs/knowledge/SAVINGS_PLAN.md` (2026-10-28, after a Codex critique). Field data: `bench/metrics.py` collects daily on our machine only (LaunchAgent; not shipped). Pilot done 2026-10-28 (`bench/`, 12 runs, Sonnet): vs a good handoff file AI Baton saved nothing (+8-10% tokens: the same information arrives three times); measured fixed cost: about 2k tokens of context per new conversation (AGENTS.md rules, the handoff import, the hook context); a trim that replaced a checkpoint's summary with a pointer to an unchanged handoff was dropped after a Codex review (it can hide reply-only facts such as failing tests; the rest saves ~50 tokens). Pilot 2 done 2026-10-28 (`bench/results/20261028T105110Z-pilot2/SUMMARY.md`): with a missing or stale handoff, 'nothing transferred' was cheapest in 3 of 4 cells; 12/12 succeeded. Conclusion: no token-saving claim from tasks whose intent is in the repo. Pilot 3 done 2026-10-28 (`bench/results/20261028T141613Z-pilot3/SUMMARY.md`): spec only in the previous chat; completed: AI Baton 2/4, pasted final reply 0/4, nothing 0/4, original request pasted again 4/4. AI Baton carries what the previous agent wrote down; the gaps were details from the user's own message, which AI Baton does not keep. Saving the user's prompts was dropped (median prompt 56 characters, 10% over 300: mostly noise); instead an AGENTS.md rule (copy the user's requirements for work that is left); pilot 3b with it: AI Baton 3/4 (the miss: an ambiguous spacing in the task's spec). Next: the README benefits section with the bounded statement from bench/results/*-pilot3b/SUMMARY.md; a larger run (more tasks, the other direction) before any stronger claim.
7. Set up the user's own projects with AI Baton (the list and order are kept privately; ask the user first).
8. Optionally remove the old project hooks from projects set up before the global hooks (global hooks cover them; ask the user first).
8a. Bug (Codex, 2026-10-28): MCP checkpoints pass the conversation's start as the turn start, so after one handoff update every later checkpoint of that conversation is flagged handoff_updated; advance the baseline per checkpoint.
9. Hardening (Codex review of the reviewing badge, 2026-10-27): `project.write_text` follows symlinks (wanted for user settings files), so a symlink planted in `.agent-memory/` (activity.json, checkpoints) would redirect AI Baton's writes; reviews.json already refuses symlinks. Decide whether memory files should refuse symlinks too.
