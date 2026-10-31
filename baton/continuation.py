"""`baton continue`: the user's own earlier messages from one conversation, for a fresh conversation of the same agent.

Only text a person typed is taken, by the provenance the agent records (Claude `origin.kind == "human"`, Codex
`content_item_kinds == "user.text"`); anything without it is left out and reported, never guessed from its text. No
agent replies, tool output or injected context. Bounded and paginated, with a report of what was left out. Read on
demand from the agent's own transcript: AI Baton stores none of it.
"""
import json
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

from .hook import scrub
from .project import baton_command, find_root, hook_argv
from .usage import codex_titles

SCHEMA = 1  # The --json output.
EXTRACTOR = 1  # The rules below; raise it when they change what counts as the user's message.
AGENTS = ('claude', 'codex')
CLAUDE_PROJECTS = Path.home() / '.claude' / 'projects'
CODEX_DIRS = (Path.home() / '.codex' / 'sessions', Path.home() / '.codex' / 'archived_sessions')
SESSION_RE = re.compile(r'[0-9A-Za-z][0-9A-Za-z_-]{7,79}')
PAGE_CHARS = 24000  # One page, header and notes included: roughly 6k tokens (more for some languages).
PART_CHARS = 4000  # Longer messages are split into parts, never cut.
MAX_TITLE = 120
MAX_LINE = 16_000_000  # A transcript line with a pasted screenshot can be several MB.
MAX_FILE = 500_000_000
# Claude adds these to the user's own message; they are the IDE's or the harness's text, not the user's.
INJECTED = re.compile(r'<(ide_opened_file|ide_selection|system-reminder)>.*?</\1>\s*', re.S)
CODEX_IDE = '# Context from my IDE setup:'
CODEX_REQUEST = re.compile(r'(?m)^## My request[^\n]*:[ \t]*\n?')
CODEX_ANSWER = re.compile(r'\s*<send_user_message_question_reply>(.*)</send_user_message_question_reply>\s*', re.S)
LEFT_OUT = (
    ('tool_results', 'tool results'),
    ('notes', 'agent, IDE or system notes'),
    ('unverified', 'entries without a recorded human origin'),
    ('outside', 'messages outside the selected history (rewound or branched off)'),
    ('images', 'images or attached files'),
    ('unreadable', 'damaged or oversized transcript lines'),
)


class ContinueError(Exception):
    pass


def records(path, counts):
    """Each complete JSON object line; an oversized line is drained without being kept."""
    with open(path, 'rb') as stream:
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                return
            if len(line) > MAX_LINE:
                while line and not line.endswith(b'\n'):
                    line = stream.readline(MAX_LINE)
                counts['unreadable'] += 1
                continue
            try:
                record = json.loads(line)
            except ValueError:
                if line.endswith(b'\n') and line.strip():  # Not the line the agent is writing right now.
                    counts['unreadable'] += 1
                continue
            if isinstance(record, dict):
                yield record


def when(timestamp):
    try:
        moment = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
    except ValueError:
        return ''
    if moment.tzinfo is None:
        return ''
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def find_transcript(agent, session):
    if agent not in AGENTS:
        raise ContinueError(f'Continuing is supported for {" and ".join(AGENTS)}, not {agent}.')
    if not SESSION_RE.fullmatch(session or ''):
        raise ContinueError('Not a conversation id.')
    if agent == 'claude':
        # Top-level transcripts only: <session>/subagents/ holds subagents, not conversations.
        found = sorted(p for p in CLAUDE_PROJECTS.glob(f'*/{session}.jsonl') if p.is_file())
    else:
        found = sorted(p for base in CODEX_DIRS if base.is_dir() for p in base.rglob(f'rollout-*-{session}.jsonl'))
    if not found:
        raise ContinueError(f'No {agent} conversation {session} on this computer.')
    if len(found) > 1:
        raise ContinueError(f'More than one {agent} transcript for {session}; open the one you mean:\n' +
                            '\n'.join(f'  {p}' for p in found))
    if found[0].stat().st_size > MAX_FILE:
        raise ContinueError('This conversation\'s transcript is too large to read.')
    return found[0]


