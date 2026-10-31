"""Token usage read from the agents' own local logs; nothing is sent anywhere.

Claude Code: ~/.claude/projects/**/*.jsonl  (per-message `usage`, deduplicated by message id)
Codex:       ~/.codex/sessions/**/rollout-*.jsonl  (`token_count` events + plan rate limits)

Files are append-only, so the cache keeps a byte offset per file and parses only new lines.
Each file also keeps its conversation's context size (input of its last request) and title: numbers and the title the
agent shows for the chat, never message text. Codex keeps its titles in ~/.codex/session_index.jsonl.
"""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .project import find_root, read_json, write_json

CACHE = Path.home() / '.cache' / 'ai-baton' / 'usage-v3.json'  # v3: context sizes, titles (needs a full re-parse).
SOURCES = {
    'claude': (Path.home() / '.claude' / 'projects', '*.jsonl'),
    'codex': (Path.home() / '.codex' / 'sessions', 'rollout-*.jsonl'),
}
CLAUDE_CONFIG = Path.home() / '.claude.json'
CODEX_TITLES = Path.home() / '.codex' / 'session_index.jsonl'
MAX_TITLE = 120
TITLE_KINDS = ('custom-title', 'ai-title')  # Claude's records; one the user gave wins.
CODEX_KEYS = (b'"token_count"', b'"turn_context"', b'"session_meta"', b'"compacted"')
FIELDS = ('input', 'cache_read', 'cache_write', 'output')
CONTEXT_HOURS = 24  # Conversations whose last request is older are not shown in the context list.
# Claude logs no window size: known model ids only (a dated id like claude-sonnet-4-5-20250929 counts too). Any
# other model gets no window, so no warning: a guess for a new model could be far off.
CLAUDE_WINDOWS = {
    **dict.fromkeys(('claude-fable-5-1', 'claude-fable-5', 'claude-mythos-5-1', 'claude-mythos-5', 'claude-opus-5-5',
                     'claude-opus-5', 'claude-opus-4-8', 'claude-opus-4-7', 'claude-opus-4-6', 'claude-sonnet-5-5',
                     'claude-sonnet-5', 'claude-sonnet-4-6', 'claude-haiku-5-5'), 1_000_000),
    **dict.fromkeys(('claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-5', 'claude-opus-4-1', 'claude-opus-4',
                     'claude-sonnet-4'), 200_000),
}
DATED = re.compile(r'^(.*?)(?:-\d{8})?$')
# A Codex compaction record holds the whole kept history; only its time is needed, read without decoding it.
CODEX_COMPACTED = re.compile(rb'^\{"timestamp":"([^"]+)",(?:"ordinal":\d+,)?"type":"compacted"')


def local_day(timestamp):
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone().date().isoformat()
    except (AttributeError, ValueError):
        return None


def new_lines(path, entry):
    """Complete lines appended since the last parse, advancing the stored offset."""
    with open(path, 'rb') as stream:
        stream.seek(entry['offset'])
        data = stream.read()
    end = data.rfind(b'\n') + 1
    entry['offset'] += end
    return data[:end].splitlines()


def parse_claude(lines, entry):
    messages = entry.setdefault('messages', {})
    for line in lines:
        boundary = b'"compact_boundary"' in line
        titled = b'"ai-title"' in line or b'"custom-title"' in line
        if b'"usage"' not in line and not boundary and not titled:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if boundary and record.get('subtype') == 'compact_boundary':
            compacted(entry, record)
            continue
        if record.get('type') in ('ai-title', 'custom-title'):
            # The chat's name in Claude's own list; one the user gave (custom) wins over the generated one.
            title = record.get('customTitle') if record['type'] == 'custom-title' else record.get('aiTitle')
            if isinstance(title, str) and title.strip():
                entry.setdefault('context', {'compactions': 0})[record['type']] = title.strip()[:MAX_TITLE]
            continue
        message = record.get('message') or {}
        usage = message.get('usage')
        model = message.get('model')
        day = local_day(record.get('timestamp'))
        if not isinstance(usage, dict) or not day or not model or model.startswith('<'):
            continue
        key = message.get('id') or record.get('uuid')
        # One message is logged once per content block with the same usage; keep the last.
        messages[key] = [day, record.get('cwd') or '', model,
                         usage.get('input_tokens') or 0,
                         usage.get('cache_read_input_tokens') or 0,
                         usage.get('cache_creation_input_tokens') or 0,
                         usage.get('output_tokens') or 0]
        if not record.get('isSidechain'):  # A subagent's own requests are not this conversation's context.
            requested(entry, record, model, sum(messages[key][3:6]), session=record.get('sessionId'),
                      cwd=record.get('cwd'), unattended=str(record.get('entrypoint') or '').startswith('sdk'))


