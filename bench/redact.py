"""Strip a Codex rollout of the agent's own configuration before it is saved in this public repo.

The rollout's first entries describe the user's machine, not the run: account ids (session_meta), installed
skills, connected apps and approved commands (developer messages, world_state). The run itself (prompts,
replies, tool calls, token counts) is kept.
    python3 bench/redact.py <rollout.jsonl> <out.jsonl>
"""
import json
import sys

DROP_TYPES = {'session_meta', 'world_state'}


def keep(entry):
    if entry.get('type') in DROP_TYPES:
        return False
    payload = entry.get('payload') or {}
    return not (entry.get('type') == 'response_item'
                and (payload.get('role') == 'developer' or payload.get('type') == 'additional_tools'))


def redact(text):
    return ''.join(line for line in text.splitlines(keepends=True) if line.strip() and keep(json.loads(line)))


def copy(src, dst):
    with open(src, encoding='utf-8') as f:
        text = f.read()
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(redact(text))


if __name__ == '__main__':
    copy(sys.argv[1], sys.argv[2])