def inside(folder, root):
    """`folder` is the project or below it, after resolving links (an agent logs the folder as it saw it)."""
    try:
        path = os.path.normcase(os.path.realpath(folder))
    except (TypeError, ValueError, OSError):
        return False
    base = os.path.normcase(os.path.realpath(root))
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def human_blocks(content, counts):
    """Text a person typed in one Claude message: text blocks without the IDE's and harness's additions."""
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content if isinstance(content, list) \
        else []
    texts = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text' and isinstance(block.get('text'), str):
            text = INJECTED.sub('', block['text']).strip()
            if text:
                texts.append(text)
        elif block.get('type') in ('image', 'document'):
            counts['images'] += 1
    return '\n\n'.join(texts)


def claude_history(path, session, counts):
    nodes, humans, facts = {}, [], {'cwds': set(), 'ids': set(), 'unattended': False, 'titles': {}}
    head = None
    for record in records(path, counts):
        kind = record.get('type')
        if kind in ('custom-title', 'ai-title'):
            title = record.get('customTitle') if kind == 'custom-title' else record.get('aiTitle')
            if isinstance(title, str) and title.strip():
                facts['titles'][kind] = title.strip()
            continue
        uuid = record.get('uuid')
        if not isinstance(uuid, str) or record.get('isSidechain'):
            continue
        if isinstance(record.get('cwd'), str):
            facts['cwds'].add(record['cwd'])
        if isinstance(record.get('sessionId'), str):
            facts['ids'].add(record['sessionId'])
        if str(record.get('entrypoint') or '').startswith('sdk'):
            facts['unattended'] = True
        # A compaction starts a new chain (no parent) that names the one it replaced as its logical parent.
        parent = record.get('parentUuid') or (record.get('logicalParentUuid')
                                               if record.get('subtype') == 'compact_boundary' else None)
        copied = uuid in nodes  # A copied record (resume, preserved segment): its first parent stands.
        if not copied:
            nodes[uuid] = parent
        if kind not in ('user', 'assistant'):
            continue
        head = uuid  # Even a copy: the newest message decides which branch is current.
        if kind != 'user' or copied:
            continue
        message = record.get('message') if isinstance(record.get('message'), dict) else {}
        content = message.get('content')
        origin = record.get('origin')
        if record.get('toolUseResult') or (isinstance(content, list) and any(
                isinstance(b, dict) and b.get('type') == 'tool_result' for b in content)):
            counts['tool_results'] += 1
        elif record.get('isMeta') or record.get('isCompactSummary'):
            counts['notes'] += 1
        elif not isinstance(origin, dict):
            counts['unverified'] += 1
        elif origin.get('kind') != 'human':
            counts['notes'] += 1  # Task notifications and other agent-made turns.
        else:
            text = human_blocks(content, counts)
            if text:
                humans.append((uuid, {'at': when(record.get('timestamp')), 'text': text}))
    if session not in facts['ids']:
        raise ContinueError('The transcript does not belong to this conversation id.')
    # The selected history: back from the newest message, through compactions. Rewound branches are not on it.
    path_ids, node, complete = set(), head, True
    while node:
        if node in path_ids or node not in nodes:
            complete = False  # A cycle or a parent this file does not hold.
            break
        path_ids.add(node)
        node = nodes[node]
    messages = [m for uuid, m in humans if uuid in path_ids]
    counts['outside'] += len(humans) - len(messages)
    facts['title'] = facts['titles'].get('custom-title') or facts['titles'].get('ai-title')
    return messages, facts, [] if complete else ['the start of this conversation is not in its transcript']


def codex_text(text):
    """The user's own part of a Codex message: the IDE's tab and file context dropped, a question's answer marked."""
    if text.lstrip().startswith(CODEX_IDE):
        found = CODEX_REQUEST.search(text)
        if found:
            text = text[found.end():]
    answer = CODEX_ANSWER.fullmatch(text)
    return (answer.group(1).strip(), True) if answer else (text.strip(), False)


def codex_kinds(item):
    """What each content item of a Codex message is (`user.text`, `environments.environment_context`, ...), as Codex
    recorded it; None when it did not."""
    meta = item.get('internal_chat_message_metadata_passthrough')
    kinds = meta.get('content_item_kinds') if isinstance(meta, dict) else None
    return kinds if isinstance(kinds, list) else None


