# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-27 (late evening), Claude

## Current state
AI Baton 0.5.0 (preview) is PUBLISHED on the VS Code Marketplace and Open VSX (`wwijatkowski.ai-baton`, 2026-10-27; every release since v0.4.0 is published by `release.yml` from its version tag, with a GitHub release holding the .vsix). The repo `github.com/wwijatkowski/ai-baton` is public.
- CLI (`baton/`, Python 3.9+, 3.11+ on Windows, stdlib only): global memory hooks for Claude and Codex, tiered memory, `review`, `recent`, `hook-status`, `install-hooks`, `uninstall-hooks`.
- Extension (`vscode-extension/`): agents, Recent work, Ask for review, usage and limits. The .vsix bundles the CLI and installs it to `~/.ai-baton` on activation (stable launcher `bin/baton` for hooks).
- Tests: `python3 -m unittest discover -s tests` (60, plus extension flows and webviews in Node); CI on Linux, Windows and macOS for every push and PR. Real agents: `sh tests/e2e_agents.sh`. UI: `docs/MANUAL_TEST.md`, six rounds by Claude desktop in `docs/UI_TEST_REPORT.md`.
- Package: `sh scripts/package.sh` builds `ai-baton-<version>.vsix` (gitignored) and checks its contents.
- Publishing accounts: Marketplace publisher `wwijatkowski` (extension id `wwijatkowski.ai-baton`); Open VSX namespace `wwijatkowski` is verified (EclipseFdn/open-vsx.org#14730 closed 2026-10-26), Publisher Agreement signed, nothing published there yet. Repo history is clean (noreply author, no private project names); the full old history is in the private repo `ai-baton-history` and `~/ai-baton-full-history-2026-10-26.bundle`.

## Recently done (2026-10-27)
- Released 0.5.0: `baton mcp` (memory tools for agents without hooks; Copilot via VS Code's MCP provider, Connect memory on its card), Claude hooks keep their project after `cd` (CLAUDE_PROJECT_DIR).
- Branch `copilot-hooks` (unreleased, 5 commits, no PR yet), all tests green (86 Python, 32 extension flows, webview smoke, e2e_hooks with the real CLIs):
  - Native Copilot hooks (DECISIONS 2026-10-27): our own `$COPILOT_HOME/hooks/ai-baton.json`, installed only when named (Install hooks on the Copilot card); SessionStart gives full context + native session_id; Stop saves the turn's final answer from `events.jsonl` (fails closed, once per reply per conversation, receipts in `.agent-memory/.copilot-stops.json`); MCP stops asking for baton_checkpoint only when the hook ran in that chat. Evidence: a payload capture in the real runtime (copilot-agent 1.0.100). Codex reviewed the design (high) and three code rounds (xhigh); all accepted points are in.
  - Review fixes: model typed by hand ("Other model…"); Claude reviews use `--session-id` recorded in `~/.cache/ai-baton/review-sessions.json` so they never set "last used" (tokens still counted); the CLI installs into `versions/<version>-<BUILD>` (content hash), so a test .vsix with the same version updates `~/.ai-baton`; `tests/vscode/suite.js` expects that.
  - A purple "reviewing" badge while an agent runs `baton review` (`.agent-memory/reviews.json`, best effort, never touches checkpoints/activity).
- Not verified live yet: that Copilot's model receives the hook context, multi-turn SessionStart behaviour, reload, install with a chat open. This is the release gate for 0.5.1.

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
6. Next: an automated live test harness (Codex's plan, 2026-10-27): a separate opt-in runner beside `tests/vscode/run.js` with a persistent test VS Code profile in `~/.cache/ai-baton/` (Copilot signed in once by the user), isolated HOME/COPILOT_HOME, a tiny driver extension that submits chat via `workbench.action.chat.open` {mode: 'agent', query, isPartialQuery: false, blockOnResponse: true} (`code chat` always opens a new chat), random sentinel codenames asserted from `events.jsonl` with an independent parser, cap 8 Copilot messages per round. Claude desktop only clicks panel buttons and takes screenshots. Then run round 10 with it, then the 0.5.1 release PR (Codex xhigh review first).

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
