# UI test report: sections 4–6 of MANUAL_TEST.md

Date: 2026-10-25, ~19:00 local. Tested by Claude via computer use (screenshots and clicks) in the user's VS Code window `ai-baton`.
Access level: VS Code is granted "click only", so nothing that needs typing could be tested (see 4.5 search).
Nothing was installed, edited, committed or sent. "Remove", "Install hooks" and the model pickers were not touched.

## Summary

| # | Check | Result |
|---|-------|--------|
| 4.1 | Recent work: expand, no "false" / "undefined" / "[object" | PASS |
| 4.2 | Entry details: summary, replies, commit, buttons | PASS |
| 4.3 | Open session (Claude) | PASS |
| 4.4 | Open session (Codex) | PASS |
| 4.5 | Open in editor…: tab beside, by day, agent filter | PASS |
| 4.5 | Open in editor…: search | NOT TESTED |
| 5.1 | Find agents: opens at once, refreshes with install counts | PASS |
| 5.1 | "Other popular in the Marketplace" section | PASS |
| 5.1 | Picking a known agent (Cline) opens its page | PASS |
| 5.1 | Picking an "Other popular" item (Google Antigravity) opens its page | FAIL |
| 5.2 / 5.3 | Add agent, Remove | SKIPPED (excluded by test rules) |
| 6.1 | Usage tiles and chart, "This project" and "All" | PASS |
| 6.2 | Stale limits dimmed with "~N%" and "stale" | PASS |
| 6.2 | Live in Claude | PASS |
| 6.3 | Model and effort pickers | SKIPPED (excluded by test rules) |

## Details

**4.1 PASS.** Recent work (5) expanded to five entries, newest first (Claude 8 min, Claude 11 min, Codex 2 h, Claude 4 h, Claude 4 h); no "false", "undefined" or "[object" in the panel or the editor tab.

**4.2 PASS.** Clicking the 4 h Claude entry showed the full summary, "6 replies · @ 2a16745 · updated handoff", and **Open session** / **Copy summary**; the Codex entry showed "1 reply · @ ba9deed · updated handoff".

**4.3 PASS.** **Open session** on the 4 h Claude entry first showed VS Code's own prompt "Allow 'Claude Code for VS Code' extension to open this URI?" (I clicked Open and left "Do not ask me again" unticked). Then a new editor tab "Alternatywne logo zamias…" opened on that exact conversation: its last reply is "Wypchnięte. Commit 2a16745 jest na GitHubie…", the same as the entry's summary.

**4.4 PASS (first live check).** **Open session** on the Codex entry (session `01a173e5-7e4d-74a1-9142-39d1dfc653f2`) worked like this:
- No permission prompt appeared.
- The secondary side bar switched to the **Codex** tab. It is a side bar view, not an editor tab like Claude's.
- For about 15–20 s the view showed only the OpenAI logo, then the thread **"Summarize handoff state"** loaded.
- The thread is the right one: it shows "Today 5:29 PM", the prompt "Test session: read docs/AGENT_HANDOFF.md and tell me the current state and next step in 2–3 sentences. Don't edit files.", and the reply "AI Baton v1 is functional, with CLI hooks…", which matches the Recent work entry word for word.
- So the `vscode://openai.chatgpt/local/<id>` URI works. The only issue is the long blank wait, which could look like a failure.

**4.5 PASS / search NOT TESTED.** **Open in editor…** opened a "Recent work" tab beside the editor:
- It shows "Recent work · ai-baton · 5 sessions" grouped under "Sunday, 25 October 2026", with time ranges, reply counts, commits and "handoff" badges.
- **Codex** filter: only the Codex entry. **Claude** filter: only the 4 Claude entries. **All**: all 5.
- Search: the field takes focus, but typing into VS Code is blocked at my access level, so it needs a manual check.

**5.1 list PASS.** **Find agents** opened a quick pick at once with the built-in list (Gemini, Cline, Continue, Roo Code, …). About 2 s later it refreshed to "Known agents (live from the Marketplace)" with install counts, e.g. "Cline · 5.7M installs" and "Gemini · 5.6M installs". At the bottom was "Other popular in the Marketplace" with Google Antigravity (710k) and Sixth (510k), followed by "Search the Marketplace…".

**5.1 Cline PASS.** Picking Cline opened the "Extension: Cline" page in an editor tab with an **Install** button. I did not click it.

**5.1 Google Antigravity FAIL.** Picking Google Antigravity did not open its extension page. It opened the Extensions side bar searched for `Google.google-antigravity`, with one result and an Install button.
- Likely cause: `extension.open` threw for this ID, so `findAgents` in `vscode-extension/extension.js` (around line 436) fell back to `workbench.extensions.search`.
- Screenshot: `~/.claude/projects/-Users-wiktorwijatkowski-Library-Application-Support-Claude-scratch-workspaces-065a41ac-7c69-462f-9f94-088efae202f6-203b491c-e5e1-47a0-84e2-837ab43e40ba-scratch-2026-10-25-ac5592/05d53e84-170a-4a1d-81be-656fd407c8f6/tool-results/mcp-computer-use-blob-1792951534444-4hmbyy.jpg` (sent in chat too). It is outside the repo because this report is the only file I was allowed to create.
- The page still lets the user reach Install, so it is a minor failure.

**6.1 PASS.** The "This project" tiles show Codex 241k and Claude 1.2M with a 14-day chart. "All" shows Codex 257k and Claude 1.6M ("6.7M in 7 days") with a fuller chart.

**6.2 dimmed PASS.** Under Plan limits, Claude's 5-hour limit shows "~0%" with "Window has already reset · stale, read 20 h ago", and the weekly limit shows "~3%" with "Resets Sat 08:00 · stale, read 20 h ago". Both are grey. The Codex readings (9% and 1%, "read 20 min ago") are normal.

**6.2 Live in Claude PASS.** It opened Claude Code's side bar with **Account & Usage** showing live values: Session (5hr) 33% and Weekly (7 day) 10%.

## Other observations (not failures)

1. Sidebar summaries in Recent work show raw Markdown, e.g. `**„robimy następny krok z handoffu”**` and backticks around `main`. The editor tab shows the same text.
2. The stale Claude weekly limit says "Resets Sat 08:00", which is already in the past on Sunday. "~3%" with "stale" is honest, but the past reset time may confuse users.
3. In "Other popular", Sixth's display name begins "Claude Opus 5.5, Fable 5.1, GPT-6-Astra…". At a glance it looks like a Claude or OpenAI product. You may want to filter or flag names that list model names.
4. Codex threads open in the secondary side bar, Claude sessions open in an editor tab. Both are fine, but the behaviour is not the same.

## State left behind

These editor tabs were left open: "Alternatywne logo zamias…" (Claude), "Recent work", "Extension: Cline". The Extensions search side bar still has `Google.google-antigravity` in its search box. The secondary side bar is on Codex's "Summarize handoff state" thread, and the primary side bar is on Claude Code's Account & Usage view. No settings were changed.