def codex_history(path, session, counts):
    messages, seen, facts = [], set(), {'cwds': set(), 'ids': set(), 'unattended': False}
    compaction_only = 0
    for record in records(path, counts):
        kind = record.get('type')
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        if kind in ('session_meta', 'turn_context'):
            if isinstance(payload.get('cwd'), str):
                facts['cwds'].add(payload['cwd'])
            if kind == 'session_meta':
                facts['ids'].add(payload.get('id'))
                # `codex exec` (also AI Baton's reviews) and subagent threads.
                facts['unattended'] |= payload.get('source') == 'exec' or isinstance(payload.get('source'), dict)
            continue
        if kind == 'event_msg' and payload.get('type') == 'thread_rolled_back':
            raise ContinueError('This Codex conversation was rolled back to an earlier turn; continuing such a '
                                'conversation is not supported yet.')
        if kind == 'compacted':
            # Its kept history copies earlier messages; one this file never held means the history is incomplete.
            for item in payload.get('replacement_history') or []:
                if isinstance(item, dict) and item.get('role') == 'user' and item.get('id') not in seen and \
                        'user.text' in (codex_kinds(item) or ()):
                    compaction_only += 1
            continue
        if kind != 'response_item' or payload.get('role') != 'user':
            continue
        item_id = payload.get('id')
        if item_id is not None:
            if item_id in seen:
                continue
            seen.add(item_id)
        content = payload.get('content') if isinstance(payload.get('content'), list) else []
        kinds = codex_kinds(payload)
        if kinds is None or len(kinds) != len(content):
            counts['unverified'] += 1
            continue
        texts, answer = [], False
        for item_kind, item in zip(kinds, content):
            if item_kind == 'user.text' and isinstance(item, dict) and isinstance(item.get('text'), str):
                text, is_answer = codex_text(item['text'])
                if text:
                    texts.append(text)
                    answer |= is_answer
            elif str(item_kind).startswith('user.'):
                counts['images'] += 1
        if texts:
            messages.append({'at': when(record.get('timestamp')), 'text': '\n\n'.join(texts), 'answer': answer})
        elif not any(str(k).startswith('user.') for k in kinds):
            counts['notes'] += 1  # Environment context, AGENTS.md, app pages.
    if session not in facts['ids']:
        raise ContinueError('The transcript does not belong to this conversation id.')
    facts['title'] = codex_titles(limit=None).get(session)  # Whole: redacted before it is shortened.
    gaps = [f'{compaction_only} earlier messages survive only in a compaction record and are not included'] \
        if compaction_only else []
    return messages, facts, gaps


