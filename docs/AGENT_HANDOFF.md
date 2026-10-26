# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-26 (evening), Claude

## Current state
AI Baton 0.3.0 (preview) is PUBLISHED on the VS Code Marketplace (`wwijatkowski.ai-baton`, 2026-10-26). The repo `github.com/wwijatkowski/ai-baton` is public.
- CLI (`baton/`, Python 3.9+, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (56, plus extension flows and webviews in Node); CI on Linux, Windows and macOS for every push and PR. Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, six rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-0.3.0.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` waits for EclipseFdn/open-vsx.org#14730. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-26, branch `cross-platform-ci`, PR #1)
- Windows support (native, not WSL), all verified in CI only:
  - portable file lock (fcntl/msvcrt, 3 s);
  - UTF-8 for every file and pipe, LF for files git reads (a `\r` in `alternates` broke reviews without git);
  - reader thread instead of `select` in hookcheck;
  - bounded process-tree kill (`project.kill_tree`, `taskkill /T`) in review, hookcheck and the extension (cancel and its own timeout);
  - review prompt goes through stdin for `.cmd`/`.bat` reviewers;
  - git watchdog detects its own kill (Windows exit code is 1);
  - binaries found with `.exe`;
  - usage paths normalized.
- Hooks on Windows: Claude in exec form (`command` + `args`), Codex as a quoted forward-slash command line. Recognition (`hook_text`, regex with `[/\\]`) covers both. Commands on macOS/Linux are unchanged.
- Installer: `current-version` pointer file (the `current` symlink is kept on POSIX); migration from symlink installs tested.
- Extension: Python lookup (`py -3`, `python`, `python3` on Windows when the setting is the default); `activate` returns `{ state }` for the integration test.
- Activity per conversation (`activity.json[agent].sessions`, see DECISIONS).
- Tests (all green, 9 CI jobs):
  - `python3 -m unittest discover -s tests`: 56 tests;
  - `tests/extension_flows.js`: 22 flows with a fake VS Code API;
  - `tests/vscode/`: real VS Code, runs the installed Claude and Codex hook commands. Locally: `sh scripts/bundle-cli.sh`, then `npm install --no-save --prefix tests/vscode @vscode/test-electron@3.1.0`, then `node tests/vscode/run.js`. It needs `--use-mock-keychain` on macOS, or a "Keychain Not Found" dialog blocks.
  - CI: `.github/workflows/test.yml`.
- Two Codex reviews of the plan and the diff; accepted points applied (see DECISIONS).

## Next steps (in this order)
1. User: review and merge PR #1 (squash or merge), then delete the branch.
2. Release 0.3.1 (or 0.4.0): bump the version, `sh scripts/package.sh`, upload on the Marketplace manage page; CHANGELOG has an Unreleased section.
3. Manual check on a real Windows machine with the Claude and Codex extensions: hooks fire, Codex approves them, review works. The shell Codex uses for `commandWindows`/`command` on Windows is unverified.
4. Publisher display name (waiting for VSMarketplace@microsoft.com), Open VSX after EclipseFdn/open-vsx.org#14730.
5. Optional: announcement post.

## How we work (user's preferences)
- Reply in Polish; docs in English. Ask before outward or destructive actions (pushes to other repos, history rewrites, deleting memory).
- After significant changes run `baton review --agent codex` (diff + ranked critique), check each point, list accept/reject/defer, and wait for the user's "ok" before changing code.
- Never name the user's private projects in this repo; commits use the noreply address set in the repo's git config.
- Start a new chat when a conversation gets long: the previous one reached about 780k tokens of context, and each turn re-read it.

## Open issues / risks
- Review infers a conversation's start from the checkpoint before its first one; wrong when another agent checkpoints during that first turn (deferred, see DECISIONS).
- Windows: tested only in CI (no real Claude/Codex there). Codex hook command paths with `$`, backticks or `%` may break if Codex runs them through a shell.
- The real-VS-Code test does not check the webview itself (`tests/webview_smoke.js` renders it in a fake DOM).
- Codex was briefly "at capacity" during a review; `baton review` reports such failures as errors.
