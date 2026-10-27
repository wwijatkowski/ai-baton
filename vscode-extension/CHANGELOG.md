# Changelog

## 0.5.0 (preview)

- Agents without hooks (Copilot, Cline, Continue, Gemini and other MCP clients) can share AI Baton's memory through its local MCP server, `baton mcp --agent <id>`: tools `baton_context`, `baton_checkpoint` and `baton_recall`. Their checkpoints show up in Recent work and reach Claude and Codex.
- Connect memory: one click on GitHub Copilot's card gives it these tools, through VS Code's MCP provider API (no settings file is edited); Disconnect turns them off. Add agent offers Copilot Chat again now that VS Code ships it built in.
- Claude Code keeps saving checkpoints after the agent runs `cd` into another folder (e.g. a sibling repo from `additionalDirectories`): hooks find the project from the folder the session started in. Before, that session saved nothing more and looked busy to other conversations for up to 45 minutes.
- Claude Code hook files run by another agent (GitHub Copilot in VS Code can read them) no longer count as Claude's turns.
- The context a new chat gets stays within its size budget however many agents saved checkpoints: the newest come first, older ones arrive with the next prompt.

## 0.4.2 (preview)

- A new chat gets the agent's own latest checkpoint from its other conversations, not only other agents' checkpoints: one agent alone carries its work into the next chat, and parallel chats see each other's progress.
- Ask for review: any agent can review, as configured or with another model and effort for that review only (e.g. a cheap model for everyday changes, a strong one for big ones). The last choice per agent is offered again. CLI: `baton review --agent claude --model opus --effort high`.

## 0.4.1 (preview)

- Clearer Marketplace listing: name, description and keywords say what AI Baton works with (Claude Code, Codex; VS Code, Cursor and Windsurf through Open VSX).
- A short demo at the top of the README: one agent picks up and reviews the other's work.

## 0.4.0 (preview)

- Windows support (Python 3.11 or newer): the CLI, memory hooks and the CLI installer work on Windows; Python is found through the `py` launcher or `python`.
- Two conversations of the same agent no longer overwrite each other's working state; a second chat is warned that the first one is still working.
- Cancelling a review on Windows also stops the reviewing agent the CLI started.
- Tests run on Linux, Windows and macOS for every change, including the extension in a real VS Code and the real Claude Code and Codex CLIs running the hooks.

## 0.3.0 (preview)

First public preview.

- Shared memory between Claude Code and Codex through lifecycle hooks, installed once for all projects.
- Project knowledge in `AGENTS.md` and `docs/`; Initialize project sets it up.
- Ask for review: another agent critiques the current changes read-only; send the review back to the author's conversation.
- Recent work: sessions with saved checkpoints and their summaries; reopen conversations.
- Usage per day and plan limits; model and effort pickers for new conversations.
- Add, remove and find agents; warnings when hooks are missing or not approved.
- `baton uninstall-hooks` removes the memory hooks from the agents' settings.
