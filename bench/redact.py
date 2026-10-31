"""Reduce a Codex rollout to the run itself before it is saved in this public repo.

An allowlist, not a blocklist: a rollout also describes the user's machine (account ids, installed skills,
connected apps, approved commands, personal instructions), and new Codex versions add new kinds of records.
Kept: the user's prompts, replies, tool calls and their output, reasoning, token counts and turn boundaries.
Everything else is dropped; in what is kept the home folder becomes ~ and the user name (e.g. file owners in
ls output) becomes "user".
    python3 bench/redact.py <rollout.jsonl> <out.jsonl>
"""
import json
import os
import re
import sys

EVENTS = {'task_started', 'task_complete', 'token_count', 'item_completed'}
ITEMS = {'custom_tool_call', 'custom_tool_call_output', 'function_call', 'function_call_output', 'reasoning'}
TURN_FIELDS = ('turn_id', 'cwd', 'model')
# Codex's own additions sent as user messages: project/global instructions and the environment.
INJECTED = ('# AGENTS.md instructions', '<environment_context', '<user_instructions', '<turn_aborted')


def message_text(payload):
    return ''.join(c.get('text', '') for c in payload.get('content') or [] if isinstance(c, dict))


def kept(entry):
    """The entry to save (possibly reduced), or None to drop it."""
    kind = entry.get('type')
    payload = entry.get('payload') if isinstance(entry.get('payload'), dict) else {}
    if kind == 'token_usage_record':
        return entry
    if kind == 'event_msg' and payload.get('type') in EVENTS:
        return entry
    if kind == 'turn_context':
        return {**entry, 'payload': {k: payload[k] for k in TURN_FIELDS if k in payload}}
    if kind == 'response_item':
        if payload.get('type') in ITEMS:
            return entry
        if payload.get('type') == 'message' and payload.get('role') == 'assistant':
            return entry
        if payload.get('type') == 'message' and payload.get('role') == 'user' \
                and not message_text(payload).lstrip().startswith(INJECTED):
            return entry
    return None


def redact(text, home=None):
    home = (home or os.path.expanduser('~')).rstrip('/')
    name = re.compile(r'\b%s\b' % re.escape(os.path.basename(home)))
    out = []
    for line in text.splitlines():
        entry = kept(json.loads(line)) if line.strip() else None
        if entry is not None:
            saved = json.dumps(entry, ensure_ascii=False).replace(home + '/', '~/').replace(home, '~')
            out.append(name.sub('user', saved) + '\n')
    return ''.join(out)


def copy(src, dst):
    with open(src, encoding='utf-8') as f:
        text = f.read()
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(redact(text))


if __name__ == '__main__':
    copy(sys.argv[1], sys.argv[2])