def requested(entry, record, model, tokens, window=None, **facts):
    """The conversation's latest request: its input is what the model read, i.e. the current context size."""
    context = entry.setdefault('context', {'compactions': 0})
    at = record.get('timestamp') or ''
    if at < context.get('at', ''):
        return
    context.update({k: v for k, v in facts.items() if v not in (None, '')}, model=model, tokens=tokens, window=window,
                   at=at)
    if context.get('compacted_at', '') <= at:
        context.pop('compacted_at', None)


def compacted(entry, record):
    """The context was replaced by a summary: the last size is out of date until the next request reports."""
    context = entry.setdefault('context', {'compactions': 0})
    context['compactions'] += 1
    context['compacted_at'] = record.get('timestamp') or context.get('at', '')


def parse_codex(lines, entry):
    state = entry.setdefault('state', {'cwd': '', 'model': '', 'total': None})
    rows = entry.setdefault('rows', {})
    for line in lines:
        if not any(key in line for key in CODEX_KEYS):
            continue
        fast = CODEX_COMPACTED.match(line)
        if fast:
            compacted(entry, {'timestamp': fast.group(1).decode('utf-8', 'replace')})
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        payload = record.get('payload') or {}
        if record.get('type') in ('session_meta', 'turn_context'):
            state['cwd'] = payload.get('cwd') or state['cwd']
            state['model'] = payload.get('model') or state['model']
            if record.get('type') == 'session_meta' and payload.get('id'):
                state['session'] = payload['id']
                # `codex exec` (also AI Baton's reviews) and subagent threads: nobody can /clear or /compact them.
                state['unattended'] = payload.get('source') == 'exec' or isinstance(payload.get('source'), dict)
            continue
        if record.get('type') == 'compacted':
            compacted(entry, record)
            continue
        if payload.get('type') != 'token_count':
            continue
        if payload.get('rate_limits'):
            entry['limits'] = {'at': record.get('timestamp'), **payload['rate_limits']}
        info = payload.get('info') or {}
        total, last = info.get('total_token_usage'), info.get('last_token_usage')
        day = local_day(record.get('timestamp'))
        if not total or not day:
            continue
        previous = state['total']
        if previous and total.get('total_tokens', 0) == previous.get('total_tokens', 0):
            continue  # Repeated event, nothing new was spent.
        if previous and total.get('total_tokens', 0) > previous.get('total_tokens', 0):
            delta = {k: total.get(k, 0) - previous.get(k, 0) for k in total}
        else:
            delta = last or total  # First event, or the counter restarted.
        state['total'] = total
        # Only a new request (its total moved): a repeated event must not undo a compaction that followed it.
        if isinstance(last, dict) and last.get('input_tokens'):
            requested(entry, record, state['model'] or 'codex', last['input_tokens'],
                      window=info.get('model_context_window'), session=state.get('session'), cwd=state['cwd'],
                      unattended=bool(state.get('unattended')))
        cached = delta.get('cached_input_tokens', 0)
        row = rows.setdefault('\t'.join((day, state['cwd'], state['model'] or 'codex')), [0, 0, 0, 0])
        for i, value in enumerate((delta.get('input_tokens', 0) - cached, cached,
                                   delta.get('cache_write_input_tokens', 0), delta.get('output_tokens', 0))):
            row[i] += max(value, 0)


