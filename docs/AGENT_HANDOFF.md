# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-26 (evening, Open VSX namespace verified), Claude

## Current state
AI Baton 0.4.0 (preview) is PUBLISHED on the VS Code Marketplace and Open VSX (`wwijatkowski.ai-baton`, 2026-10-26, first automated release from the `v0.4.0` tag via `release.yml`; GitHub release with the .vsix). The repo `github.com/wwijatkowski/ai-baton` is public.
- CLI (`baton/`, Python 3.9+, 3.11+ on Windows, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (56, plus extension flows and webviews in Node); CI on Linux, Windows and macOS for every push and PR. Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, six rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-0.3.0.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` is verified (EclipseFdn/open-vsx.org#14730 closed 2026-10-26), Publisher Agreement signed, nothing published there yet. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-26, branch `cross-platform-ci`, PR #1)
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
Releasing: secrets VSCE_PAT and OVSX_PAT are set. Bump the version and add a CHANGELOG section in a PR, merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`. `release.yml` then tests, publishes to both stores and creates the GitHub release; the stores show the new version about 5 minutes later.
1. Now that Open VSX has the extension:
   - Done 2026-10-26: the Reader member added to the Marketplace publisher for the namespace claim is removed.
   - Open VSX trusted publishing: registered 2026-10-26 (owner `wwijatkowski`, repo `ai-baton`, workflow `release.yml`, environment `release`); `release.yml` publishes with `--trusted-publishing` and falls back to OVSX_PAT with a warning. After the next release: if the publish job shows no fallback warning, remove the fallback step, then the user deletes the OVSX_PAT secret and the token on open-vsx.org.
2. Marketplace without a PAT (global PATs stop working on 2026-12-01). Set up 2026-10-26:
   - Managed identity `ai-baton-release` in resource group `ai-baton-release` (West Europe, user's subscription).
   - Federated credential subject `repo:wwijatkowski@37709252/ai-baton@1434103333:environment:release`. GitHub now sends owner and repo with their numeric ids; the plain `repo:wwijatkowski/ai-baton:...` form did not match.
   - Secrets `AZURE_CLIENT_ID` and `AZURE_TENANT_ID`.
   - The identity's Azure DevOps id `871d2ee6-b125-6f1a-b920-3940cbfd884f` is added by the user as Contributor of publisher wwijatkowski.
   - `release.yml` signs in with `azure/login@v2` and publishes with `--azure-credential`, falling back to VSCE_PAT with a warning.
   Verified 2026-10-26 from a temporary workflow: the identity signs in and `vsce verify-pat wwijatkowski --azure-credential` succeeds (a role check; a skipped duplicate publish proves nothing, vsce only reads the version list). After the first release without the fallback warning, remove the fallback step; the user deletes VSCE_PAT and the Azure DevOps token.
3. Optional: a manual look at the VS Code panel on Windows. CI covers the CLIs, hooks and the extension host, not the rendered webview.
4. Publisher display name (waiting for VSMarketplace@microsoft.com). Optional: announcement post.

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
