"""`baton metrics`: one summary per conversation, kept after the agents delete their transcripts (Claude Code after 30
days by default). No prompts, replies, file names or paths: counts, the session id, client and model names, and a hash
of the project folder. Stays on this machine. Descriptive data for docs/knowledge/SAVINGS_PLAN.md, never the source of
savings claims.

Claude Code: ~/.claude/projects/*/<session>.jsonl, subagents in */<session>/subagents/*.jsonl (usage per API message,
             deduplicated by message id, also across files)
Codex:       ~/.codex/sessions/**/rollout-*.jsonl  (cumulative token_count events, as usage.py reads them; a resumed
             session's files are one conversation, repeated records counted once)

A conversation is parsed again only when one of its files changed (size or mtime), so `collect` can run often. Its
summary stays once a transcript is gone (it is not parsed again from what is left).
"""
import hashlib
import json
import os
import re
import statistics
from datetime import datetime
from pathlib import Path

from . import models
from .project import file_lock, find_root, read_json, write_json

STORE = Path.home() / '.cache' / 'ai-baton' / 'metrics' / 'conversations.json'
SOURCES = {
    'claude': (Path.home() / '.claude' / 'projects', ('*/*.jsonl', '*/*/subagents/*.jsonl')),
    'codex': (Path.home() / '.codex' / 'sessions', ('**/rollout-*.jsonl',)),
}
VERSION = 3  # Of the summary format: summaries of an older version are parsed again.
USAGE = ('input', 'cache_write', 'cache_read', 'output')  # input = uncached input tokens.
CLAUDE_EDITS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
# Shell commands that change files: a heuristic, so the boundary is an attempted change (first_edit.kind says how it
# was seen). Redirects into temporary folders, /dev/null or another stream do not count; nor does --help.
SHELL_EDIT = re.compile(r'\bsed\s+-i|\bperl\s+-p?i\b|(?<![-=<>&\d])>{1,2}\s*(?![&\s]|/dev/|/tmp/|/private/|/var/folders/)'
                        r'[\w~./"\'$]|\btee\s+(?!/dev/)|\bgit\s+(apply|checkout\s+--|restore)\b(?!.*--help)'
                        r'|\b(Set-Content|Add-Content|Out-File)\b', re.IGNORECASE)
# Writing the handoff or AI Baton's memory is bookkeeping, not the first change to the work.
BOOKKEEPING = re.compile(r'(^|/)(docs/(AGENT_HANDOFF|STATUS)\.md|docs/knowledge/[^/]+|\.agent-memory/.*)$')
PATCH_FILE = re.compile(r'\*\*\* (?:Add|Update|Delete) File: ([^\n\\"]+)')
CODEX_COMMAND = re.compile(r'\bcmd:\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)')
CODEX_TOOL = re.compile(r'tools\.(\w+)\(')
CODEX_INJECTED = ('# AGENTS.md instructions', '<environment_context', '<user_instructions', '<turn_aborted')
# AI Baton's hook context: the first delivery starts with BASE_CONTEXT, later ones may only hold new checkpoints.
BATON_MARKS = ('This project uses AI Baton', 'historical checkpoints from other agents', 'baton recall')
# One delivered checkpoint (hook.checkpoint_text): "[codex] 2026-..." or "[claude, your other conversation] 2026-...".
CHECKPOINT = re.compile(r'^\[([a-z0-9-]+)(, your other conversation)?\] \d{4}-\d\d-\d\d', re.MULTILINE)
REVIEW_MARK = "You are reviewing a teammate's change"  # review.PROMPT
BENCH_FOLDER = '/baton-bench-'  # bench/run.py works in /tmp/baton-bench-*: not field data.


def project_id(cwd):
    return hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12] if cwd else None


def file_id(path):
    return hashlib.sha256(str(path).encode()).hexdigest()[:16]


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None