def refresh_cache():
    cache = read_json(CACHE, {}) or {}
    files = cache.setdefault('files', {})
    seen = set()
    for agent, (base, pattern) in SOURCES.items():
        if not base.is_dir():
            continue
        for path in base.rglob(pattern):
            key = str(path)
            seen.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue
            entry = files.get(key)
            if entry and entry['mtime'] == stat.st_mtime and entry['size'] == stat.st_size:
                continue
            if not entry or stat.st_size < entry['offset']:
                entry = {'agent': agent, 'offset': 0}  # New or rewritten file.
            try:
                lines = new_lines(path, entry)
            except OSError:
                continue
            (parse_claude if agent == 'claude' else parse_codex)(lines, entry)
            entry.update(mtime=stat.st_mtime, size=stat.st_size)
            files[key] = entry
    for key in set(files) - seen:
        files[key]['gone'] = True  # Keep history of rotated/archived logs.
        # But not a deleted chat's title: no name outlives its transcript here (the numbers stay).
        for kind in TITLE_KINDS:
            (files[key].get('context') or {}).pop(kind, None)
    write_json(CACHE, cache, private=True)
    return cache


def iter_rows(cache):
    """Yield (agent, day, cwd, model, input, cache_read, cache_write, output)."""
    claude = {}
    for entry in cache['files'].values():
        if entry['agent'] == 'claude':
            claude.update(entry.get('messages', {}))
        else:
            for key, values in entry.get('rows', {}).items():
                yield ('codex', *key.split('\t'), *values)
    for values in claude.values():  # Resumed sessions copy messages; ids dedupe them.
        yield ('claude', *values)


def latest_limits(cache):
    best = {}
    for entry in cache['files'].values():
        limits = entry.get('limits')
        if limits and limits.get('at', '') > best.get(limits.get('limit_id'), {}).get('at', ''):
            best[limits.get('limit_id')] = limits
    now = datetime.now(timezone.utc).timestamp()
    for limits in best.values():
        for window in ('primary', 'secondary'):
            info = limits.get(window)
            if info and info.get('resets_at') and info['resets_at'] < now:
                info['expired'] = True  # Window has reset since the last Codex turn.
    return best


def claude_limits():
    """Plan limits the Claude Code extension caches in ~/.claude.json after it polls them."""
    cached = (read_json(CLAUDE_CONFIG, {}) or {}).get('cachedUsageUtilization') or {}
    usage = cached.get('utilization') or {}
    fetched = cached.get('fetchedAtMs')
    now = datetime.now(timezone.utc).timestamp()
    limits = {'limit_id': 'claude', 'plan_type': None,
              'at': fetched and datetime.fromtimestamp(fetched / 1000, timezone.utc).isoformat()}
    for window, key, minutes in (('primary', 'five_hour', 300), ('secondary', 'seven_day', 10080)):
        info = usage.get(key)
        if not info or info.get('utilization') is None:
            continue
        try:
            resets = datetime.fromisoformat(info['resets_at']).timestamp()
        except (TypeError, ValueError):
            resets = None
        limits[window] = {'used_percent': info['utilization'], 'window_minutes': minutes, 'resets_at': resets,
                          'expired': bool(resets and resets < now)}
    return {'claude': limits} if 'primary' in limits or 'secondary' in limits else {}


def claude_window(model):
    return CLAUDE_WINDOWS.get(DATED.match(model or '').group(1))


