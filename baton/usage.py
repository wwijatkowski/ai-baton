"""Token usage read from the agents' own local logs; nothing is sent anywhere.

Claude Code: ~/.claude/projects/**/*.jsonl  (per-message `usage`, deduplicated by message id)
Codex:       ~/.codex/sessions/**/rollout-*.jsonl  (`token_count` events + plan rate limits)

Files are append-only, so the cache keeps a byte offset per file and parses only new lines.
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .project import find_root, read_json, write_json

CACHE = Path.home() / '.cache' / 'ai-baton' / 'usage-v1.json'
SOURCES = {
    'claude': (Path.home() / '.claude' / 'projects', '*.jsonl'),
    'codex': (Path.home() / '.codex' / 'sessions', 'rollout-*.jsonl'),
}
CLAUDE_CONFIG = Path.home() / '.claude.json'
CODEX_KEYS = (b'"token_count"', b'"turn_context"', b'"session_meta"')
FIELDS = ('input', 'cache_read', 'cache_write', 'output')


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
        if b'"usage"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
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


def parse_codex(lines, entry):
    state = entry.setdefault('state', {'cwd': '', 'model': '', 'total': None})
    rows = entry.setdefault('rows', {})
    for line in lines:
        if not any(key in line for key in CODEX_KEYS):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get('payload') or {}
        if record.get('type') in ('session_meta', 'turn_context'):
            state['cwd'] = payload.get('cwd') or state['cwd']
            state['model'] = payload.get('model') or state['model']
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
    roots, report = {}, {}
    for agent, day, cwd, model, *values in iter_rows(cache):
        if day < start:
            continue
        if project and same(cwd) != inside and not same(cwd).startswith(inside.rstrip(os.sep) + os.sep):
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
            'agents': report, 'limits': {'claude': claude_limits(), 'codex': latest_limits(cache)}}