def records(path):
    """(digest of the line, record): the digest tells a record repeated in another file of the conversation."""
    with open(path, 'rb') as stream:
        for line in stream:
            try:
                record = json.loads(line.decode('utf-8', 'replace'))
            except ValueError:
                continue  # A line still being written, or damaged.
            if isinstance(record, dict):
                yield hashlib.blake2b(line.rstrip(b'\r\n'), digest_size=12).digest(), record


def texts(content):
    """The text of a message's content (a string, or a list of blocks); None when it holds tool results."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
        return None
    return ' '.join(b.get('text', '') for b in content if isinstance(b, dict) and isinstance(b.get('text'), str))


SHELL_TARGET = re.compile(r'(?:(?<![-=<>&\d])>{1,2}|\btee\s+(?:-a\s+)?|\b(?:Set-Content|Add-Content|Out-File)\s+(?:-Path\s+)?)'
                          r'\s*["\']?([^\s"\';|&>]+)', re.IGNORECASE)


def shell_edit(command):
    """True when a shell command looks like it changes files other than the handoff and AI Baton's memory."""
    if not isinstance(command, str) or not SHELL_EDIT.search(command):
        return False
    targets = SHELL_TARGET.findall(command)
    # Only redirects, tee and Set-Content name their files plainly; sed -i, git apply and the like count as edits.
    plain = not re.search(r'\bsed\s+-i|\bperl\s+-p?i\b|\bgit\s+(apply|checkout|restore)\b', command, re.IGNORECASE)
    return not (plain and targets and bookkeeping(targets))


def bookkeeping(paths):
    """True when every file named is the handoff or AI Baton's memory."""
    paths = [p for p in paths if isinstance(p, str) and p]
    return bool(paths) and all(BOOKKEEPING.search(p.replace('\\', '/')) for p in paths)


class Summary:
    """What one conversation adds up to while its records are read in order (all of its files)."""

    def __init__(self, agent):
        self.agent = agent
        self.session = self.cwd = self.client = None
        self.models, self.first, self.last = set(), None, None
        self.prompts = self.tool_calls = self.deliveries = self.injected_chars = 0
        self.checkpoints = {'own': 0, 'other_agent': 0}
        self.review = False
        self.usage, self.subagents = dict.fromkeys(USAGE, 0), dict.fromkeys(USAGE, 0)
        self.by_request = {}  # request id -> its usage (the first time it is seen)
        self.requests = self.subagent_requests = 0
        self.first_edit = None
        self.seen_lines = set()

    def seen(self, record):
        moment = timestamp(record.get('timestamp'))
        if moment:
            self.first = min(self.first, moment) if self.first else moment
            self.last = max(self.last, moment) if self.last else moment

    def context(self, text):
        if not any(mark in text for mark in BATON_MARKS):
            return
        self.deliveries += 1
        self.injected_chars += len(text)
        for agent, own in CHECKPOINT.findall(text):
            self.checkpoints['own' if own or agent == self.agent else 'other_agent'] += 1

    def prompt(self, text):
        if text and text.strip():
            self.prompts += 1
            self.review = self.review or REVIEW_MARK in text

    def spent(self, values, request=None, subagent=False):
        """One API request's usage, once per request id."""
        if request is not None:
            if request in self.by_request:
                return
            self.by_request[request] = values
        if subagent:
            self.subagent_requests += 1
            for key in USAGE:
                self.subagents[key] += max(values.get(key, 0), 0)
            return
        self.requests += 1
        for key in USAGE:
            self.usage[key] += max(values.get(key, 0), 0)

    def tool(self, edit_kind=None, request=None):
        """A tool call; `edit_kind` when it tried to change files (the first one ends the orientation). What was spent
        before it leaves out the request that made the call, wherever its usage was logged."""
        if edit_kind and self.first_edit is None:
            own = self.by_request.get(request) or {}
            self.first_edit = {'kind': edit_kind, 'tool_calls_before': self.tool_calls,
                               'usage_before': {k: self.usage[k] - max(own.get(k, 0), 0) for k in USAGE},
                               'requests_before': self.requests - (1 if request in self.by_request else 0),
                               'seconds': round((self.last - self.first).total_seconds()) if self.first and self.last else None}
        self.tool_calls += 1

    def result(self, source):
        root = find_root(self.cwd) if self.cwd and os.path.isdir(self.cwd) else None
        known = self.requests > 0
        return {
            'version': VERSION, 'agent': self.agent, 'session': self.session, 'client': self.client,
            'project': project_id(self.cwd), 'baton_project': root is not None,
            'models': sorted(self.models), 'started': self.first and self.first.isoformat(),
            'ended': self.last and self.last.isoformat(),
            'seconds': round((self.last - self.first).total_seconds()) if self.first and self.last else None,
            'prompts': self.prompts, 'requests': self.requests,
            # None, not zeros, when the transcript held no usage at all: unknown is not free.
            'usage': self.usage if known else None,
            'subagents': {'requests': self.subagent_requests, 'usage': self.subagents} if self.subagent_requests else None,
            'tool_calls': self.tool_calls,
            # Seen even without usage; its tokens are then unknown.
            'first_edit': self.first_edit and {**self.first_edit, 'usage_before': self.first_edit['usage_before'] if known else None},
            'baton': {'deliveries': self.deliveries, 'chars': self.injected_chars, 'checkpoints': self.checkpoints},
            'review': self.review, 'bench': bool(self.cwd and BENCH_FOLDER in self.cwd), 'source': source,
        }


