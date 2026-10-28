"""`baton metrics`: one summary per conversation, kept after the agents delete their transcripts (Claude Code after 30
days by default). Counts only: no prompts, replies, file names or paths; the project is a hash of its folder. Stays on
this machine. Descriptive data for docs/knowledge/SAVINGS_PLAN.md, never the source of savings claims.

Claude Code: ~/.claude/projects/*/<session>.jsonl  (usage per API message, deduplicated by message id)
Codex:       ~/.codex/sessions/**/rollout-*.jsonl  (cumulative token_count events, as usage.py reads them)

A conversation is parsed again only when its file changed (size or mtime), so `collect` can run often; a summary stays
when its transcript is gone.
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
    'claude': (Path.home() / '.claude' / 'projects', '*/*.jsonl'),
    'codex': (Path.home() / '.codex' / 'sessions', '**/rollout-*.jsonl'),
}
VERSION = 2  # Of the summary format: summaries of an older version are parsed again.
USAGE = ('input', 'cache_write', 'cache_read', 'output')  # input = uncached input tokens.
CLAUDE_EDITS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
# Shell commands that change files: a heuristic, named as such in the summary (first_edit.kind).
# Redirects into temporary folders, /dev/null or another stream do not count.
SHELL_EDIT = re.compile(r'\bsed\s+-i|\bperl\s+-p?i\b|(?<![-=<>&\d])>{1,2}\s*(?![&\s]|/dev/|/tmp/|/private/|/var/folders/)'
                        r'[\w~./"\'$]|\btee\s+(?!/dev/)|\bgit\s+(apply|checkout\s+--|restore)\b')
CODEX_COMMAND = re.compile(r'\bcmd:\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)')
CODEX_INJECTED = ('# AGENTS.md instructions', '<environment_context', '<user_instructions', '<turn_aborted')
BATON_MARK = 'This project uses AI Baton'
OTHER_CHECKPOINTS = 'checkpoints from other agents'  # hook.DATA_NOTICE: another agent's work was delivered.
REVIEW_MARK = "You are reviewing a teammate's change"  # review.PROMPT


def project_id(cwd):
    return hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12] if cwd else None


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None


def records(path):
    with open(path, encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                continue  # A line still being written, or damaged.
            if isinstance(record, dict):
                yield record


class Summary:
    """What one conversation adds up to while its records are read in order."""

    def __init__(self, agent):
        self.agent = agent
        self.session = self.cwd = self.client = None
        self.models, self.first, self.last = set(), None, None
        self.prompts = self.tool_calls = self.injections = self.injected_chars = 0
        self.other_checkpoint = self.review = False
        self.usage = dict.fromkeys(USAGE, 0)
        self.requests = 0
        self.first_edit = None

    def seen(self, record):
        moment = timestamp(record.get('timestamp'))
        if moment:
            self.first = self.first or moment
            self.last = moment

    def context(self, text):
        if BATON_MARK in text:
            self.injections += 1
            self.injected_chars += len(text)
            self.other_checkpoint = self.other_checkpoint or OTHER_CHECKPOINTS in text

    def spent(self, values):
        self.requests += 1
        for key in USAGE:
            self.usage[key] += max(values.get(key, 0), 0)

    def tool(self, edit_kind=None):
        """A tool call; `edit_kind` when it changed files (the first one is the end of orientation). What was spent
        before it leaves out the request that made the call."""
        if edit_kind and self.first_edit is None:
            self.first_edit = {'kind': edit_kind, 'tool_calls_before': self.tool_calls,
                               'usage_before': dict(self.usage), 'requests_before': self.requests,
                               'seconds': round((self.last - self.first).total_seconds()) if self.first and self.last else None}
        self.tool_calls += 1

    def result(self, source):
        root = find_root(self.cwd) if self.cwd and os.path.isdir(self.cwd) else None
        return {
            'version': VERSION, 'agent': self.agent, 'session': self.session, 'client': self.client,
            'project': project_id(self.cwd), 'baton_project': root is not None,
            'models': sorted(self.models), 'started': self.first and self.first.isoformat(),
            'ended': self.last and self.last.isoformat(),
            'seconds': round((self.last - self.first).total_seconds()) if self.first and self.last else None,
            'prompts': self.prompts, 'requests': self.requests, 'usage': self.usage,
            'tool_calls': self.tool_calls, 'first_edit': self.first_edit,
            'baton': {'injections': self.injections, 'chars': self.injected_chars,
                      'other_checkpoint': self.other_checkpoint},
            'review': self.review, 'source': source,
        }


def shell_edit(command):
    return isinstance(command, str) and bool(SHELL_EDIT.search(command))


def parse_claude(path):
    summary = Summary('claude')
    summary.session = path.stem
    summary.review = path.stem in set(models.review_sessions())
    counted = {}  # message id -> usage: one API message is logged once per content block.
    for record in records(path):
        if record.get('isSidechain'):
            continue  # Subagents: their own transcripts, not this conversation's orientation.
        summary.seen(record)
        summary.cwd = summary.cwd or record.get('cwd')
        summary.client = summary.client or record.get('entrypoint')
        attachment = record.get('attachment') or {}
        if attachment.get('type') == 'hook_additional_context':
            summary.context(' '.join(c for c in attachment.get('content') or [] if isinstance(c, str)))
        message = record.get('message') if isinstance(record.get('message'), dict) else {}
        content = message.get('content')
        if record.get('type') == 'user' and isinstance(content, str) and not record.get('isMeta'):
            summary.prompts += 1
        if record.get('type') != 'assistant':
            continue
        model = message.get('model')
        if isinstance(model, str) and model and not model.startswith('<'):
            summary.models.add(model)
        # Tools first: usage before an edit leaves out the request that made it (as Codex logs it, after the call).
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                name, args = block.get('name'), block.get('input') or {}
                summary.tool('tool' if name in CLAUDE_EDITS else
                             'shell' if name == 'Bash' and shell_edit(args.get('command')) else None)
        usage, key = message.get('usage'), message.get('id') or record.get('uuid')
        if isinstance(usage, dict) and key not in counted:
            counted[key] = True
            summary.spent({'input': usage.get('input_tokens') or 0, 'cache_write': usage.get('cache_creation_input_tokens') or 0,
                           'cache_read': usage.get('cache_read_input_tokens') or 0, 'output': usage.get('output_tokens') or 0})
    return summary


CODEX_TOOL = re.compile(r'tools\.(\w+)\(')


def parse_codex(path):
    summary = Summary('codex')
    previous = None
    for record in records(path):
        summary.seen(record)
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        kind = record.get('type')
        if kind == 'session_meta':
            summary.session = payload.get('id') or summary.session
            summary.cwd = summary.cwd or payload.get('cwd')
            summary.client = summary.client or payload.get('originator')
        elif kind == 'turn_context':
            summary.cwd = summary.cwd or payload.get('cwd')
            if payload.get('model'):
                summary.models.add(payload['model'])
        elif kind == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
            text = ' '.join(c.get('text', '') for c in payload.get('content') or [] if isinstance(c, dict))
            if not text.lstrip().startswith(CODEX_INJECTED):  # Codex's own additions are logged as user messages too.
                summary.prompts += 1
                summary.review = summary.review or REVIEW_MARK in text
        elif kind == 'event_msg' and payload.get('type') == 'token_count':
            total = (payload.get('info') or {}).get('total_token_usage')
            if not isinstance(total, dict) or (previous and total.get('total_tokens') == previous.get('total_tokens')):
                continue
            grew = previous and total.get('total_tokens', 0) > previous.get('total_tokens', 0)
            delta = {k: total.get(k, 0) - previous.get(k, 0) for k in total} if grew else \
                (payload.get('info') or {}).get('last_token_usage') or total
            previous = total
            cached = delta.get('cached_input_tokens', 0)
            summary.spent({'input': delta.get('input_tokens', 0) - cached, 'cache_read': cached,
                           'cache_write': delta.get('cache_write_input_tokens', 0), 'output': delta.get('output_tokens', 0)})
        elif kind == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'developer':
            summary.context(' '.join(c.get('text', '') for c in payload.get('content') or [] if isinstance(c, dict)))
        elif kind == 'response_item' and payload.get('type') in ('custom_tool_call', 'function_call'):
            code = payload.get('input') or payload.get('arguments') or ''
            if payload.get('name') != 'exec':
                summary.tool('tool' if payload.get('name') == 'apply_patch' else None)
                continue
            # One exec runs JavaScript that calls tools; its shell commands are the cmd: strings, in order.
            commands = iter(CODEX_COMMAND.findall(code))
            for name in CODEX_TOOL.findall(code):
                command = next(commands, '') if name == 'exec_command' else ''
                summary.tool('tool' if name == 'apply_patch' else 'shell' if shell_edit(command) else None)
    if summary.session is None:
        summary.session = path.stem
    return summary


PARSERS = {'claude': parse_claude, 'codex': parse_codex}


def collect(store=None, sources=None):
    """Summarize every new or changed conversation; returns (added or updated, kept)."""
    store = Path(store or STORE)
    store.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(store.with_name(store.name + '.lock'), timeout=10):
        data = read_json(store, {}) if store.exists() else {}
        conversations = data.get('conversations') if isinstance(data, dict) else None
        conversations = conversations if isinstance(conversations, dict) else {}
        changed = 0
        for agent, (base, pattern) in (sources or SOURCES).items():
            if not base.is_dir():
                continue
            for path in base.glob(pattern):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                source = {'size': stat.st_size, 'mtime': int(stat.st_mtime)}
                # Keyed by file, not session: a resumed Codex session writes a new file with the same id.
                key = f'{agent}:{hashlib.sha256(str(path).encode()).hexdigest()[:16]}'
                known = conversations.get(key)
                if known and known.get('source') == source and known.get('version') == VERSION:
                    continue
                try:
                    summary = PARSERS[agent](path).result(source)
                except OSError:
                    continue
                if not summary['requests'] and not summary['prompts']:
                    continue  # Nothing happened in it (an opened and closed chat).
                conversations[key] = summary
                changed += 1
        write_json(store, {'version': VERSION, 'conversations': conversations}, private=True)
    return changed, len(conversations)


def tokens(usage, cached=False):
    """Tokens a conversation processed: uncached input, cache writes and output; cache reads only when asked (they
    are billed and counted against limits at a fraction)."""
    return sum(usage.get(k, 0) for k in USAGE if cached or k != 'cache_read')


def report(store=None):
    """Descriptive groups (per agent: other agent's checkpoint delivered / AI Baton context only / none). Not a
    comparison of like with like: projects and tasks differ."""
    data = read_json(Path(store or STORE), {}) if Path(store or STORE).exists() else {}
    rows = [c for c in (data.get('conversations') or {}).values() if not c.get('review')]
    groups = {}
    for row in rows:
        baton = row.get('baton') or {}
        kind = 'other agent\'s checkpoint' if baton.get('other_checkpoint') else 'AI Baton context' \
            if baton.get('injections') else 'no AI Baton context'
        groups.setdefault((row['agent'], kind), []).append(row)
    out = []
    for (agent, kind), group in sorted(groups.items()):
        edited = [r for r in group if r.get('first_edit')]
        median = lambda values: round(statistics.median(values)) if values else None
        out.append({
            'agent': agent, 'group': kind, 'conversations': len(group), 'with_edit': len(edited),
            'median_tokens': median([tokens(r['usage']) for r in group]),
            'median_tool_calls_before_first_edit': median([r['first_edit']['tool_calls_before'] for r in edited]),
            'median_tokens_before_first_edit': median([tokens(r['first_edit']['usage_before']) for r in edited]),
            'median_injected_chars': median([r['baton']['chars'] for r in group if r['baton']['injections']]),
        })
    return {'conversations': len(rows), 'reviews_left_out': len(data.get('conversations') or {}) - len(rows), 'groups': out}
