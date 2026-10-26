# AI Baton

**A conductor for your AI coding agents.** Claude Code, Codex and others take turns on one project without losing context, and a second agent can review the first one's work.

> Preview. Works with the Claude Code and Codex extensions for VS Code, on macOS and Linux.

## What it does

- **Shared memory between agents.** When an agent finishes a turn, AI Baton saves a short checkpoint. The next agent, or the same one in a new chat, starts with what the others did, without you retelling it. Everything stays in your project (`.agent-memory/`, ignored by git).
- **Project knowledge in plain files.** `AGENTS.md` holds one set of rules for every agent; `docs/AGENT_HANDOFF.md`, `docs/STATUS.md` and `docs/knowledge/DECISIONS.md` hold the current state, progress and decisions.
- **Ask for review.** Pick the conversation that made the changes, pick another agent, and it critiques the current changes read-only: at least three ranked points with fixes. Send the review back to the author's conversation; the author says what it accepts and waits for your "ok" before changing code. Agents can also do this themselves when you say "ask Codex".
- **Recent work.** Every agent session in the project, newest first, with its summary; reopen a conversation or start a review from it.
- **Usage and limits.** Tokens per day per agent, for this project or all, and the plan limits each agent last reported.
- **Agents at a glance.** Model and effort for new conversations, which agent is working, and a warning when memory hooks are missing or not yet approved.

## Getting started

1. Install AI Baton and at least one of [Claude Code](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) or [Codex](https://marketplace.visualstudio.com/items?itemName=openai.chatgpt).
2. Open a project folder and click the baton icon in the activity bar.
3. Click **Initialize project**. AI Baton offers to install its memory hooks once for all projects, then adds `AGENTS.md`, `CLAUDE.md` and `docs/` (existing files are never overwritten).
4. Codex only: approve the hooks once. In the Codex chat box, click the hooks button next to the model picker ("Review hooks"), then **Allow all**. The panel shows a reminder until you do.

Start a new chat in either agent. From the second agent on, each one knows what the others did.

## Requirements

- macOS or Linux. Windows is not supported yet.
- Python 3.9 or newer as `python3` (on macOS: `xcode-select --install`), or set `aiBaton.python`.
- The Claude Code and/or Codex VS Code extension. Other agents (Copilot, Cline, Continue, ...) can be added to the panel, but do not share memory yet.

## What AI Baton reads and writes

It runs locally. The memory hooks never use the network or call a model.

**Reads**
- Claude Code and Codex logs, for token usage: `~/.claude/projects/`, `~/.codex/sessions/`.
- Their cached plan limits and model settings: `~/.claude.json`, `~/.claude/settings.json`, `~/.codex/config.toml`.

**Writes, after you agree**
- Memory hooks in `~/.claude/settings.json` and `~/.codex/hooks.json`. They run `~/.ai-baton/bin/baton` and do nothing outside projects set up for AI Baton.
- The model and effort you pick, in the same settings files.
- In a project: `AGENTS.md`, `CLAUDE.md`, `docs/`, and `.agent-memory/` (added to `.gitignore`).
- Its own files: `~/.ai-baton/` (the command-line tool), `~/.config/ai-baton/agents.json`, `~/.cache/ai-baton/`.

**Network**
- **Find agents** reads the public VS Code Marketplace listing.
- **Ask for review** runs the reviewing agent's own command-line tool, which uses that agent's account and plan.

No telemetry.

## Good to know

AI Baton relies on details of Claude Code and Codex that are not public APIs: log and transcript formats, the cached plan usage, the links that reopen a conversation, and how Codex reports hook approval. An update to either agent can break a feature until AI Baton catches up. The rest keeps working.

## Commands

- **AI Baton: Switch Agent** (`Cmd+Alt+A` / `Ctrl+Alt+A`)
- **AI Baton: Ask Another Agent for a Review**
- **AI Baton: Show Recent Work**
- **AI Baton: Initialize Project**, **Add Agent**, **Remove Agent**, **Add Decision**, **Open Handoff**, **Copy Handoff Request**

## Settings

- `aiBaton.python`: the Python interpreter (default `python3`).
- `aiBaton.home`: leave empty to use the bundled command-line tool; set a folder to use a development checkout.
- `aiBaton.usageDays`, `aiBaton.refreshSeconds`: usage chart range and refresh interval.

## License

Source-available under the [PolyForm Shield License 1.0.0](LICENSE): free for any use, including at work, except building a product that competes with AI Baton. Source and issues: [github.com/wwijatkowski/ai-baton](https://github.com/wwijatkowski/ai-baton).