def parse_claude(summary, path, subagent=False):
    for line, record in records(path):
        if line in summary.seen_lines:
            continue  # The same record in another file of this conversation.
        summary.seen_lines.add(line)
        message = record.get('message') if isinstance(record.get('message'), dict) else {}
        if subagent or record.get('isSidechain'):
            # Subagents: their spending counts toward the conversation, not toward its orientation.
            usage = message.get('usage')
            if record.get('type') == 'assistant' and isinstance(usage, dict):
                summary.spent(claude_usage(usage), message.get('id') or record.get('uuid'), subagent=True)
            continue
        summary.seen(record)
        summary.cwd = summary.cwd or record.get('cwd')
        summary.client = summary.client or record.get('entrypoint')
        attachment = record.get('attachment') or {}
        if attachment.get('type') == 'hook_additional_context':
            summary.context(' '.join(c for c in attachment.get('content') or [] if isinstance(c, str)))
        content = message.get('content')
        if record.get('type') == 'user' and not record.get('isMeta'):
            summary.prompt(texts(content))
        if record.get('type') != 'assistant':
            continue
        model = message.get('model')
        if isinstance(model, str) and model and not model.startswith('<'):
            summary.models.add(model)
        request = message.get('id') or record.get('uuid')
        if isinstance(message.get('usage'), dict):
            summary.spent(claude_usage(message['usage']), request)
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                name, args = block.get('name'), block.get('input') if isinstance(block.get('input'), dict) else {}
                edit = 'tool' if name in CLAUDE_EDITS and not bookkeeping([args.get('file_path') or args.get('notebook_path')]) \
                    else 'shell' if name == 'Bash' and shell_edit(args.get('command')) else None
                summary.tool(edit, request)


def claude_usage(usage):
    return {'input': usage.get('input_tokens') or 0, 'cache_write': usage.get('cache_creation_input_tokens') or 0,
            'cache_read': usage.get('cache_read_input_tokens') or 0, 'output': usage.get('output_tokens') or 0}