---

# Round 2: Ask for review and changes since round 1

Date: 2026-10-25, 20:44–21:00 local. Tested by Claude (Claude desktop, computer use, VS Code at "click only" level) after the user ran Developer: Reload Window. The user pressed Enter in the focus field (twice) and pasted the review into Claude. Nothing was installed or committed and no settings were changed. The tester sent nothing to any agent.

## Summary

| # | Check | Result |
|---|-------|--------|
| A1 | Reviewer pick and focus field | PASS |
| A2 | Progress while Codex reviews; time | PASS (about 33 s) |
| A3 | Review tab beside the editor and notification | PASS |
| A4 | "Send to Claude" opens the author's conversation | FAIL |
| A5 | Claude answers with accept / reject / defer, changes nothing, ends with how to answer | PASS |
| A6 | Cancel during a Claude review | PASS |
| A7 | No Recent work entries from the reviews | PASS |
| B8 | Find agents: "by <publisher>"; Google Antigravity | PASS ("by" shown; Antigravity opened inside VS Code, so the browser fallback did not run) |
| B9 | Recent work plain text; Codex "Opening…" hint | PASS |
| B10 | Plan limit resets show a date | PASS |
| B11 | Codex not "working"; hook warnings | PASS |
| B12 | Remove Codex, then Add agent → Codex | PASS |

## Details

**A1 PASS.** "Ask for review" opens a quick pick titled "Who should review the current changes?" with two items: **Codex** (highlighted) and **Claude** with the description "worked here last". After Codex was picked, the input box was titled "Review by Codex". Placeholder: "Optional focus, e.g. performance, the new button, error handling". Prompt below: "Codex gets the changes plus Claude's last summary and the handoff, so it knows what they are for. Press Enter to start, or name something to look at closely. (Press 'Enter' to confirm or 'Escape' to cancel)". The field was left empty.

**A2 PASS.** A progress notification appeared at the bottom right: "Codex is reviewing the changes… (usually 1-3 minutes)", "Source: AI Baton", with a **Cancel** button. The `baton review --json --agent codex` process ran from 20:49:04 to 20:49:37, so the review took **about 33 seconds**.

**A3 PASS.** A Markdown editor tab "# Review by Codex" (unsaved Untitled-1) opened beside the editor with three numbered points on `baton/review.py`. A notification appeared at the same time: "Codex's review is ready. Send it to Claude's last session to act on it?" with the buttons **Send to Claude** and **Copy review**. "Do Not Disturb" is off (the bell is not crossed out).

**A4 FAIL.** "Send to Claude" showed "Review copied. Paste it into Claude (⌘V) and send. Claude lists what it accepts; reply "ok" to apply, or adjust the list." and the status bar showed "Opening the Claude conversation… it can take a few seconds". VS Code did not ask for consent to open a URL. However, it opened the **tester's own Claude desktop conversation** ("AI Baton panel manual te…") in an editor tab, not the conversation that made the changes. Claude Code showed the warning "This conversation is still open somewhere else. Using it in two places at once can mix up its messages. … This notice stays until you choose Open here anyway." with the button **Open here anyway**, which was not clicked. Cause: `reviewAndSend` in `vscode-extension/extension.js` (around line 518) picks the author as the agent with the newest checkpoint. This tester session also runs Claude in `~/ai-baton`, so the global hooks saved its checkpoints, and it was newer than the author's. Any second Claude session (a quick question in another window, a tester, `claude -p`) takes over "Send to". This may also explain "nothing pops up": the paste target is not the conversation the user is looking at. Screenshot: `round2-A4-send-to-claude-wrong-session.jpg`, kept in the tester's scratchpad and sent to the user; per the test rules it was not saved in the repo.

**A5 PASS.** The user pasted the review into the author's conversation instead (Claude Code panel, "Następny krok z handoffu"). Claude ran only read-only commands (`sed`, `grep` on `baton/review.py`), then replied with a numbered list: 1 accept, 2 accept, 3 accept in part (file-count limit and running byte count accepted; a separate total time limit rejected, with reasons). It ended with: "Odpisz „ok”, żebym wprowadził przyjęte punkty, albo napisz, co zmienić (np. „ok, 3 w całości, z limitem czasu”)." It made no edits before the answer. Afterwards the user replied "ok" themselves, and Claude applied the three fixes (38 tests pass, per its reply).

**A6 PASS.** The first attempt never started: the user clicked the chat panel before pressing Enter, which dismissed the focus box without any message. On the retry, the progress notification "Claude is reviewing the changes… (usually 1-3 minutes)" appeared. Clicking **Cancel** removed it at once, with no error notification, and no `baton review` or reviewer process was left running.

**A7 PASS.** Recent work still shows 10 entries. The newest Codex entry is from before this round (1 h ago), and no "Review by…" or reviewer output appears from either review. Two older entries are reviewer output from earlier rounds: Claude 1 h ago "Here is my review of baton review…" and Codex 1 h ago "The Git error checks…". Opening the latter shows the thread "You are reviewing a teammate's change…". They predate the `BATON_REVIEW` hook guard.

**B8 PASS.** The list opened at once with the built-in names. About 5 s later it refreshed to "Known agents (live from the Marketplace)", with every item showing a publisher, e.g. "Cline by Cline · 5.7M installs", "Gemini by Google · 5.6M installs", and under "Other popular in the Marketplace" "Google Antigravity by Google · 712k installs" and "Claude Opus 5.5, Fable 5.1, GPT-6-Astra… by Sixth · 510k installs". This time picking Google Antigravity opened its extension page **inside VS Code** after a few seconds (Install button not touched). So `extension.open` succeeded, and the browser fallback and its warning did not run and could not be tested.

**B9 PASS.** Recent work summaries are plain text (no `**` or backticks), e.g. "The diff budget still permits unbounded collection…", where the checkpoint had bold Markdown. Open session on the Codex entry showed "Opening the Codex conversation… it can take a few seconds" in the status bar, and the Codex side bar loaded the thread after a short spinner.

**B10 PASS.** "Resets Mon 26 Oct, 01:09 · read 14 min ago" (Claude 5-hour), "Resets Sat 31 Oct, 07:59" (Claude weekly), "Resets Sun 25 Oct, 21:10" (Codex 5-hour), "Resets Sun 1 Nov, 16:10" (Codex weekly). None were stale.

**B11 PASS.** The Codex card has no "working" badge ("Checkpoint 1 h ago"). There is no yellow hook warning on either card. The Claude card shows "working" because the tester's own Claude session was mid-turn; its checkpoint text is the tester's messages, see A4.

