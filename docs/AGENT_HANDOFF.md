# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-27, Claude

## Current state
AI Baton 0.4.0 (preview) is PUBLISHED on the VS Code Marketplace and Open VSX (`wwijatkowski.ai-baton`, 2026-10-26, first automated release from the `v0.4.0` tag via `release.yml`; GitHub release with the .vsix). The repo `github.com/wwijatkowski/ai-baton` is public.
- CLI (`baton/`, Python 3.9+, 3.11+ on Windows, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (60, plus extension flows and webviews in Node); CI on Linux, Windows and macOS for every push and PR. Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, six rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-0.3.0.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` is verified (EclipseFdn/open-vsx.org#14730 closed 2026-10-26), Publisher Agreement signed, nothing published there yet. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-27, branch `review-model-own-checkpoint`, unreleased)
- Hooks deliver an agent's own latest checkpoint when another conversation of it saved it (`build_context` in `baton/hook.py`, labelled "[claude, your other conversation]"). One agent alone keeps its thread across new chats; parallel chats see each other's work once.
- `baton review --model M --effort E` for that run only (`reviewer_choice` in `baton/review.py`); the effort is checked against the effective model (chosen, else configured, else the agent's default). Panel step 2/3 lists each reviewer as configured, its last successful review choice, and "another model or effort…" (model pick, then effort pick).
- Verified: 60 unit tests, 25 extension flows, `tests/e2e_hooks.py` with the real CLIs (now also checks own-checkpoint delivery), real `claude --model=haiku --effort=low` and `codex exec --model=gpt-6-luna -c model_reasoning_effort="low"` runs. Codex reviewed the diff: points 1 (effort vs effective model) and 3 (remember only after a successful run) applied; 2 (typed model id in the panel) deferred to STATUS.
- Not yet checked by a person in the VS Code panel (docs/MANUAL_TEST.md 5b describes it).

## Earlier (2026-10-26, branch `cross-platform-ci`, PR #1)
- Windows support (native, not WSL, Python 3.11+), verified in CI including the real agent CLIs:
  - portable file lock (fcntl/msvcrt, 3 s);
  - UTF-8 for every file and pipe, LF for files git reads (a `\r` in `alternates` broke reviews without git);
  - reader thread instead of `select` in hookcheck;
  - bounded process-tree kill (`project.kill_tree`, `taskkill /T`) in review, hookcheck and the extension (cancel and its own timeout);
  - review prompt goes through stdin for `.cmd`/`.bat` reviewers;
  - git watchdog detects its own kill (Windows exit code is 1);
  - binaries found with `.exe`;
  - usage paths normalized.
- Hooks on Windows: Claude in exec form (`command` + `args`). Codex runs hooks in PowerShell with an empty environment, so its command is `C:/.../python.exe "C:/.../bin/baton" hook codex --global` (unquoted interpreter, 8.3 name if needed) and `baton/winenv.py` restores the environment. Recognition (`hook_text`, regex with `[/\\]`) covers all forms. Commands on macOS/Linux are unchanged.
- `tests/e2e_hooks.py`: the real Claude Code and Codex CLIs (npm, latest) run the installed hooks with no login and no tokens. It checks Codex approval via `hook-status` and context delivered between the agents. CI job `agents` runs it on 3 systems, plus weekly. On failure it prints Codex's own hook results (via app-server `hook/completed`).
- Installer: `current-version` pointer file (the `current` symlink is kept on POSIX); migration from symlink installs tested.
- Extension: Python lookup (`py -3`, `python`, `python3` on Windows when the setting is the default); `activate` returns `{ state }` for the integration test.
- Activity per conversation (`activity.json[agent].sessions`, see DECISIONS).
- Tests (all green, 12 CI jobs: unit ×3 systems ×2 Pythons, real VS Code ×3, real agent CLIs ×3):
  - `python3 -m unittest discover -s tests`: 56 tests;
  - `tests/extension_flows.js`: 22 flows with a fake VS Code API;
  - `tests/vscode/`: real VS Code, runs the installed Claude and Codex hook commands. Locally: `sh scripts/bundle-cli.sh`, then `npm install --no-save --prefix tests/vscode @vscode/test-electron@3.1.0`, then `node tests/vscode/run.js`. It needs `--use-mock-keychain` on macOS, or a "Keychain Not Found" dialog blocks.
  - CI: `.github/workflows/test.yml`.
- Two Codex reviews of the plan and the diff; accepted points applied (see DECISIONS).

## Next steps (in this order)
Releasing (no stored tokens, see 1): bump the version and add a CHANGELOG section in a PR, merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`. `release.yml` then tests, publishes to both stores and creates the GitHub release; the stores show the new version about 5 minutes later.
1. Done 2026-10-26: releases need no stored tokens. 0.4.1 was the first release published this way: the Marketplace as the managed identity, Open VSX through trusted publishing. Neither fallback ran, so the fallbacks were removed. Setup:
   - Marketplace: managed identity `ai-baton-release` (resource group `ai-baton-release`, West Europe). Its federated credential subject is `repo:wwijatkowski@37709252/ai-baton@1434103333:environment:release` (GitHub's numeric-id format). Secrets `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`. Azure DevOps id `871d2ee6-b125-6f1a-b920-3940cbfd884f` is a Contributor of publisher wwijatkowski. Check rights with `vsce verify-pat wwijatkowski --azure-credential`; a skipped duplicate publish proves nothing.
   - Open VSX: trusted publisher registered for `release.yml`, environment `release`.
   - Done: the Reader member on the Marketplace publisher was removed; both tokens were revoked by the user and the VSCE_PAT/OVSX_PAT secrets deleted. The only release secrets are AZURE_CLIENT_ID and AZURE_TENANT_ID (identifiers, not credentials).
2. Optional: a manual look at the VS Code panel on Windows. CI covers the CLIs, hooks and the extension host, not the rendered webview.
3. Publisher display name (waiting for VSMarketplace@microsoft.com). The user does not want promotional posts for now.
4. Listing (0.4.1, released): display name "AI Baton: Claude Code & Codex memory, handoff, review" for Marketplace search (it weighs the name most; the id stays, so it can go back to "AI Baton" any time), wider keywords, Cursor/Windsurf via Open VSX in the description. The README starts with `media/screenshots/demo.gif` (33 s, 1.6 MB): recorded by Claude desktop with `screencapture -v` in a throwaway project, cut and sped up with ffmpeg; the raw video is `~/Movies/ai-baton-demo.mov`.
5. Merge the PR for this branch, check the review picker by hand (MANUAL_TEST 5b), then release 0.4.2 (CHANGELOG has an Unreleased section).
6. Then: the MCP server for agents without hooks (STATUS To do 2).

## How we work (user's preferences)
- Reply in Polish; docs in English. Ask before outward or destructive actions (pushes to other repos, history rewrites, deleting memory).
- After significant changes run `baton review --agent codex` (diff + ranked critique), check each point, list accept/reject/defer, and wait for the user's "ok" before changing code.
- Never name the user's private projects in this repo; commits use the noreply address set in the repo's git config.
- Start a new chat when a conversation gets long: the previous one reached about 780k tokens of context, and each turn re-read it.

## Open issues / risks
- Review infers a conversation's start from the checkpoint before its first one; wrong when another agent checkpoints during that first turn (deferred, see DECISIONS).
- Windows: verified in CI with the real agent CLIs, not yet by a person in VS Code on Windows.
- The real-VS-Code test does not check the webview itself (`tests/webview_smoke.js` renders it in a fake DOM).
- Codex was briefly "at capacity" during a review; `baton review` reports such failures as errors.
