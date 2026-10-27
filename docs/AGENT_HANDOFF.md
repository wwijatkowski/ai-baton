# Agent handoff

A short, current state of the work for the next agent. Replace outdated content; do not keep history here (that is what Git and `docs/knowledge/` are for).

**Last updated:** 2026-10-28 (night, 0.5.1 release), Claude

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
- Live Copilot harness (`tests/live/`, 2026-10-27, branch `copilot-hooks`): `node tests/live/run.js setup` once (GitHub sign-in in its own profile, `~/.cache/ai-baton/live`; the test HOME links the real `~/Library/Keychains`: the login keychain is shared with your account, the token sits encrypted in the test profile, `clean` does not remove keychain items), then `round` (4 Copilot messages, cap 8). Verified with it, all assertions green: the SessionStart context reaches the model (random codename only in a Codex checkpoint), SessionStart runs on every turn as `resume` (also after a reload), so later turns get newer checkpoints; every reply saved once; a new chat gets the newest context. It found a real bug, fixed: Copilot runs Stop before the final answer reaches events.jsonl, so 3 of 4 replies were lost; Stop now waits up to 2 s for an unsaved reply (`COPILOT_REPLY_WAIT`), and the whole Copilot Stop has one 7 s deadline (`COPILOT_STOP_BUDGET`: lock and git change capture included; past it git is skipped). Codex review (high) of the harness: all 7 points accepted and in (exact save checks, per-turn hook checks, t2/t3 as assertions, quit outside the chat queue, bounded kill, runner lock, strict parser with `tests/live/events_test.js`).
- Hooks run only in **Copilot CLI** chats (`copilotcli`, the copilot-agent runtime); a "Local" chat runs none.
- 2026-10-28: the harness also covers round 10 E–F (7 messages a round), all green: t5 hooks + MCP tools (the test chat auto-approves tools via `chat.permissions.default`, set only for that chat; baton_context with the hook's session_id says the Stop hook saves, no baton_checkpoint call, one save); t6 hooks removed: no hook runs, nothing saved; t7 hooks installed with that chat open: its next turn runs SessionStart, knows the newest codename and is saved (INFO). Release bump 0.5.1 (README section "GitHub Copilot", CHANGELOG, install toast) committed on `copilot-hooks`.

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
6. Done 2026-10-28: 0.5.1 released from PR #10 (tag v0.5.1): native Copilot hooks, `baton review --base`, review fixes. Verified: unit tests, CI (Linux, Windows, macOS), live rounds with the real Copilot (all green, 7 messages), UI round 10 by Claude desktop (all PASS, `docs/UI_TEST_REPORT.md`), Codex reviews in five rounds (all accepted points in; the Copilot Stop now takes a per-conversation lock, writes checkpoint and receipt under the shared lock, every lock and Windows retry within its 7 s budget, at-least-once after a crash). Check the stores show 0.5.1 (about 5 minutes after the tag).
7. After 0.5.1: start collecting token-saving metrics now (STATUS To do 6); the user wants a summary after some weeks of real work.

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