**B12 PASS.** Remove on the Codex card asked: "Remove Codex from AI Baton? The extension stays installed and existing project hooks keep working. Add it back any time with Add agent." (Cancel / Remove). After Remove, the card disappeared within about 2 s (`~/.config/ai-baton/agents.json` had `"hidden": ["codex"]`). Add agent listed "Codex openai.chatgpt, built-in: memory hooks, usage and model choice" and "Codex History Viewer - Codex and Claude Code, detected from its Marketplace category". Picking Codex showed "Codex is back. In projects set up without it, run AI Baton: Initialize Project again to add its hooks." The card came back with its models (GPT-6.1-Sol, low) and checkpoint, and `hidden` is empty again.

## Other observations (round 2)

1. A4 in short: "the newest checkpoint" is not "the author". Ideas: prefer the session that last edited files, track the session active when the review started, or let the user pick the target session from Recent work.
2. While Codex was removed, Usage and the status bar showed it as lowercase "codex" (the id instead of the label).
3. A dismissed focus box (click elsewhere) gives no feedback. That was harmless here, but it can look like "nothing happened".
4. The self-review prompt says "Claude gets the changes plus Claude's last summary…" when Claude reviews its own work. Correct, but it reads oddly.
5. Recent work summaries are cut mid-word ("…the omission list is appen").

## State left behind (round 2)

These editor tabs are open: "Untitled-1" (Codex review, unsaved), the tester's Claude conversation (with the "Open here anyway" warning, not clicked) and "Extension: Google Antigravity". The secondary side bar is on the Codex review thread from 1 h ago. Codex was removed and re-added (net config unchanged). The only file edited is this report.

---

# Round 3: three-step Ask for review, review from Recent work, empty panel

Date: 2026-10-25, 21:27–21:47 local. Tested by Claude (Claude desktop, computer use, VS Code at "click only" level) after the user ran Developer: Reload Window. The user pressed Enter three times, pressed Escape once and typed "review" in the search box. Nothing was installed or committed, no settings were changed and nothing was sent to an agent. The working tree was clean (HEAD `3dc2c97`), so both reviews covered the last commit.

## Summary

| # | Check | Result |
|---|-------|--------|
| A1 | Step 1/3 "whose work?" | PASS |
| A2 | Step 2/3 with the user's conversation | PASS |
| A3 | Step 3/3 text; review time | PASS (about 35 s) |
| A4 | "Work of:" header; notification | PASS |
| A5 | "Send to Claude" opens the user's conversation, not the tester's | PASS |
| B6 | "Ask for review" on a Codex entry skips step 1 | PASS (cancel needs Escape, see details) |
| B7 | "Ask for review" in the Recent work tab; search "review" | PASS |
| C8 | No particular conversation → only "Copy review" | PASS (about 77 s) |
| D9 | Empty panel after removing both agents | PASS |
| D10 | Add agent → Claude, then Codex | PASS |
| E11 | Cut summaries end with "…" on a whole word | FAIL |

## Details

