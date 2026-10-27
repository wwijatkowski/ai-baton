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

## To do
1. Done: 0.4.1 published on the VS Code Marketplace and Open VSX by `release.yml` from a version tag, with no stored tokens (Azure managed identity, Open VSX trusted publishing). Left: publisher display name.
2. Shared memory for agents without hooks (Copilot, Cline, Gemini, Continue, ...), one approach for all:
   - Main path, done (unreleased): `baton mcp --agent ID`, a local stdio MCP server with `baton_context`, `baton_checkpoint` and `baton_recall` (DECISIONS 2026-10-27). Verified with Claude Code as a real MCP client (connects in CI; a Haiku run called both tools). `baton install-mcp --agent copilot` (VS Code's user mcp.json) and Connect memory in the panel; verified live with Copilot Free in VS Code (read Codex's checkpoint, saved its own, Claude's hook got it). Left: other agents' MCP configs (Cline, Gemini, Continue: each its own file and format) once they can be tested; Copilot's native hooks (VS Code Preview: sessionStart context, Stop without the reply) as a possible replacement for MCP there; check that VS Code's Local harness reading Claude's hook files (`chat.useClaudeHooks`) cannot run `baton hook claude` for Copilot.
   - Fallback: the extension infers a checkpoint when the handoff doc or git changes while a hook-less agent was the last one opened (marked as inferred).
   - Per agent, use native hooks where they exist (check each agent's docs when adding it).
3. Done (unreleased): an agent gets its own latest checkpoint from its other conversations (new chat, or one running in parallel); review by any agent with a model and effort for that review only. Released in 0.4.2. Small ideas left: let the panel take a model id typed by hand (the CLI already does); a review run should not count as Claude's "last used" model (`models.claude_last_model` reads the newest transcript, which can be the reviewer's); the CLI installer (`cli-install.js`) should compare the bundled CLI's content, not only its version, so a test .vsix with an unchanged version still updates `~/.ai-baton` (UI test round 7).
4. More reviewers for `baton review`: agents with a headless CLI (check Gemini CLI, Copilot CLI) get a runner in `review.py` and `"review"` in the registry; panel-only agents (Cline, Continue) cannot review.
5. Done (0.4.0): Windows support, CI on Linux/Windows/macOS (unit tests plus the extension in a real VS Code), extension.js flow tests with a fake VS Code API, activity per conversation. Left: a manual check with the real Claude and Codex extensions on Windows.
6. Measure whether project memory saves tokens (tokens spent before real work starts, before vs after init).
7. Set up the user's own projects with AI Baton (the list and order are kept privately; ask the user first).
8. Optionally remove the old project hooks from projects set up before the global hooks (global hooks cover them; ask the user first).
