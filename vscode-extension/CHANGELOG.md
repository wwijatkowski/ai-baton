# Changelog

## 0.3.0 (preview)

First public preview.

- Shared memory between Claude Code and Codex through lifecycle hooks, installed once for all projects.
- Project knowledge in `AGENTS.md` and `docs/`; Initialize project sets it up.
- Ask for review: another agent critiques the current changes read-only; send the review back to the author's conversation.
- Recent work: sessions with saved checkpoints and their summaries; reopen conversations.
- Usage per day and plan limits; model and effort pickers for new conversations.
- Add, remove and find agents; warnings when hooks are missing or not approved.
- `baton uninstall-hooks` removes the memory hooks from the agents' settings.
