# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-26, Claude

## Current state
AI Baton 0.3.0 (preview) is ready to publish, pending a real-install check. Everything below is committed and pushed to the private repo `github.com/wwijatkowski/ai-baton`.
- CLI (`baton/`, Python 3.9+, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (50, pass on Python 3.11 and the macOS system 3.9). Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, six rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-0.3.0.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` waits for EclipseFdn/open-vsx.org#14730. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-26)
- Real package installed (`wwijatkowski.ai-baton` 0.3.0 from the .vsix); hooks call `~/.ai-baton/bin/baton`; Codex hooks re-approved. The installer only replaces `~/.ai-baton` when the version changes, so after rebuilding 0.3.0 its CLI was copied into `~/.ai-baton/versions/0.3.0` by hand.
- `baton review` works without git (shadow snapshots, or a file list without git) and reviews a conversation's replies when no files changed (DECISIONS 2026-10-26).
- UI round 5 (docs/UI_TEST_REPORT.md): 16 PASS, 2 FAIL. Fixed both: D6 (first conversation without git had no "before": baseline snapshot at init/first prompt, `refs/baton/baseline`) and X (New chat did nothing without an open Claude view: `editor.open` + `pin-to-panel`). Also: "Setting up…" progress on Initialize, a hint when there is no conversation to review, Restricted Mode notes in README and MANUAL_TEST. Codex reviewed the fixes; all 5 points applied (bounded baseline, retry after failure, no git filters in snapshots, marked baseline only, New chat without changing Claude's preferred location).
- UI round 6 + 6b: baseline and review without git pass; New chat first failed (`null` in `newArgs` reached Claude Code as a session id), fixed (null -> undefined, command failures shown as an error) and passed on retest. MANUAL_TEST section 7: every round ends by closing its windows and deleting its test folders.
- Tests: 50 pass (3.11 and 3.9). First prompt in a 3000-file project without git: 1.5 s (one-time snapshot), then 0.05 s.

## Next steps (in this order)
1. User takes 3 screenshots into `vscode-extension/media/screenshots/` (panel with agents and Recent work; the "whose work?" picker; a review tab with the Send-to notification); add them to the README.
2. Publish: make `ai-baton` public; upload the .vsix on marketplace.visualstudio.com/manage (or `vsce publish --azure-credential` after `az login`, untested); Open VSX after #14730 closes.

## How we work (user's preferences)
- Reply in Polish; docs in English. Ask before outward or destructive actions (pushes to other repos, history rewrites, deleting memory).
- After significant changes run `baton review --agent codex` (diff + ranked critique), check each point, list accept/reject/defer, and wait for the user's "ok" before changing code.
- Never name the user's private projects in this repo; commits use the noreply address set in the repo's git config.
- Start a new chat when a conversation gets long: the previous one reached about 780k tokens of context, and each turn re-read it.

## Open issues / risks
- Review infers a conversation's start from the checkpoint before its first one; wrong when another agent checkpoints during that first turn (deferred, see DECISIONS).
- Linux and Windows untested (no Docker here); preview targets macOS and Linux.
- No tests for `extension.js` flows (roadmap item 5).
- Activity is one entry per agent: two sessions of the same agent overwrite each other's working state.
- Codex was briefly "at capacity" during a review; `baton review` reports such failures as errors.
