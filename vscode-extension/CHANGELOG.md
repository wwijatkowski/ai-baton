# Changelog

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
