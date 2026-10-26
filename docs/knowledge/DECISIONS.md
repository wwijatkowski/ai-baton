# Decisions

Lasting project decisions, newest first. Format: `## YYYY-MM-DD: title`, followed by the decision, the reasoning and who decided.

## 2026-10-26: "New chat" for Claude opens a new editor tab
- Decision: the Claude card's New chat runs `claude-vscode.editor.open` with `{"programmatic": "pin-to-panel"}` (`newArgs` in agents.json) instead of `claude-vscode.newConversation`.
- Reasoning: `newConversation` only acts on an already open Claude view, so in a fresh window it did nothing (UI round 5, X). `editor.open` always creates a new conversation tab; without the programmatic flag it would also switch the user's preferred Claude location to the editor.
- Decided by: Claude, after Codex review.

## 2026-10-26: Review works without git and reviews replies when no files changed
- Decision: `baton review` picks its input by what the project has. Git: uncommitted changes; with a chosen conversation and a clean tree, the commits since it began (the commit of the checkpoint just before its first one), or its replies when there are none or its start is unknown; without a conversation, the last commit as before. No repository: the shadow snapshots against the files now, staged in a throwaway repo that borrows the shadow objects, with `* -filter` in its info/attributes so no git filter program runs and the shadow repo is only read. No git installed: the conversation's changed files (recorded lists plus files modified after its last checkpoint), for the reviewer to read. The output says what was reviewed.
- Reasoning: many users do not work with git; "Review needs a git repository" and reviewing an unrelated older commit both misled. Codex review (accepted: unknown start, read-only shadow, incomplete file lists, cut-diff notes).
- Baseline (after UI round 5, D6): without a repository, `baton init` and the first SessionStart/UserPromptSubmit take one snapshot before any agent works, marked `refs/baton/baseline` in the shadow repo, within 5 s (else retried at the next prompt). A conversation with no checkpoint before it is compared with that baseline; an unmarked first commit is never used. Shadow snapshots (hooks too) set `* -filter` in the shadow repo's info/attributes.
- Deferred: the start of a conversation is inferred from the previous checkpoint, which is too late when another agent checkpoints during its first turn; recording it at the first prompt needs a hook change.
- Decided by: user (scope), Claude (design).

## 2026-10-25: Source-available under PolyForm Shield; preview on macOS and Linux, no telemetry
- Decision: license AI Baton under PolyForm Shield 1.0.0 (`LICENSE`, copy in `vscode-extension/LICENSE`, `package.json` "SEE LICENSE IN LICENSE"); the GitHub repo goes public at publishing time. First Marketplace release is a free preview for macOS and Linux; Windows later. No telemetry at first: Marketplace statistics (installs, uninstalls, ratings) and GitHub show adoption.
- Reasoning: the user wants wide free use (including at work) but no copy-paste competitors; MIT would allow that, closed code is visible in the .vsix anyway. Shield allows any use except building a competing product. Telemetry would undercut the "everything stays local" promise of a tool that reads agent logs.
- Decided by: user, on Claude's proposal.

## 2026-10-25: Second opinions through `baton review`
- Decision: `baton review --agent <codex|claude> "<goal>"` gives another agent the diff (uncommitted changes, else the last commit, or `--commit`) with a prompt asking for at least 3 ranked points (what, why, fix, minor?) and a merge verdict. Agents run it when the user asks ("ask Codex"): a rule in AGENTS.md and the command in the session context; the panel has an "Ask for review" button for the same. The reviewer runs read-only (Codex `--sandbox read-only`, approval never; Claude `--tools Read,Grep,Glob --strict-mcp-config`), in its own process group (cancel kills it), with `BATON_REVIEW=1` so its hooks write nothing to shared memory.
- Reasoning: `codex exec review` only reports high-confidence bugs and nearly always says "no findings"; the ranked prompt found real bugs in every round. A command makes this work for every agent and user, not only through one agent's private memory; the button shows people it exists.
- Decided by: user.

## 2026-10-25: Memory hooks live in user settings
- Decision: `baton install-hooks` puts the hooks once into `~/.claude/settings.json` and `~/.codex/hooks.json` (`baton hook <agent> --global`); `baton init` writes no project hooks for agents that have them. A global hook steps aside, per event, when the project hooks that event itself (projects set up earlier keep working without doubles). The panel asks Codex's app-server (`hooks/list` -> `trustStatus`) whether the hooks are approved and offers "Approve in Codex" or "Install hooks".
- Reasoning: Codex asks for trust per hook file, so per-project hooks meant one approval per project and repos carrying a local absolute path; user-level hooks need one approval per computer (verified: Codex loads `~/.codex/hooks.json` as `source: user`). We never write Codex's trust ourselves: it is its safety check.
- Decided by: user, on Claude's proposal.