def parse_codex(summary, path, subagent=False):
    previous = None  # Per file: a resumed session's file starts its counter again.
    for line, record in records(path):
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        kind = record.get('type')
        if kind == 'session_meta':
            summary.session = summary.session or payload.get('id')
            summary.cwd = summary.cwd or payload.get('cwd')
            summary.client = summary.client or payload.get('originator')
            continue
        if kind == 'event_msg' and payload.get('type') == 'token_count':
            total = (payload.get('info') or {}).get('total_token_usage')
            if not isinstance(total, dict) or (previous and total.get('total_tokens') == previous.get('total_tokens')):
                continue
            grew = previous and total.get('total_tokens', 0) > previous.get('total_tokens', 0)
            delta = {k: total.get(k, 0) - previous.get(k, 0) for k in total} if grew else \
                (payload.get('info') or {}).get('last_token_usage') or total
            previous = total
            if line in summary.seen_lines:
                continue  # Copied into a resumed session's file: spent once.
            summary.seen_lines.add(line)
            summary.seen(record)
            cached = delta.get('cached_input_tokens', 0)
            summary.spent({'input': delta.get('input_tokens', 0) - cached, 'cache_read': cached,
                           'cache_write': delta.get('cache_write_input_tokens', 0), 'output': delta.get('output_tokens', 0)})
            continue
        if line in summary.seen_lines:
            continue
        summary.seen_lines.add(line)
        summary.seen(record)
        if kind == 'turn_context':
            summary.cwd = summary.cwd or payload.get('cwd')
            if payload.get('model'):
                summary.models.add(payload['model'])
        elif kind == 'response_item' and payload.get('type') == 'message' and payload.get('role') in ('user', 'developer'):
            text = texts(payload.get('content')) or ''
            if payload['role'] == 'developer':
                summary.context(text)  # Hook context comes as a developer message.
            elif not text.lstrip().startswith(CODEX_INJECTED):  # Codex's own additions (AGENTS.md...) come as user ones.
                summary.prompt(text)
        elif kind == 'response_item' and payload.get('type') in ('custom_tool_call', 'function_call'):
            codex_tools(summary, payload)


def codex_tools(summary, payload):
    code = payload.get('input') or payload.get('arguments') or ''
    if not isinstance(code, str):
        code = json.dumps(code)
    patch = lambda: 'tool' if not bookkeeping(PATCH_FILE.findall(code)) else None
    name = payload.get('name')
    if name != 'exec':
        command = ''
        if name == 'exec_command':
            try:
                command = (json.loads(code) or {}).get('cmd') or ''
            except (ValueError, AttributeError):
                command = code
        summary.tool(patch() if name == 'apply_patch' else 'shell' if shell_edit(command) else None)
        return
    # One exec runs JavaScript that calls tools; its shell commands are the cmd: strings, in order.
    commands = iter(CODEX_COMMAND.findall(code))
    for tool in CODEX_TOOL.findall(code):
        command = next(commands, '') if tool == 'exec_command' else ''
        summary.tool(patch() if tool == 'apply_patch' else 'shell' if shell_edit(command) else None)


PARSERS = {'claude': parse_claude, 'codex': parse_codex}


def session_of(agent, path):
    """(session, subagent?) of a transcript file, read cheaply."""
    if agent == 'claude':
        if path.parent.name == 'subagents':
            return path.parent.parent.name, True
        return path.stem, False
    try:
        with open(path, encoding='utf-8', errors='replace') as stream:
            first = json.loads(stream.readline() or '{}')
        found = (first.get('payload') or {}).get('id') if first.get('type') == 'session_meta' else None
    except (OSError, ValueError, AttributeError):
        found = None
    return found or path.stem, False


def conversations_on_disk(sources):
    """{key: [(path, subagent?, {'file', 'size', 'mtime'})]} of every transcript file, grouped by conversation."""
    found = {}
    for agent, (base, patterns) in sources.items():
        if not base.is_dir():
            continue
        for pattern in patterns:
            for path in base.glob(pattern):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                session, subagent = session_of(agent, path)
                found.setdefault(f'{agent}:{session}', []).append(
                    (path, subagent, {'file': file_id(path), 'size': stat.st_size, 'mtime': int(stat.st_mtime)}))
    return found


