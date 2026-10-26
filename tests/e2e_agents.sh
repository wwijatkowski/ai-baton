#!/bin/sh
# End-to-end shared memory with the real agents (uses a few thousand tokens of each plan; not part of unittest).
# Needs the global hooks installed (`baton install-hooks`) and approved in Codex.
# Usage: sh tests/e2e_agents.sh [folder]   (default: a new temp folder)
set -eu
BATON="$(cd "$(dirname "$0")/.." && pwd)/bin/baton"
CLAUDE=$(ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | tail -1)
CODEX=$(command -v codex || ls -d "$HOME"/.vscode/extensions/openai.chatgpt-*/bin/*/codex 2>/dev/null | tail -1)
DIR=${1:-$(mktemp -d)}
fail() { echo "FAIL: $1"; exit 1; }

[ -x "$CLAUDE" ] || fail "Claude CLI not found"
[ -x "$CODEX" ] || fail "Codex CLI not found"
mkdir -p "$DIR" && cd "$DIR"
git init -q && git commit -q --allow-empty -m init
python3 "$BATON" init . >/dev/null
[ ! -e .claude ] && [ ! -e .codex ] || fail "init wrote project hooks although global hooks exist"
python3 "$BATON" hook-status . | grep -q "codex *ok" || fail "Codex hooks not approved: $(python3 "$BATON" hook-status .)"

echo "1/3 Claude makes a change"
"$CLAUDE" -p "AI Baton test. Create NOTES.md containing 'Favourite colour: teal'. Replace the 'Recently done' section of docs/AGENT_HANDOFF.md with one bullet about it. Reply in one sentence." \
  --permission-mode acceptEdits >/dev/null
echo "2/3 Codex answers from shared memory"
"$CODEX" exec --sandbox read-only --skip-git-repo-check \
  "AI Baton test. Without reading files, answer from your start context only: which favourite colour did the previous agent record? One word." \
  2>/dev/null | tail -1 | grep -qi teal || fail "Codex did not get Claude's checkpoint"
echo "3/3 Claude answers from Codex's checkpoint"
"$CLAUDE" -p "AI Baton test. Without reading files or tools, answer from your start context only: did a Codex checkpoint mention teal? Answer yes or no." \
  | grep -qi yes || fail "Claude did not get Codex's checkpoint"

python3 - <<'EOF' || fail "history check"
import json
rows = [json.loads(l) for l in open('.agent-memory/history.jsonl')]
assert [r['agent'] for r in rows] == ['claude', 'codex', 'claude'], [r['agent'] for r in rows]
assert [bool(r.get('handoff_updated')) for r in rows] == [True, False, False], 'handoff flags'
state = {k: v['state'] for k, v in json.load(open('.agent-memory/activity.json')).items()}
assert set(state.values()) == {'idle'}, state
EOF
echo "PASS ($DIR)"