def codex_titles():
    """Codex chat titles by conversation id; the file is small and rewritten by Codex, so it is read each time.
    Anything damaged is skipped: a title is never worth losing the rest of the report."""
    titles = {}
    try:
        with open(CODEX_TITLES, encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                session, name = record.get('id'), record.get('thread_name')
                if isinstance(session, str) and session and isinstance(name, str) and name.strip():
                    titles[session] = name.strip()[:MAX_TITLE]  # Later lines are renames.
    except OSError:
        pass
    return titles


def chat_titles(cache):
    """Every conversation's title and folder by its id, resolved once per report so all views agree. Claude: a title
    the user gave beats a generated one; between copies of a resumed conversation, the one with the latest event."""
    best = {}
    for entry in cache['files'].values():
        context = entry.get('context') or {}
        session = context.get('session')
        if not session or entry.get('gone') or entry['agent'] != 'claude':
            continue
        kind = next((k for k in TITLE_KINDS if context.get(k)), None)
        if kind:
            rank = (kind == 'custom-title', max(context.get('at', ''), context.get('compacted_at') or ''))
            if session not in best or best[session][0] < rank:
                best[session] = (rank, context[kind], context.get('cwd'))
    found = {session: (title, cwd) for session, (_, title, cwd) in best.items()}
    index = codex_titles()
    for entry in cache['files'].values():
        context = entry.get('context') or {}
        session = context.get('session')
        if entry['agent'] == 'codex' and session in index and not entry.get('gone'):
            found[session] = (index[session], context.get('cwd'))
    return found


def contexts(cache, inside=None, hours=CONTEXT_HOURS, titles=None):
    """Context size of each conversation a person runs (no reviews, `claude -p`, `codex exec` or subagents) with a
    request in the last `hours`, newest first. `inside`: a filter on the conversation's folder. A window is only
    given when known and not exceeded (an id the table gets wrong)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    found = {}
    for path, entry in cache['files'].items():
        context = entry.get('context')
        # Claude keeps subagent transcripts in <session>/subagents/: those are not conversations of their own.
        if not context or not context.get('at') or entry.get('gone') or 'subagents' in Path(path).parts:
            continue
        try:
            at = datetime.fromisoformat(context['at'].replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
            last = max(context['at'], context.get('compacted_at') or '')  # Its latest event: a request or compaction.
            last = datetime.fromisoformat(last.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
        # A resumed conversation can be logged in two files, the newer one copying the older's records: the file with
        # the latest event wins, and its counts stand alone (adding them would count copied compactions twice). Only
        # then the filters: an older copy must not stand in for a newest one that is filtered out.
        key = (entry['agent'], context.get('session') or path)
        if key not in found or found[key][0] < last:
            found[key] = (last, at, entry['agent'], context)
    titles = chat_titles(cache) if titles is None else titles
    shown = []
    for last, at, agent, context in found.values():
        if context.get('unattended') or last < since or (inside and not inside(context.get('cwd'))):
            continue
        window = context.get('window') or (claude_window(context.get('model')) if agent == 'claude' else None)
        if window and context['tokens'] > window:
            window = None
        title = titles.get(context.get('session'), (None, None))[0]
        shown.append({'agent': agent, 'session': context.get('session'), 'title': title, 'cwd': context.get('cwd') or '',
                      'model': context.get('model'), 'tokens': context['tokens'], 'window': window, 'at': at,
                      'compactions': context.get('compactions', 0), 'compacted': 'compacted_at' in context,
                      'last': last})
    return sorted(shown, key=lambda item: item['last'], reverse=True)


def empty():
    return dict.fromkeys(FIELDS, 0)


def add(totals, values):
    for field, value in zip(FIELDS, values):
        totals[field] += value


def project_label(cwd, roots):
    if cwd not in roots:
        root = find_root(cwd) if cwd and os.path.isdir(cwd) else None
        roots[cwd] = str(root or cwd)
    return roots[cwd]


def summarize(days=30, project=None):
    cache = refresh_cache()
    today = date.today()
    start = (today - timedelta(days=days - 1)).isoformat()
    week = (today - timedelta(days=6)).isoformat()
    project = str(Path(project).resolve()) if project else None
    # Agents log the folder as they saw it: on Windows the drive letter's case and the slashes can differ.
    same = lambda path: os.path.normcase(os.path.normpath(path)) if path else ''
    inside = same(project)
    within = lambda cwd: not project or same(cwd) == inside or same(cwd).startswith(inside.rstrip(os.sep) + os.sep)
    roots, report = {}, {}
    titles = chat_titles(cache)
    for agent, day, cwd, model, *values in iter_rows(cache):
        if day < start:
            continue
        if not within(cwd):
            continue
        data = report.setdefault(agent, {'today': empty(), 'week': empty(), 'period': empty(),
                                         'by_day': {}, 'by_project': {}, 'by_model': {}})
        add(data['period'], values)
        if day >= week:
            add(data['week'], values)
        if day == today.isoformat():
            add(data['today'], values)
        add(data['by_day'].setdefault(day, empty()), values)
        add(data['by_project'].setdefault(project_label(cwd, roots), empty()), values)
        add(data['by_model'].setdefault(model, empty()), values)
    for data in report.values():
        data['by_day'] = [{'day': d, **t} for d, t in sorted(data['by_day'].items())]
        for group in ('by_project', 'by_model'):
            data[group] = sorted(({'name': n, **t} for n, t in data[group].items()),
                                 key=lambda t: -(t['input'] + t['cache_write'] + t['output']))
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'days': days, 'project': project,
            'agents': report, 'limits': {'claude': claude_limits(), 'codex': latest_limits(cache)},
            'contexts': contexts(cache, within, titles=titles),
            'titles': {session: title for session, (title, cwd) in titles.items() if within(cwd)}}