## 2026-10-25: Find agents reads the Marketplace live
- Decision: the Find agents button queries the public Marketplace gallery API when clicked (known agents plus popular AI extensions that describe themselves as coding agents); hooks and the CLI stay offline.
- Reasoning: the agent market changes fast and a hard-coded list goes stale; the call is user-initiated, anonymous, and VS Code talks to the same service anyway.
- Decided by: user.

## 2026-10-25: Cross-agent review: Claude builds, Codex reviews, Claude decides
- Decision: after significant changes Claude runs `codex exec review --uncommitted` (the CLI bundled in the openai.chatgpt extension, `bin/<platform>/codex`), weighs each finding and reports which it applied and why.
- Reasoning: the user wants one agent to write and another to test and suggest fixes; the first run caught a real bug (Recent work ignored the history archive).
- Decided by: user.

## 2026-10-25: Plan limits are local readings; mark them stale
- Decision: no network calls for limits. Readings older than 60 min are greyed out as "stale" and left out of the status bar; for Claude a "Live in Claude" button opens its sessions sidebar, whose Account & Usage section is live.
- Reasoning: Claude Code only rarely writes `cachedUsageUtilization` to `~/.claude.json` (checked: 17 h old while its own view showed live values) and Codex only during turns; querying providers would need their login tokens.
- Decided by: user, on Claude's proposal.

## 2026-10-25: Show only the agents the user has
- Decision: Claude and Codex stay built in, but the panel shows an agent only if its extension is installed (or it left a checkpoint in the project). Built-ins can be hidden (`hidden` in `~/.config/ai-baton/agents.json`) and brought back with Add agent; `baton init --agents=` installs hooks only for the agents in use.
- Reasoning: AI Baton is useful with a single agent (memory between sessions), and an empty start would hide the built-in integrations that are its main value.
- Decided by: user, on Claude's proposal.

## 2026-10-25: Adding agents: VS Code detects, the CLI writes
- Decision: the extension finds agent extensions (a known list plus the Marketplace categories "AI" and "Chat") and passes the entry to `baton add-agent`; only the CLI writes `~/.config/ai-baton/agents.json`. A user-added agent keeps launch settings only (`id`, `label`, `extension`, `openCommand`, `newCommand`). Unknown extensions open through `workbench.view.extension.<container>`.
- Reasoning: only VS Code can see installed extensions, but keeping registry writes in Python keeps them validated and tested; user entries cannot claim the Claude or Codex hooks, usage or model providers.
- Decided by: Claude (roadmap item from the user).

## 2026-10-25: No Handoff block in replies
- Decision: agents do not print a Handoff block; they update `docs/AGENT_HANDOFF.md`, and the Stop hook flags checkpoints where that file changed.
- Reasoning: the block cluttered every finished reply and repeated what the handoff doc already holds; the doc is loaded at session start anyway.
- Decided by: user.

## 2026-10-25: Tiered memory, pointers instead of copies
- Decision: inject only a short per-agent summary (about 1.5k tokens total); keep full replies on disk and archive old checkpoints with gzip; point at changes through git, a shadow git repo in `.agent-memory/`, or a file list.
- Reasoning: injecting full replies cost ~3k tokens per agent per session; pointers keep everything recoverable without loading it.
- Decided by: user.

## 2026-10-25: English everywhere, shared memory in English
- Decision: all UI, templates and CLI output in English; agents reply in the user's language but write handoff notes and docs in English.
- Reasoning: the tool may be published; English is cheaper to load (Polish costs roughly 1.5-2x tokens).
- Decided by: user.

## 2026-10-25: Name and logo
- Decision: the product is AI Baton (CLI `baton`); logo is a conductor's baton directing three agents.
- Reasoning: short, says "AI", the baton is both a relay handoff and a conductor; the previous stacked-layers icon looked like Databricks.
- Decided by: user.

## 2026-10-25: Project set up with AI Baton
- Decision: the project uses shared agent memory (AI Baton).
- Reasoning: smooth switching between Claude, Codex and other agents.