def collect(store=None, sources=None):
    """Summarize every new or changed conversation; returns {'updated', 'conversations', 'errors'}."""
    store = Path(store or STORE)
    store.parent.mkdir(parents=True, exist_ok=True)
    reviews = set(models.review_sessions())
    with file_lock(store.with_name(store.name + '.lock'), timeout=10):
        data = read_json(store, {}) if store.exists() else {}
        conversations = data.get('conversations') if isinstance(data, dict) else None
        # Summaries of an older format (other keys and fields) are rebuilt from the transcripts still on disk.
        conversations = {k: v for k, v in (conversations if isinstance(conversations, dict) else {}).items()
                         if isinstance(v, dict) and v.get('version') == VERSION}
        updated = errors = 0
        for key, files in conversations_on_disk(sources or SOURCES).items():
            agent = key.split(':', 1)[0]
            files.sort(key=lambda f: (f[1], f[2]['mtime']))  # Main files first, oldest first.
            source = [f[2] for f in files]
            known = conversations.get(key)
            if known and known.get('version') == VERSION:
                if known.get('source') == source:
                    continue
                if not {f['file'] for f in known.get('source') or []} <= {f['file'] for f in source}:
                    continue  # A file is gone: what is left would summarize less than we have.
            try:
                summary = Summary(agent)
                summary.session = key.split(':', 1)[1]
                for path, subagent, _ in files:
                    PARSERS[agent](summary, path, subagent)
                result = summary.result(source)
            except Exception:  # noqa: BLE001 (one odd transcript must not stop the others)
                errors += 1
                continue
            result['review'] = result['review'] or result['session'] in reviews
            if not result['requests'] and not result['prompts']:
                continue  # Nothing happened in it (an opened and closed chat).
            conversations[key] = result
            updated += 1
        write_json(store, {'version': VERSION, 'conversations': conversations}, private=True)
    return {'updated': updated, 'conversations': len(conversations), 'errors': errors}


def tokens(usage, cached=False):
    """Tokens a conversation processed: uncached input, cache writes and output; cache reads only when asked (they
    are billed and counted against limits at a fraction)."""
    return sum(usage.get(k, 0) for k in USAGE if cached or k != 'cache_read')


def report(store=None):
    """Descriptive groups per agent: another agent's checkpoint delivered / only its own other conversations' / AI
    Baton context without checkpoints / none. Not a comparison of like with like: projects and tasks differ."""
    path = Path(store or STORE)
    data = read_json(path, {}) if path.exists() else {}
    everything = [c for c in (data.get('conversations') or {}).values() if isinstance(c, dict) and c.get('version') == VERSION]
    rows = [c for c in everything if not c.get('review') and not c.get('bench')]
    groups = {}
    for row in rows:
        baton = row.get('baton') or {}
        seen = baton.get('checkpoints') or {}
        kind = 'other agent\'s checkpoint' if seen.get('other_agent') else 'own checkpoints only' if seen.get('own') \
            else 'AI Baton context' if baton.get('deliveries') else 'no AI Baton context'
        groups.setdefault((row['agent'], kind), []).append(row)
    median = lambda values: round(statistics.median(values)) if values else None
    out = []
    for (agent, kind), group in sorted(groups.items()):
        known = [r for r in group if r.get('usage') is not None]
        edited = [r for r in group if r.get('first_edit')]
        out.append({
            'agent': agent, 'group': kind, 'conversations': len(group), 'usage_unknown': len(group) - len(known),
            'with_edit_attempt': len(edited),
            'median_tokens': median([tokens(r['usage']) for r in known]),  # Cache reads left out.
            'median_usage': {k: median([r['usage'][k] for r in known]) for k in USAGE},
            'median_tool_calls_before_first_edit': median([r['first_edit']['tool_calls_before'] for r in edited]),
            'median_tokens_before_first_edit': median([tokens(r['first_edit']['usage_before']) for r in edited
                                                       if r['first_edit']['usage_before'] is not None]),
            'median_injected_chars': median([r['baton']['chars'] for r in group if r['baton']['deliveries']]),
        })
    return {'conversations': len(rows), 'reviews_left_out': sum(1 for c in everything if c.get('review')),
            'bench_left_out': sum(1 for c in everything if c.get('bench') and not c.get('review')),
            'median_tokens_counts': 'uncached input + cache writes + output (cache reads left out)', 'groups': out}
