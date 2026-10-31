# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-31, Claude

## Now (2026-10-31)
- Privacy cleanup done: Codex transcripts under `bench/frozen*/` contained the user's private settings (Codex system prompt; no credentials). History rewritten from the first affected commit and force-pushed (main, bench-pilot2, handoff-requirements; tags untouched); `bench/redact.py` now strips agent configuration before a rollout is saved. GitHub Support was asked to drop cached views of the old commits (pending). A local pre-commit/pre-push guard with a private word list (outside the repo) blocks such leaks. User rule: nothing private may ever reach this public repo; check every diff, including archives and bundles.
- 0.5.2 prepared (branch `release-0.5.2`): panel froze when Claude reported a limit window without a reset time (fixed, PR #14) + the requirements rule (PR #13). Codex review before the release was requested by the user.
- Next feature (DECISIONS 2026-10-31): a context-size indicator per active session in the panel, with a warning that suggests saving and `/clear`. Shared chat deferred; gateway is agent configuration, not an AI Baton feature.
- Antigravity (Google) as a user agent: a local MCP config (`.agents/`, machine-specific, never commit) starts `baton mcp --agent antigravity`; server handshake verified, real client load/save not yet. `baton review` supports Claude/Codex only.

## Current state
AI Baton 0.5.1 (preview) is PUBLISHED on the VS Code Marketplace and Open VSX (`wwijatkowski.ai-baton`, 2026-10-28; every release since v0.4.0 is published by `release.yml` from its version tag, with a GitHub release holding the .vsix). The repo `github.com/wwijatkowski/ai-baton` is public.
- CLI (`baton/`, Python 3.9+, 3.11+ on Windows, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (60, plus extension flows and webviews in Node); CI on Linux, Windows and macOS for every push and PR. Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, six rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-<version>.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` is verified (EclipseFdn/open-vsx.org#14730 closed 2026-10-26), Publisher Agreement signed, nothing published there yet. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-28)
- 0.5.1 released (native Copilot hooks; see git history and CHANGELOG).
- Measuring what AI Baton saves (plan: `docs/knowledge/SAVINGS_PLAN.md`; benchmark in `bench/`, run with `python3 bench/run.py ...`, real agents, Sonnet for B):
  - Pilots 1-2 (task described in the repo): every run completed in every arm; AI Baton saved no tokens (about 2k tokens of fixed context per new conversation).
  - Pilot 3 (feature specified only in the previous chat): completed: AI Baton 2/4, pasted final reply 0/4, nothing 0/4, original request pasted again 4/4.
  - Pilot 3b, after an AGENTS.md rule change (for work that is left, copy the user's requirements as given): AI Baton 3/4; the miss was an ambiguous spacing in the task's spec. Branch `handoff-requirements` (rule + 3b results).
  - Field data: `bench/metrics.py` (dev tool, not shipped) collects daily on the user's machine via a LaunchAgent (`bench/collect-daily.sh`, installed by the user).
- Dropped after Codex review: a hook-context trim (hid reply-only facts), saving all user prompts (mostly short noise).

## Next steps (in this order)
Releasing (no stored tokens, see 1): bump the version and add a CHANGELOG section in a PR, merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`. `release.yml` then tests, publishes to both stores and creates the GitHub release; the stores show the new version about 5 minutes later.
1. Done 2026-10-26: releases need no stored tokens. 0.4.1 was the first release published this way: the Marketplace as the managed identity, Open VSX through trusted publishing. Neither fallback ran, so the fallbacks were removed. Setup:
   - Marketplace: managed identity `ai-baton-release` (resource group `ai-baton-release`, West Europe). Its federated credential subject is `repo:wwijatkowski@37709252/ai-baton@1434103333:environment:release` (GitHub's numeric-id format). Secrets `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`. Azure DevOps id `871d2ee6-b125-6f1a-b920-3940cbfd884f` is a Contributor of publisher wwijatkowski. Check rights with `vsce verify-pat wwijatkowski --azure-credential`; a skipped duplicate publish proves nothing.
   - Open VSX: trusted publisher registered for `release.yml`, environment `release`.
   - Done: the Reader member on the Marketplace publisher was removed; both tokens were revoked by the user and the VSCE_PAT/OVSX_PAT secrets deleted. The only release secrets are AZURE_CLIENT_ID and AZURE_TENANT_ID (identifiers, not credentials).
2. Optional: a manual look at the VS Code panel on Windows. CI covers the CLIs, hooks and the extension host, not the rendered webview.
3. Publisher display name (waiting for VSMarketplace@microsoft.com). The user does not want promotional posts for now.
4. Listing (0.4.1, released): display name "AI Baton: Claude Code & Codex memory, handoff, review" for Marketplace search (it weighs the name most; the id stays, so it can go back to "AI Baton" any time), wider keywords, Cursor/Windsurf via Open VSX in the description. The README starts with `media/screenshots/demo.gif` (33 s, 1.6 MB): recorded by Claude desktop with `screencapture -v` in a throwaway project, cut and sped up with ffmpeg; the raw video is `~/Movies/ai-baton-demo.mov`.
5. Done: 0.5.0 released; Copilot hooks built on `copilot-hooks`.
6. Done 2026-10-28: 0.5.1 released.
7. Done: the requirements rule merged (PR #13), ships in 0.5.2. Next: the README benefits section: lead with memory/continuity; one bounded statement from `bench/results/*-pilot3b/SUMMARY.md` (small sample, one direction, completions not token savings). A stronger claim needs more tasks and the Claude-to-Codex direction.

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