**A1 PASS.** Title: "Ask for review (1/3): whose work?". Placeholder: "Pick the conversation that made the changes. The reviewer reads all current uncommitted changes plus this conversation's own summary, and the review can be sent back to it." There are 11 conversations and one extra item:
1. Claude · 1 min ago, 12 replies: "Zanim zacznę rundę 3, uruchom Developer: Reload Window…" (**the tester**)
2. Claude · 2 min ago, 49 replies: "Commit 3dc2c97 jest zrobiony, drzewo robocze czyste…" (**the user's VS Code conversation "Następny krok z handoffu"**)
3. Claude · 2 h ago, 1 reply: "Here is my review of baton review, most important first…"
4. Codex · 2 h ago, 1 reply: "The Git error checks, NUL-separated filenames…"
5. Codex · 2 h ago, 1 reply: "1. Cancellation leaves the reviewer running…"
6. Codex · 2 h ago, 1 reply: "The revised completion logic addresses the main round-one concerns…"
7. Codex · 2 h ago, 1 reply: "Sharing isworking between hooks and the panel is a good improvement…"
8. Codex · 4 h ago, 1 reply: "AI Baton v1 is functional, with CLI hooks…"
9. Claude · 6 h ago, 6 replies: "Wypchnięte. Commit 2a16745 jest na GitHubie…"
10. Claude · 6 h ago, 2 replies: "- Done: Copied the pre-rename Claude chat…"
11. **"No particular conversation"**: "The reviewer works out the goal from the changes and the handoff; you copy the review yourself."

Both the user's and the tester's conversations are listed. They differ only by age, reply count and first words; nothing says which client (VS Code or Claude desktop) a conversation is in.

**A2 PASS.** Title: "Ask for review (2/3): who reviews Claude's work?". **Codex** is first and **Claude** second, described as "wrote this (self-review)". Codex was picked.

**A3 PASS.** Title: "Ask for review (3/3): anything to look at closely?". Placeholder: "Optional focus, e.g. performance, the new button, error handling". Prompt: "Codex gets the current changes plus Claude's summary from that conversation and the handoff, so it knows what they are for. Press Enter to start, or name a focus. (Press 'Enter' to confirm or 'Escape' to cancel)". The process was `baton review --json --agent codex --path … --session 93c83d1d-…` (the user's session id). It ran from 21:33:36 to 21:34:11, **about 35 seconds**.

**A4 PASS.** Tab "# Review by Codex", header lines: "Reviewed: the last commit (there are no uncommitted changes)" and "**Work of: Claude, conversation from 9 min ago**". Four ranked points followed. Notification: "Codex's review is ready. Send it back to Claude's conversation from 9 min ago?" with the buttons **Send to Claude** and **Copy review**.

**A5 PASS.** "Send to Claude" focused the Claude Code input of the user's conversation "Następny krok z handoffu" in the right side bar; the input got a highlight and the review tab as an attached chip. The tester's conversation did **not** open (no new tab, no "still open somewhere else" warning). Status bar: "Opening the Claude conversation… it can take a few seconds". Toast: "Review copied. Paste it into Claude (⌘V) and send. Claude lists what it accepts; reply "ok" to apply, or adjust the list." Nothing was pasted.

**B6 PASS.** The expanded Codex entry (2 h ago) in the panel shows **Open session**, **Ask for review** and **Copy summary**. Ask for review skipped step 1 and opened "Ask for review (2/3): who reviews Codex's work?" with **Claude** first and "Codex — wrote this (self-review)" second. Step 3 for Claude said "Claude gets the current changes plus Codex's summary from that conversation and the handoff…". Clicking the empty editor area beside it did **not** close the box (it now has `ignoreFocusOut`, the fix for round 2's silent dismissal), so the test step "click beside it to cancel" no longer applies. The user pressed Escape: the box closed with no message and no `baton review` process started.

**B7 PASS.** "Show all 10…" opened the "Recent work · ai-baton · 10 sessions" tab beside the editor. Clicking an entry expanded it and showed **Open session**, **Ask for review** and **Copy summary**. After the user typed "review" in "Search summaries", the list narrowed from 10 to 5 entries, each containing "review".

**C8 PASS.** Ask for review → "No particular conversation" opened "Ask for review (2/3): who reviews?" (no author in the title, Claude first). Step 3 said "Claude gets the current changes plus the latest summary and the handoff…". The process was `baton review --json --agent claude --path …` with no `--session`. It ran from 21:42:18 to 21:43:35, **about 77 seconds**. Tab "# Review by Claude" has "Reviewed: the last commit (there are no uncommitted changes)" and no "Work of" line. The notification reads only "Claude's review is ready." with **only "Copy review"**.

**D9 PASS.** Both Remove dialogs read "Remove <agent> from AI Baton? The extension stays installed and existing project hooks keep working. Add it back any time with Add agent." After both removals, the Agents section shows "No coding agent found. Add one you have installed, or find one in the Marketplace.". **Add agent** is the highlighted (blue) button, and **Ask for review** is gone: only Add agent, Find agents, Request handoff and Add decision remain. Recent work entries stay, but lose "Open session" (only Ask for review and Copy summary, then only Copy summary). The status bar item became "AI Baton".

**D10 PASS.** Add agent listed "Claude anthropic.claude-code, built-in: memory hooks, usage and model choice", "Codex openai.chatgpt, built-in: …" and "Codex History Viewer…". Picking Claude showed "Claude is back. In projects set up without it, run AI Baton: Initialize Project again to add its hooks.", and then the same for Codex. Both cards came back with their models (Claude "Default (last used: Opus 5.5)" / "Default effort", Codex "Default (GPT-6.1-Sol)" / "Default (low)") and checkpoints. `~/.config/ai-baton/agents.json` ends with `"hidden": []`, and Open session is back on the entries.

**E11 FAIL.** The display trimming (`status.clip`) cuts at a word boundary, e.g. "…the handoff reports 28 passing tests, though several recent UI features still need manual …" and "…Canceling can leave that agent …". But summaries that were already cut **when the checkpoint was saved** still end mid-word: the expanded Codex entry (19:39) ends "Furthermore, the omission list is **appen …**", in the panel and in the tab. Cause: `baton/hook.py:65` (`flat[:SUMMARY_FALLBACK].rstrip() + ' …'`) and `hook.py:165` (`summary[:limit].rstrip() + ' …'`) cut by character count, and new checkpoints are still cut this way. One-line rows in the panel also use a CSS ellipsis, which cuts mid-word ("bez wybranej ro…"), as expected for single-line rows. Screenshot: `round3-E11-midword-cut.jpg` (tester's scratchpad, sent to the user).

## Other observations (round 3)

1. The step 1 list mixes every client: the tester's Claude desktop session is item 1, above the user's VS Code session. Picking it by mistake would send the review to the wrong place, as in round 2's A4. A client hint ("VS Code" / "CLI" / "desktop") or the first user prompt would make the choice safer.
2. The Recent work tab still shows raw Markdown in one entry: "…I didn't edit or run anything. ### 1. The reviewer's own…".
3. Each review opens another editor group, so after two reviews and the Recent work tab the editor area had three narrow columns.
4. The Claude review tab showed "13 problems in this file" (Markdown lint on an unsaved buffer); harmless, but noisy.
5. Two of the listed "conversations" (Claude 2 h "Here is my review…", Codex 2 h "The Git error checks…") are reviewer runs from before the `BATON_REVIEW` guard. As "whose work?" choices, they would hand a review to a reviewer.

## State left behind (round 3)

These editor tabs are open: "Untitled-1" (Codex review), "Untitled-2" (Claude review), "Recent work" (search box still holds "review"). The review text is in the clipboard. Both agents were removed and re-added (net config unchanged). The only file edited is this report.

---

# Round 4: clean check after the round 3 fixes

Date: 2026-10-25, 21:55–22:05 local. Tested by Claude (Claude desktop, computer use, VS Code at "click only" level) after the user ran Developer: Reload Window. The user pressed Enter twice and pasted the review into their own Claude conversation once. Nothing was installed or committed, no settings were changed and the tester sent nothing to an agent. The working tree was clean (HEAD `c5dd4f7`), so both reviews covered the last commit.

## Summary

| # | Check | Result |
|---|-------|--------|
| A1 | Recent work has no reviewer output | PASS |
| A2 | Codex card shows its real checkpoint | PASS |
| A3 | No mid-word cuts, no `###`, `**` or backticks | PASS |
| B4 | Step 1/3 shows where each conversation runs | PASS |
| B5 | Review of the user's conversation by Codex | PASS (about 31 s) |
| B6 | Send to Claude → user's conversation; Claude proposes, changes nothing | PASS |
| B7 | Second review reuses the same editor column | PASS (2 columns) |
| B8 | No new Recent work entries from reviewers | PASS |
| C9 | Find agents live with "by <publisher>" | PASS |
| C10 | Plan limits: reset dates; stale readings dimmed | PASS for dates; dimming NOT TESTABLE (no reading was older than 60 min) |
| C11 | No hook warning, no wrong "working" on Codex | PASS |

## Details

**A1 PASS.** Recent work (5), newest first:
1. Claude · 1 min ago: "Zanim zacznę rundę 4, uruchom Developer: Reload Windo…" (tester)
2. Claude · 2 min ago: "Zrobiłem commit c5dd4f7, drzewo robocze jest czyste. Hi…" (user)
3. Codex · 4 h ago: "AI Baton v1 is functional, with CLI hooks, shared memory, …"
4. Claude · 6 h ago: "Wypchnięte. Commit 2a16745 jest na GitHubie, a lokalne …"
5. Claude · 7 h ago: "- Done: Copied the pre-rename Claude chat (bd5bcb28-…"

None of "Here is my review…", "The Git error checks…", "1. Cancellation leaves…", "The revised completion logic…" or "Sharing is_working…" appears.

**A2 PASS.** Codex card: "Checkpoint 4 h ago · main @ ba9deed" with "AI Baton v1 is functional, with CLI hooks, shared memory, and a VS Code panel; the handoff reports 28 passing tests, though several recent UI features still…". The data has `saved_at 2026-10-25T16:29:53Z`, which is 17:29 local, as shown in the tab.

**A3 PASS.** In the panel and in the Recent work tab, no summary showed `###`, `**` or backticks. The stored summaries still contain `**` and backticks, but the UI strips them; for example `.agent-memory` is shown as plain ".agent-memory". Multi-line previews end with " …" after a whole word ("…Historia jest uporządkowana: usunąłem wszystkie …", "…the handoff reports 28 passing tests, …"). The only cut stored summary ends on a whole word: "…poproś mnie o Developer: Reload Window i…". The expanded 15:15 entry shows full plain text with its "- Done / - Verified / - Next / - Open" lines. One-line rows in the panel still use a CSS ellipsis, which can end mid-word ("…Reload Windo…"); that is expected for single-line rows.

**B4 PASS.** "Ask for review (1/3): whose work?" listed:
1. "Claude · **Claude desktop** · 2 min ago", 18 replies: "Zanim zacznę rundę 4…"
2. "Claude · **VS Code** · 3 min ago", 52 replies: "Zrobiłem commit c5dd4f7…"
3. "Codex · 4 h ago", 1 reply: "AI Baton v1 is functional…"
4. "Claude · 6 h ago", 6 replies: "Wypchnięte…"
5. "Claude · 7 h ago", 2 replies: "- Done: Copied…"
6. "No particular conversation"

The user's conversation ("VS Code") and the tester's ("Claude desktop") can now be told apart at a glance. Older entries have no client label, as expected (`client` is null for checkpoints saved before the change).

**B5 PASS.** Step 2 was "Ask for review (2/3): who reviews Claude's work?" (Codex first, "Claude — wrote this (self-review)"). Step 3: "Codex gets the current changes plus Claude's summary from that conversation and the handoff, so it knows what they are for. Press Enter to start, or name a focus." The process (`--agent codex --session 93c83d1d-…`) ran from 21:58:16 to 21:58:47, **about 31 seconds**. Tab "# Review by Codex", header: "Reviewed: the last commit (there are no uncommitted changes)" and "Work of: Claude, conversation from 4 min ago", then three ranked points. Notification: "Codex's review is ready. Send it back to Claude's conversation from 4 min ago?" with **Send to Claude** and **Copy review**.

**B6 PASS.** Send to Claude focused the user's conversation "Następny krok z handoffu" in the right side bar (the review tab attached as a chip), and no other conversation opened. Status bar: "Opening the Claude conversation… it can take a few seconds". Toast: "Review copied. Paste it into Claude (⌘V) and send. Claude lists what it accepts; reply "ok" to apply, or adjust the list." The user pasted and sent. Claude replied "Sprawdzam każdą uwagę w kodzie. Na razie niczego nie zmieniam." and ran one read-only Bash command (`sed`/`grep`). Then it listed: 1 "przyjmuję", 2 "przyjmuję", 3 "przyjmuję częściowo" with the VS Code mock test "Odkładam", each with reasons. It ended: "Odpisz „ok”, żebym wprowadził punkty 1–3 (bez testu z atrapą VS Code), albo napisz, co zmienić." `git status` stayed clean. The tester did not answer it.

**B7 PASS.** Before the reviews, the editor had one column (Recent work tab). The first review opened a second column beside it. The second review started from the Codex entry's "Ask for review": step 1 was skipped, "who reviews Codex's work?" put Claude first, and the run was `--agent claude --session 01a173e5-…` from 22:02:06 to 22:03:04, about 58 s. It opened "# Review by Claude" as a new tab **in the same column** as "# Review by Codex", so there were still 2 editor columns. Header: "Work of: Codex, conversation from 5 h ago". Notification: "Claude's review is ready. Send it back to Codex's conversation from 5 h ago?" with **Send to Codex** and **Copy review**. It was not clicked.

**B8 PASS.** After both reviews, Recent work still has 5 entries; only the tester's and the user's own sessions got newer. `baton recent --json` lists claude-desktop 21:01, claude-vscode 21:00, codex 16:29, claude 14:28 and claude 14:21: no reviewer runs.

**C9 PASS.** The list opened with the built-in names and then switched to "Known agents (live from the Marketplace)", each item with a publisher: "Cline by Cline · 5.7M installs", "Gemini by Google · 5.6M installs", "Continue by Continue · 4.4M installs" and so on. The "Other popular in the Marketplace" section started with "Google Antigravity by Google · 715k installs". Tester error: a click meant to close the list landed on the "Amazon Q" row and opened its extension page in the editor. Nothing was installed, and the tab "Extension: Amazon Q" was left open.

**C10 PASS / NOT TESTABLE.** Resets: "Resets Mon 26 Oct, 01:09 · read 39 min ago" (Claude 5-hour, 31%), "Resets Sat 31 Oct, 07:59 · read 39 min ago" (Claude weekly, 19%), "Resets Mon 26 Oct, 02:11 · read 5 min ago" (Codex 5-hour, 3%), "Resets Sun 1 Nov, 16:10 · read 5 min ago" (Codex weekly, 4%). All readings were under 60 minutes old, so none was dimmed or shown as "~N%", and stale display could not be checked this round (it passed in round 1).

**C11 PASS.** No yellow hook warning on either card. Codex shows "Checkpoint 4 h ago" (later "5 h ago") with no "working" badge. Claude shows "working", which is correct because the tester's session was mid-turn.

## Other observations (round 4)

1. Codex's review (point 1) found a real risk in the new client label: `client_of` reads `CLAUDE_CODE_ENTRYPOINT` for every agent, so a Codex run started from inside Claude (e.g. `tests/e2e_agents.sh`) would be labelled "VS Code"/"Claude desktop". The author accepted it.
2. One-line rows in the panel still end mid-word through the CSS ellipsis ("Reload Windo…"). Fine for one line; mentioned only because A3 asks about cuts.
3. The tester accidentally clicked "Copy summary" once while collapsing an entry in the Recent work tab (the button moved under the pointer as the entry collapsed). The clipboard was overwritten until Send to Claude replaced it. Collapse-on-click near buttons is easy to mis-hit.
4. "No particular conversation" and the four older entries have no client label; only checkpoints saved after the change carry one.
5. The Claude review tab reported "8 problems in this file" (Markdown lint on the unsaved buffer).

## State left behind (round 4)

These editor tabs are open: "Recent work" (column 1); "# Review by Codex" (Untitled-1), "# Review by Claude" (Untitled-2) and "Extension: Amazon Q" (column 2). The "Claude's review is ready… Send to Codex" notification is still showing. The clipboard holds the Codex review prompt. The only file edited is this report.

---

# Round 5: installed package

Date: 2026-10-26, 11:39–12:00 local. Tested by Claude (Claude desktop, computer use, VS Code at "click only" level) on the installed package `wwijatkowski.ai-baton` 0.3.0 from the .vsix, CLI in `~/.ai-baton` (0.3.0), and hooks calling `~/.ai-baton/bin/baton`. The user trusted the two new folders, approved the Codex hooks, pressed Enter four times and gave Claude two prompts in `~/baton-test-nogit`. Nothing was installed or committed, VS Code settings and hooks were not changed, and nothing was sent to an agent (Send to Claude was clicked once, nothing pasted). Test folders: `~/baton-test` (git, no commits) and `~/baton-test-nogit` (no git), left in place.

## Summary

| # | Check | Result |
|---|-------|--------|
| A1 | New git folder: panel shows "not connected" and Initialize project | PASS |
| A2 | Initialize: AGENTS.md, CLAUDE.md, docs/; no .claude/ or .codex/; no hook prompt | PASS |
| A3 | Codex card warns about unapproved hooks | PASS |
| B1 | Approve in Codex opens Codex and explains the hooks button | PASS |
| B2 | After Allow all (user) and refresh, the warning is gone | PASS |
| C1 | Recent work (~/ai-baton): entries, no "false" / "undefined" / "[object" | PASS |
| C2 | Entry details and buttons | PASS |
| C3 | Open session (Claude) | PASS |
| C4 | Open session (Codex) | PASS |
| C5 | Open in editor…: tab beside, by day, agent filter | PASS |
| D1 | Ask for review of an uncommitted change (git) | PASS (about 28 s) |
| D3 | Cancel a running review | PASS |
| D5 | Review leaves no Recent work entry or checkpoint | PASS |
| D6 | No git: review of the conversation that edited a file | FAIL |
| D7 | No file changes: review of a question-only conversation | PASS (about 30 s; tested in the no-git folder) |
| D2 | Send to Claude opens the chosen conversation | PASS (nothing pasted) |
| E | ~/ai-baton panel: cards, usage, limits, no errors | PASS |
| X | "New chat" on the Claude card in a window where Claude is not open yet | FAIL |

## Details

**A1 PASS.** Folder `~/baton-test` with `git init` (no commits), opened via `open -a "Visual Studio Code"`. It first opened in **Restricted Mode** ("Restricted Mode is intended for safe code browsing. Trust this folder to enable all features."), and the AI Baton icon was missing until the user trusted the folder. Then the panel showed "baton-test", "This folder is not connected yet. Initializing adds AGENTS.md, CLAUDE.md, docs/ and memory hooks. Existing files stay unchanged.", **Initialize project**, and cards for Claude and Codex (models, Open / New chat / Remove).

**A2 PASS.** Dialog: "Set up baton-test for AI Baton? This adds AGENTS.md, CLAUDE.md, docs/ and memory hooks. Existing files are not overwritten." (Cancel / Initialize). It did not ask about installing hooks. Created: `.baton.json`, `.gitignore` (`.agent-memory/`), `AGENTS.md`, `CLAUDE.md`, `docs/AGENT_HANDOFF.md`, `docs/STATUS.md`, `docs/knowledge/`. No `.claude/` or `.codex/`. The Output channel ended "Done. Restart agent sessions in this folder.", and the toast said "Project ready. Start a new Claude conversation. In Codex, approve the 3 hooks once: hooks button next to the model picker, then Allow all."

**A3 PASS.** Codex card: "No checkpoint" and a yellow box "Codex has not approved the memory hooks yet, so it does not share memory." with **Approve in Codex**. `baton hook-status ~/baton-test` printed `codex untrusted not approved yet: in Codex click the hooks button next to the model picker (Review hooks), then Allow all`. The Claude card had no warning.

**B1 PASS.** Approve in Codex switched the secondary side bar to the Codex tab (a few seconds of blank logo, then the Codex chat list) and showed: "In Codex, click the hooks button next to the model picker ("Review hooks · 3 need approval") and choose Allow all. This is needed once per computer."

**B2 PASS.** After the user's Allow all, `baton hook-status` printed `codex ok approved (user)`. After the panel's refresh button, the yellow box was gone.

**C1 PASS.** Recent work (7), newest first: Claude 2 min (tester, claude-desktop), Claude 6 min "Reinstalacja się udała…", Claude 39 min "Handoff jest uaktualniony i wysłany (commit 890e040)…", Claude 3 h "Zapisałem wszystko w pamięci…", Codex 18 h "AI Baton v1 is functional…", and two Claude 20 h entries. There were no reviewer outputs and no "false", "undefined" or "[object".

**C2 PASS.** Expanded entries show the full plain-text summary (no Markdown), "13 replies · @ 0aa2984 · updated handoff" or "78 replies · @ 890e040 · updated handoff", plus **Open session**, **Ask for review** and **Copy summary**.

**C3 PASS.** Open session on the Claude 39 min entry opened the conversation "Następny krok z handoffu" in an editor tab beside the panel. Status bar: "Opening the Claude conversation… it can take a few seconds".

**C4 PASS.** Open session on the Codex entry showed "Opening the Codex conversation… it can take a few seconds". The Codex side bar showed its logo for a few seconds, then the thread "Summarize handoff state" with the matching prompt and reply.

**C5 PASS.** "Open in editor…" opened "Recent work · ai-baton · 7 sessions" beside, grouped by day ("Monday, 26 October 2026", "Sunday, 25 October 2026"). The Codex filter left only the Codex entry, and All restored the list. Search was not retyped this round (passed in round 3).

**D1 PASS.** The tester added `README.md` ("# baton-test / Scratch project for the AI Baton round 5 UI test.") to `~/baton-test`. With no conversation in the folder, Ask for review skipped step 1. It opened "Ask for review (2/3): who reviews?" (Claude, Codex, no author) and then step 3: "Codex gets the changes (or, if no files changed, the conversation's replies) plus the latest summary and the handoff, so it knows what they are for. Press Enter to start, or name a focus." The process `baton review --json --agent codex --path ~/baton-test` ran 11:47:01–11:47:29, **about 28 s**. Tab "# Review by Codex": "Reviewed: the uncommitted changes", then three ranked points citing `AGENTS.md:29` and `README.md:3`. Notification: "Codex's review is ready." with only **Copy review** (no conversation to send back to).

**D3 PASS.** A second review (Claude) showed "Claude is reviewing the work… (usually 1-3 minutes)" with **Cancel**. Cancel closed it at once with no error, and afterwards there was no `baton review` and no `git` process for the folder.

**D5 PASS.** After both reviews, `baton recent --json ~/baton-test` returned `"sessions": []` and no `.agent-memory/` existed: the reviewer left no checkpoint.

**D6 FAIL.** `~/baton-test-nogit` (no `git init`) also opened in Restricted Mode first. After the user trusted it, Initialize project created the same files as A2 and no `.git`. The user asked Claude (VS Code) "Utwórz plik notes.txt z jedną linijką: hello from round 5", and Claude created `notes.txt`. Its checkpoint lists `"kind": "shadow", "commit": "53553b5"` with `notes.txt` among 8 changed files. Ask for review → "Claude · VS Code · 1 min ago" → step 2 "who reviews Claude's work?" (Codex first, Claude "wrote this (self-review)") → Codex. The run had `--session e8dd47f4…` and lasted 11:53:02–11:53:35 (about 33 s). Expected "Reviewed: the changes since that conversation began". Got "**Reviewed: Claude's replies in that conversation (no file changes)**" and "Work of: Claude, conversation from 1 min ago". Codex still mentioned `notes.txt`, because it read the file itself, but the header is wrong: a file did change. Cause: the shadow repo has only one commit, taken at the end of that first conversation (`53553b5`, 11:52:10), so there is no snapshot from where it began. `collect_shadow` (review.py:213) finds no base and returns nothing, and the review falls back to "replies … (no file changes)". The first conversation in a fresh no-git project can never be reviewed as a change. Initialize, or UserPromptSubmit when no snapshot exists, should take a baseline snapshot. Screenshot: `round5-D6-nogit-no-file-changes.jpg` (tester's scratchpad, sent to the user).

**D7 PASS.** No conversation in `~/ai-baton` qualifies: every recent one ended in a commit. The user asked a question in a second Claude conversation in `~/baton-test-nogit` ("Ile plików jest w katalogu tests? Niczego nie zmieniaj."), and Claude only ran `ls` and `find`. Ask for review on "Claude · VS Code · just now" → Codex. The run (`--session feb01cdd…`) lasted 11:56:26–11:56:56, about 30 s. Header: "**Reviewed: Claude's replies in that conversation (no file changes)**", "Work of: Claude, conversation from 2 min ago", then points on the reply text. This covers the no-git variant only; the git variant (clean tree, no commit since) was not tested.

**D2 PASS.** On the D7 review, "Codex's review is ready. Send it back to Claude's conversation from 2 min ago?" → **Send to Claude** kept the same conversation ("Liczba plików w katalogu tests") focused with the review tab attached as "Untitled-2". The status bar showed "Opening the Claude conversation…" and the toast "Review copied. Paste it into Claude (⌘V) and send. Claude lists wh…". Nothing was pasted.

**E PASS.** `~/ai-baton` panel: the Claude card shows "working" (the tester's session, correct) and "Checkpoint 1 min ago · main @ 0aa2984". The Codex card shows "Checkpoint 18 h ago · main @ ba9deed" with no "working" badge and no hook warning. Usage "This project": Codex 144k / 968k in 7 days, Claude 2.7M / 5.2M in 7 days, chart for 13.10–26.10. Plan limits: Claude 5-hour "~0%" "Window has already reset · stale, read 15 h ago" and Claude weekly "~19%" "Resets Sat 31 Oct, 07:59 · stale, read 15 h ago", both dimmed. Codex 5-hour 6% "Resets Mon 26 Oct, 14:36 · read 3 min ago" and Codex weekly 1% "Resets Mon 2 Nov, 09:36". **Live in Claude** is present. No error notifications.

**X FAIL: New chat.** In the new `~/baton-test-nogit` window, before any Claude panel had been opened there, the user clicked **New chat** on the Claude card several times. Nothing happened: no new conversation, no panel and no error (screenshot `round5-newchat-no-effect.webp`, from the user, sent to the user). Cause: AI Baton runs `claude-vscode.newConversation` (`newCommand` in `agents.json`). In Claude Code 2.1.310 that command only calls `notifyCreateNewConversation()` on an already open Claude view, so with no view open it does nothing. The workaround was **Open**, then New chat; after that New chat worked in the same window, and it also works in `~/ai-baton` where Claude is already open. Fix idea: run the open command (or `claude-vscode.editor.open`) first, then `newConversation`.

## Other observations (round 5)

1. Every new folder opens in Restricted Mode, and AI Baton is disabled until the user trusts it. `MANUAL_TEST.md` 0.2 does not mention this; a first-time user sees no batuta icon at all.
2. The panel lags after Initialize: right after the dialog it still showed "not connected" for a few seconds, and the files existed before the panel updated. In the no-git window the first click on Initialize project, made while the panel was loading, did nothing.
3. When there is no conversation, step 1 is skipped silently, and step 2 is titled just "who reviews?". Correct, but a one-line hint ("no conversations here yet") would explain the skip.
4. Codex's D6 review still quoted `notes.txt` because it read the folder itself, so a user may not notice the wrong header. It is worth a test in `tests/`.
5. The D1 review in `~/baton-test` reviewed AI Baton's own scaffolding (AGENTS.md, docs/) along with README.md, because the repo has no commits; expected for an unborn repo.

## State left behind (round 5)

- `~/baton-test`: initialized, untracked scaffolding plus `README.md`, no commits. Its window has the "Review by Codex" tab (Untitled-1) open.
- `~/baton-test-nogit`: initialized, `notes.txt`, `.agent-memory/` with two Claude sessions. Its window has two review tabs (Untitled-1, Untitled-2) and the Claude conversation open.
- `~/ai-baton` window: tabs "Następny krok z handoffu" (Claude) and "Recent work"; the Codex side bar is on "Summarize handoff state".
- The clipboard holds the D7 review prompt. Codex hooks are now approved (by the user). The only file edited in the repo is this report.

---

# Round 6: fixes from round 5

Date: 2026-10-26, 12:31–14:31 local, with a pause while the user's plan limit reset. Tested by Claude (Claude desktop, computer use, VS Code at "click only" level) on the installed `wwijatkowski.ai-baton` 0.3.0 (extension.js from 12:31) and CLI `~/.ai-baton/versions/0.3.0`. The user trusted both new folders, gave Claude one prompt and pressed Enter once. Nothing was installed or committed, settings and hooks were not changed, and nothing was sent to an agent. Test folders: `~/baton-test6` (git, no commits) and `~/baton-test6-nogit` (no git), left in place.

## Summary

| # | Check | Result |
|---|-------|--------|
| 1.2 | Initialize shows "Setting up …", then the project view | PASS |
| 1.4a | New chat (Claude) before any Claude view: a new conversation in an editor tab | FAIL |
| 1.4b | New chat a second time: a second, separate conversation | FAIL (nothing opened, as in 1.4a) |
| 1.4c | Open (Claude) still opens the side bar | PASS |
| 5b.6 | No git: Initialize takes a baseline snapshot | PASS |
| 5b.6 | No git: review of the conversation that edited a file | PASS (about 35 s) |

## Details

**1.2 PASS.** `~/baton-test6` (`git init`, no commits) opened in a new window, first in Restricted Mode; the user trusted it. The panel showed "This folder is not connected yet…" and **Initialize project**. The dialog "Set up baton-test6 for AI Baton? …" → Initialize. A "Setting up baton-test6…" notification appeared at the bottom right, then the panel switched to the project view (cards with "No checkpoint", Ask for review, Project knowledge "just now"). The toast "Project ready. Start a new Claude conversation. In Codex, approve…" followed. Created: `.agent-memory/`, `.baton.json`, `.gitignore`, `AGENTS.md`, `CLAUDE.md`, `docs/`; no `.claude/` or `.codex/`.

**1.4a FAIL.** Before any Claude view was opened in this window, **New chat** on the Claude card did nothing visible: no editor tab, no side bar, no notification. The extension host log of that window shows, for each click, two of: `[error] TypeError: Cannot read properties of null (reading 'startsWith')` at `resolveTeleportedCopy` → `hasPanelForSession` (anthropic.claude-code-2.1.310 extension.js), called from `openAgent` (wwijatkowski.ai-baton extension.js:313) with `claude-vscode.editor.open`. Cause: `agents.json` now sets `"newCommand": "claude-vscode.editor.open"` with `"newArgs": [null, null, null, null, null, {"programmatic": "pin-to-panel"}]`. Claude Code reads the first argument as a session id and calls `.startsWith` on `null`, so the command throws before it opens anything. AI Baton swallows the rejection, so the user sees nothing. Fix idea: pass `undefined` (or omit the leading arguments) instead of `null`, and surface a failed `executeCommand` as an error message. Screenshot: `round6-newchat-no-effect.jpg` (tester's scratchpad, sent to the user).

**1.4b FAIL.** The second click was made after **Open** (see 1.4c), with the Claude side bar already showing "Untitled". It also did nothing and logged the same TypeError (4 errors in total: 12:33:37, 12:33:38, 12:34:13, 12:34:14). A second, separate conversation could not be checked because the first never opened.

**1.4c PASS.** **Open** on the Claude card opened Claude Code in the secondary side bar ("Claude Code" tab, empty "Untitled" conversation), as before. The failed New chat did not change where Open opens Claude.

**5b.6 baseline PASS.** `~/baton-test6-nogit` (no `.git`), trusted by the user, Initialize project. `.agent-memory/shadow.git` was created at once with one commit, `388bbfa 2026-10-26 12:46:13 baseline`. The Output channel listed "+ .agent-memory/shadow.git: first snapshot of the files (no git repository)". This is the fix for round 5 D6.

**5b.6 review PASS.** The user opened Claude (Open, then "+", because of 1.4a) and asked "Utwórz plik notes.txt z jedną linijką: hello from round 6"; Claude wrote `notes.txt` (session `53e7217c…`, client claude-vscode). Ask for review → "Claude · VS Code · just now · 1 reply" → step 2 Codex → step 3 "Codex gets the changes (or, if no files changed, the conversation's replies) plus Claude's summary from that conversation and the handoff…" → Enter. The process `baton review --json --agent codex --path ~/baton-test6-nogit --session 53e7217c…` ran 14:29:59–14:30:34, **about 35 s**. Tab "# Review by Codex": "**Reviewed: the changes since that conversation began**", "Work of: Claude, conversation from 2 min ago", "The file matches the author's stated intent exactly…", and ranked points citing `notes.txt:1` and `docs/AGENT_HANDOFF.md:8`. Notification: "Codex's review is ready. Send it back to Claude's conversation from 2 min ago?" with **Send to Claude** and **Copy review** (not clicked).

## Other observations (round 6)

1. New folders still open in Restricted Mode first; the user has to trust each one before AI Baton appears.
2. A failing `executeCommand` in `openAgent` is silent. Any future change in an agent's command arguments will again look like "the button does nothing"; a `catch` with an error toast (and the log line) would make it visible.
3. After the panel refresh, the layout shifted by one row as Recent work (1) appeared, so the tester's click meant for Ask for review hit **Add agent**. Its quick pick ("Add which installed agent?") stayed open until Ask for review replaced it; nothing was added.
4. The round 5 note about `MANUAL_TEST.md` is addressed: section 1.2 now mentions the "Setting up …" notification and 1.4 the New chat check.

## State left behind (round 6)

- `~/baton-test6`: initialized, no commits; the Claude side bar is open with an empty "Untitled" conversation.
- `~/baton-test6-nogit`: initialized with the shadow baseline, `notes.txt`, one Claude session. Its window has the "Review by Codex" tab (Untitled-1, unsaved) and the Claude conversation "Plik notes.txt" open.
- Earlier folders `~/baton-test` and `~/baton-test-nogit` are unchanged since round 5.
- The only file edited by the tester is this report. Other uncommitted changes in the repo (baton/*.py, agents.json, extension.js and others) are the author's fixes, not the tester's.

---

# Round 6b: New chat retest

Date: 2026-10-26, 14:38–14:40 local. Tested by Claude (Claude desktop, computer use, VS Code at "click only" level) on `wwijatkowski.ai-baton` 0.3.0 reinstalled from the new .vsix (extension.js from 14:36). It maps `null` in `newArgs` to `undefined` (extension.js:313–314) and shows "Could not open …" when the command fails (extension.js:320). Nothing was installed or committed, settings and hooks were not changed, and nothing was sent to an agent; the new conversations were left empty.

## Summary

| # | Check | Result |
|---|-------|--------|
| 1 | ~/baton-test6 in a new window, Claude not open beforehand | PASS (folder recreated, see details) |
| 2 | New chat → new Claude conversation in an editor tab, no error | PASS |
| 3 | New chat again → a second, separate tab | PASS |
| 4 | Open → Claude in the side bar, as before | PASS |
| 5 | No "Could not open Claude" message; no TypeError in the Extension Host log | PASS |

## Details

**1 PASS.** `~/baton-test6` (like all earlier test folders) had been deleted since round 6: `open -a "Visual Studio Code" ~/baton-test6` answered "The file /Users/wiktorwijatkowski/baton-test6 does not exist." The tester recreated it with `git init` (no commits) and opened it in a new window, which showed Restricted Mode until the user trusted it. The restored window had no Claude view: the secondary side bar showed only Chat and Codex tabs and the editor only "Welcome", so nothing had to be closed. Initialize project was then run (the dialog, "Project ready…" toast, cards with "No checkpoint"), because a fresh folder shows only "This folder is not connected yet".

**2 PASS.** **New chat** on the Claude card opened an editor tab "Claude Code" beside Welcome. After a moment it showed an empty "Untitled" conversation (Claude Code logo, "You've come to the absolutely right place!", "Introducing Sonnet 5.5" card, input "⌘ Esc to focus or unfocus Claude", model "Opus 5.5"). No error notification.

**3 PASS.** A second **New chat** opened a second, separate tab: the editor group then had two tabs, both titled "Claude Code", the new one active. No error.

**4 PASS.** **Open** on the Claude card opened Claude Code in the secondary side bar ("Claude Code" tab next to Chat and Codex, an empty "Untitled" conversation, "Tired of repeating yourself? Tell Claude to remember what you've told it using CLAUDE.md."). The two editor tabs stayed open. New chat did not change where Open puts Claude.

**5 PASS.** No "Could not open Claude: …" message appeared at any step. The Extension Host log of this window (`logs/20261024T234158/window10/exthost/exthost.log`, 26 lines; its AI Baton output log names baton-test6) contains no `TypeError`, no `startsWith`, no `resolveTeleportedCopy` and no `claude-vscode.editor.open` error. The Output → AI Baton channel only shows the Initialize lines ("Done. Restart agent sessions in this folder.").

## Other observations (round 6b)

1. The test folders from rounds 5 and 6 no longer exist. `MANUAL_TEST.md` 1.4 assumes a fresh, initialized folder anyway, so recreating it is part of the step.
2. Both New chat tabs have the same title "Claude Code" until a message is sent, so two empty conversations look identical in the tab bar. That is Claude Code's naming, not AI Baton's.

## State left behind (round 6b)

- `~/baton-test6`: recreated, `git init` (no commits), initialized by AI Baton. Its window has two empty "Claude Code" editor tabs and Claude Code in the side bar. No messages were sent.
- The only file edited by the tester is this report.
