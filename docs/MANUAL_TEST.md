# Manual test from scratch

End-to-end check of AI Baton in the real VS Code UI. Unit tests (`python3 -m unittest discover -s tests`) cover the logic; this covers what only a person can see. Tick each step; note anything that differs from "Expect".

## 0. Setup
1. Package with `sh scripts/package.sh` and install the `.vsix` (Extensions: Install from VSIX…), then **Developer: Reload Window**. The extension id is `wwijatkowski.ai-baton`; uninstall the old development copy `wiktor.ai-baton` first.
2. Create an empty test folder (e.g. `~/baton-test`) with `git init`, open it in a new VS Code window. A new folder opens in Restricted Mode: trust it, otherwise AI Baton is off and its icon is missing.

## 1. New project
1. Open the AI Baton panel. Expect: "This folder is not connected yet" and **Initialize project**; agent cards only for installed agents (Claude, Codex).
2. Click **Initialize project**. Expect: a "Setting up …" notification, then the panel switches to the project view; no prompt to install hooks (already global on this machine); AGENTS.md, CLAUDE.md, docs/ created; **no** `.claude/` or `.codex/` folder in the project.
3. Expect on the Codex card: nothing if the global Codex hooks are approved, otherwise a yellow warning with **Approve in Codex**.
4. **New chat** on the Claude card before any Claude view was opened in this window. Expect: a new Claude conversation opens in an editor tab.

## 2. Hook approval (Codex)
1. If the warning shows, click **Approve in Codex**. Expect: Codex opens; a message explains the hooks button next to the model picker.
2. In Codex click the hooks button ("Review hooks · 3 need approval"), **Allow all**. Click the panel's refresh. Expect: the warning disappears.

## 3. Shared memory
Automated with the real agents: `sh tests/e2e_agents.sh` (Claude CLI and `codex exec` in a temp project; passed 2026-10-25). Do these by hand only to see it in the chat UI.
1. In Claude (new chat): ask for a small change, e.g. "add a README line". Expect after the reply: Claude card shows "Checkpoint just now"; Recent work lists the session.
2. In Codex (new chat): "What did the previous agent do?" Expect: Codex answers from Claude's checkpoint without reading files first.
3. Back in Claude: any prompt. Expect: Claude receives Codex's checkpoint (ask "what did Codex say?").
4. Ask an agent to update `docs/AGENT_HANDOFF.md`. Expect: its Recent work entry shows "updated handoff"; an agent that only read files does not.

## 4. Recent work
1. Expand **Recent work** in the panel. Expect: one entry per session, newest first, no "false", "undefined" or "[object" anywhere.
2. Click an entry. Expect: full summary, replies count, commit; **Open session** and **Copy summary**.
3. **Open session** on a Claude entry. Expect: that exact Claude conversation opens in an editor tab.
4. **Open session** on a Codex entry. Expect: that Codex thread opens (this one is unverified so far; note what happens).
5. **Open in editor… / Show all N…**. Expect: an editor tab beside with all sessions by day, agent filter and search working.

## 5. Agents
1. **Find agents**. Expect: list opens at once, then refreshes with install counts; "Other popular in the Marketplace" section; picking one opens its Marketplace page.
2. **Add agent** (with e.g. Cline or Copilot installed). Expect: it appears as a card; **Open** opens it and copies a context request to the clipboard.
3. **Remove** on Codex. Expect: card disappears; Codex's old checkpoints still reach Claude. **Add agent** shows Codex again with "built-in".

## 5b. Ask for review
1. Make a small uncommitted change. Click **Ask for review** (or **Ask for review** on an expanded Recent work entry, which skips step 1).
   - Step 1/3 "whose work?": recent conversations (agent, time, replies, summary), up to 20, plus "No particular conversation". Pick the one that made the change.
   - Step 2/3 "who reviews?": the other agent comes first; the author is marked "wrote this (self-review)".
   - Step 3/3: optional focus; Enter starts.
   Expect: progress notification; after about a minute a Markdown tab beside ("Work of: <agent>, conversation from …"); the notification offers **Send to <author>** (the chosen conversation) and **Copy review**.
2. **Send to <author>**: the chosen conversation opens and one short message says the review is copied. Paste and send: the author lists accept/reject/defer per point, ends with how to answer, and changes nothing until you reply "ok".
3. Cancel a running review. Expect: the notification closes quietly, no error; no stray reviewer or git process.
4. In Claude say "ask Codex for a review of this change". Expect: Claude runs `baton review --agent codex ...`, lists its verdicts and waits for your ok.
5. Expect: the review does not appear in Recent work and the agents' checkpoints are unchanged.
6. Without git: in a folder with no `.git`, Initialize project, let an agent edit a file, then **Ask for review** on that conversation. Expect: "Reviewed: the changes since that conversation began" and the edit in the review.
7. No file changes: pick a conversation that only answered a question (clean tree, no commit since). Expect: "Reviewed: <agent>'s replies in that conversation (no file changes)", not an older commit.

## 6. Usage and limits
1. Expect: usage tiles and chart for this project and "All".
2. Limits older than an hour are dimmed with "~N%" and "stale"; **Live in Claude** opens Claude's Account & Usage view.
3. Model and effort pickers: change Codex's model, start a new Codex chat. Expect: it uses the chosen model.

## 7. Clean up
Always the last step of a test round, after the report is written:
1. Close the VS Code windows opened for the test (do not save the Untitled review tabs; their content is in the report).
2. Delete every test folder created in the round (e.g. `~/baton-test*`), and nothing else.
3. Note in the report's "State left behind" what was removed. Global hooks stay (they do nothing outside AI Baton projects).
