# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-26, Claude

## Current state
AI Baton 0.3.0 (preview) is ready to publish, pending a real-install check. Everything below is committed and pushed to the private repo `github.com/wwijatkowski/ai-baton`.
- CLI (`baton/`, Python 3.9+, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (51, pass on Python 3.11 and the macOS system 3.9). Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, four rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-0.3.0.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` waits for EclipseFdn/open-vsx.org#14730. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-26)
- Fixed an outage: concurrent Stop hooks damaged the gzip history archive and crashed the panel. History writes are locked (`.agent-memory/.history.lock`), the archive reader skips damaged members.
- README for the Marketplace corrected after two Codex reviews (what is stored and written, review prerequisites, uninstall steps that keep the user's docs, license wording). `baton uninstall-hooks` removes only exact AI Baton hook commands.

## Next steps (in this order)
1. User installs the real package: uninstall the old dev copy "AI Baton" (`wiktor.ai-baton`), then Extensions: Install from VSIX… `~/ai-baton/ai-baton-0.3.0.vsix`, then Developer: Reload Window. Expect `~/.ai-baton/` to appear (bin, current, versions) and the panel to work. The user's hooks still point at `~/ai-baton` (this checkout); fine for now.
2. UI test round 5 in Claude desktop on the installed package, including Initialize project in a fresh git folder (`docs/MANUAL_TEST.md` sections 1, 4, 5b). Fix what it finds before screenshots.
3. User takes 3 screenshots into `vscode-extension/media/screenshots/` (panel with agents and Recent work; the "whose work?" picker; a review tab with the Send-to notification); add them to the README.
4. Publish: make `ai-baton` public; upload the .vsix on marketplace.visualstudio.com/manage (or `vsce publish --azure-credential` after `az login`, untested); Open VSX after #14730 closes.

## How we work (user's preferences)
- Reply in Polish; docs in English. Ask before outward or destructive actions (pushes to other repos, history rewrites, deleting memory).
- After significant changes run `baton review --agent codex` (diff + ranked critique), check each point, list accept/reject/defer, and wait for the user's "ok" before changing code.
- Never name the user's private projects in this repo; commits use the noreply address set in the repo's git config.
- Start a new chat when a conversation gets long: the previous one reached about 780k tokens of context, and each turn re-read it.

## Open issues / risks
- Linux and Windows untested (no Docker here); preview targets macOS and Linux.
- No tests for `extension.js` flows (roadmap item 5).
- Activity is one entry per agent: two sessions of the same agent overwrite each other's working state.
- Codex was briefly "at capacity" during a review; `baton review` reports such failures as errors.