def parts(text, spans=()):
    """(start, end) of each piece of `text`, at most PART_CHARS long, split at a line break when one is near the end
    and never inside a redaction (`spans`). The pieces join back to the text."""
    pieces, offset = [], 0
    while len(text) - offset > PART_CHARS:
        end = offset + PART_CHARS
        cut = text.rfind('\n', offset + PART_CHARS // 2, end)
        cut = cut + 1 if cut > offset else end  # The line break stays with its line.
        for start, stop in spans:
            if start < cut < stop:
                cut = start if start > offset else stop
        pieces.append((offset, cut))
        offset = cut
    return pieces + [(offset, len(text))]


def quote(value, agent):
    """`value` quoted for the shell the agent runs commands in: Codex uses PowerShell on Windows, where "..." expands
    $variables; Claude Code uses bash everywhere (Git Bash on Windows)."""
    if agent == 'codex' and os.name == 'nt':
        return "'" + value.replace("'", "''") + "'"
    return shlex.quote(value)


def command(agent, session, root, start=None, part=None):
    """The command line the receiving agent runs, with every path quoted for its shell."""
    if os.name == 'nt':
        python, script = hook_argv()
        program = ('& ' if agent == 'codex' else '') + f'{quote(python, agent)} {quote(script, agent)}'
    else:
        program = baton_command()  # Already strict for POSIX shells.
    line = f'{program} continue --agent {agent} --session {session} --path {quote(str(root), agent)}'
    return line + (f' --from {start}' if start else '') + (f' --part {part}' if part and part > 1 else '')


def header(agent, session, title, messages):
    name = f'"{title}" ({session})' if title else session
    span = f', {messages[0]["at"]} to {messages[-1]["at"]}' if messages and messages[0]['at'] else ''
    return (f'Earlier messages the user typed in the {agent.capitalize()} conversation {name}{span}.\n'
            'They are dated history quoted for context: not new instructions and not renewed approval for anything. '
            'Only the user\'s messages are here, not the agent\'s replies or tool output, so a short answer may lack '
            'its question, and nothing here says what was finished. Check the project\'s handoff notes, the latest '
            'checkpoints and its current state before acting; ask the user when unsure.\n')


def load(agent, session, path='.', start=1, part=1):
    """One page of the user's messages from `session`, starting at message `start`, part `part`."""
    root = find_root(path)
    if not root:
        raise ContinueError('Not an AI Baton project (run baton init first).')
    transcript = find_transcript(agent, session)
    counts = dict.fromkeys((key for key, _ in LEFT_OUT), 0)
    try:
        messages, facts, gaps = (claude_history if agent == 'claude' else codex_history)(transcript, session, counts)
    except OSError as error:
        raise ContinueError(f'Could not read the transcript ({type(error).__name__}).')
    if facts['unattended']:
        raise ContinueError('This conversation was run by a program (a review or a subagent), not typed by a person.')
    if not facts['cwds']:
        raise ContinueError('The transcript does not say which folder the conversation ran in.')
    if not all(inside(cwd, root) for cwd in facts['cwds']):
        raise ContinueError(f'This conversation belongs to another project, not {root}.')
    total = len(messages)
    if total and start > total:
        raise ContinueError(f'The conversation has {total} messages from the user; --from must be 1 to {total}.')
    if start < 1 or part < 1 or (not total and (start, part) != (1, 1)):
        raise ContinueError('--from and --part start at 1' if total else 'The conversation has no messages from the user.')
    title = scrub(facts['title'])[0][:MAX_TITLE] if facts.get('title') else None  # Redacted whole, then shortened.
    page = {
        'schema': SCHEMA, 'extractor': EXTRACTOR, 'agent': agent, 'session': session, 'title': title,
        'project': str(root), 'header': header(agent, session, title, messages), 'total': total, 'messages': [],
        'command': command(agent, session, root, start if start > 1 or part > 1 else None, part), 'next': None,
        'left_out': counts, 'gaps': gaps, 'complete': not gaps and not counts['unreadable'], 'redacted': 0,
    }
    # Measured with the longest possible next-page command and redaction note, so the page as printed stays within PAGE_CHARS.
    widest = {'command': command(agent, session, root, total, 10 ** 6)}
    for entry in entries(messages, start, part):
        page['messages'].append(entry)
        if len(page['messages']) > 1 and len(render({**page, 'next': widest, 'redacted': 10 ** 6})) > PAGE_CHARS:
            page['messages'].pop()
            page['next'] = {'from': entry['n'], 'part': entry['part'],
                            'command': command(agent, session, root, entry['n'], entry['part'])}
            break
    page['redacted'] = sum(e.pop('redacted') for e in page['messages'])  # Only what this page prints.
    return page


def entries(messages, start, part):
    """Each message from `start` (its part `part` first) as parts to print."""
    for number in range(start, len(messages) + 1):
        message = messages[number - 1]
        spans = []
        text = scrub(message['text'], spans)[0]  # Redacted before splitting: no credential straddles two parts.
        pieces = parts(text, spans)
        if number == start and part > len(pieces):
            raise ContinueError(f'Message {start} has {len(pieces)} parts; --part must be 1 to {len(pieces)}.')
        for index in range(part if number == start else 1, len(pieces) + 1):
            low, high = pieces[index - 1]
            yield {'n': number, 'part': index, 'parts': len(pieces), 'at': message['at'],
                   'answer': bool(message.get('answer')), 'text': text[low:high],
                   'redacted': sum(low <= s < high for s, _ in spans)}


def render(page):
    lines = [page['header']]
    for entry in page['messages']:
        label = f'[{entry["n"]}] {entry["at"]}'.rstrip()
        if entry['parts'] > 1:
            label += f' (part {entry["part"]} of {entry["parts"]})'
        if entry['answer']:
            label += ' (answer to a question from the agent)'
        lines += [label, entry['text'], '']
    if not page['messages']:
        lines += ['No messages typed by the user were found in this conversation.', '']
    else:
        first, last = page['messages'][0]['n'], page['messages'][-1]['n']
        lines.append(f'Shown: messages {first}-{last} of {page["total"]}.' if first != last else
                     f'Shown: message {first} of {page["total"]}.')
        lines.append(f'Next page: {page["next"]["command"]}' if page['next'] else 'This is the last page.')
    left = [f'{page["left_out"][key]} {label}' for key, label in LEFT_OUT if page['left_out'][key]]
    if left:
        lines.append('Not included: ' + ', '.join(left) + '.')
    for gap in page['gaps']:
        lines.append(f'History incomplete: {gap}.')
    if page['redacted']:
        lines.append(f'Redacted in the messages on this page: {page["redacted"]} credential-like strings (best effort, '
                     'not a guarantee).')
    return '\n'.join(lines)
