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
- PR #1 (cross-platform-ci): Windows support and CI; green on all 9 jobs, waiting for the user's merge.

## To do
1. Done: 0.3.0 preview published on the VS Code Marketplace (2026-10-26). Left: 0.4.0 to the Marketplace and Open VSX through `release.yml` (needs the VSCE_PAT and OVSX_PAT secrets, then a `v0.4.0` tag after PR #1), publisher display name.
2. Shared memory for agents without hooks (Copilot, Cline, Gemini, Continue, ...), one approach for all:
   - Main path: a local MCP server (`baton mcp`, stdio, no network) with tools `baton_context` (what the hooks inject at start) and `baton_checkpoint` (save a summary at the end). Most agents speak MCP; AGENTS.md tells them to call the tools. Checkpoints land in the same history, so Recent work and other agents see them.
   - Fallback: the extension infers a checkpoint when the handoff doc or git changes while a hook-less agent was the last one opened (marked as inferred).
   - Per agent, use native hooks where they exist (check each agent's docs when adding it).
3. Idea: give an agent its own latest checkpoint when it starts a new chat (today hooks deliver only the other agents' checkpoints; the same agent relies on the handoff docs).
4. More reviewers for `baton review`: agents with a headless CLI (check Gemini CLI, Copilot CLI) get a runner in `review.py` and `"review"` in the registry; panel-only agents (Cline, Continue) cannot review.
5. Done (branch cross-platform-ci): Windows support, CI on Linux/Windows/macOS (unit tests plus the extension in a real VS Code), extension.js flow tests with a fake VS Code API, activity per conversation. Left: a manual check with the real Claude and Codex extensions on Windows.
6. Measure whether project memory saves tokens (tokens spent before real work starts, before vs after init).
7. Set up the user's own projects with AI Baton (the list and order are kept privately; ask the user first).
8. Optionally remove the old project hooks from projects set up before the global hooks (global hooks cover them; ask the user first).
