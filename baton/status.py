"""Snapshot of one project's agent state for the CLI and the VS Code extension."""
from datetime import datetime, timezone
from pathlib import Path

import json

from .project import MARKER, agent_activity, clip, find_root, is_working, load_agents, read_json, running_reviews
from .recall import entries

DOCS = {'handoff': 'docs/AGENT_HANDOFF.md', 'status': 'docs/STATUS.md',
        'decisions': 'docs/knowledge/DECISIONS.md', 'agents': 'AGENTS.md'}


RECENT_IN_PANEL = 8


def mtime(path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def recent_work(mem, limit=None, chars=600):
    """Newest sessions first, one entry per agent session (the history has one line per reply).
    `limit` and `chars` (summary length) of None mean everything."""
    sessions = {}
    # The archive too: a long session can fill the whole hot history.
    for line in entries(mem):
        try:
            snap = json.loads(line)
        except ValueError:
            continue
        key = (snap.get('agent'), snap.get('session_id') or snap.get('saved_at'))
        entry = sessions.setdefault(key, {'agent': snap.get('agent'), 'session_id': snap.get('session_id'),
                                          'started': snap.get('saved_at'),
                                          'turns': 0, 'handoff_updated': False})
        entry.update({'saved_at': snap.get('saved_at'), 'commit': snap.get('commit'), 'branch': snap.get('branch'),
                      'client': snap.get('client') or entry.get('client'),
                      'summary': clip(snap.get('summary') or snap.get('last_reply') or '', chars)})
        entry['turns'] += 1
        entry['handoff_updated'] |= bool(snap.get('handoff_updated'))
    return sorted(sessions.values(), key=lambda e: e['saved_at'] or '', reverse=True)[:limit]


def project_recent(start):
    """Every session with full summaries, for the Recent work editor tab."""
    root = find_root(start)
    if root is None:
        raise LookupError('Project is not initialized. Run: baton init')
    return {'root': str(root), 'sessions': recent_work(root / '.agent-memory', chars=None)}


def project_status(start):
    root = find_root(start)
    if root is None:
        return {'initialized': False, 'path': str(Path(start).resolve()),
                'agents': [{**a, 'activity': None, 'checkpoint': None} for a in load_agents()],
                'hidden_agents': load_agents(hidden=True)}
    mem = root / '.agent-memory'
    recent = recent_work(mem)
    activity = read_json(mem / 'activity.json', {}) or {}
    reviews = running_reviews(mem)
    agents = []
    for agent in load_agents(root):
        snap = read_json(mem / (agent['id'] + '.json')) or {}
        agents.append({**agent,
                       # "working" only while is_working agrees (turn not ended in the transcript, not stale).
                       'activity': {**act, 'state': 'working' if is_working(act) else 'idle'}
                       if (act := agent_activity(activity.get(agent['id']))) else None,
                       'reviewing': reviews.get(agent['id']),
                       'checkpoint': ({k: snap.get(k) for k in ('saved_at', 'branch', 'commit', 'session_id')}
                                      | {'summary': clip(snap.get('summary') or snap.get('last_reply') or '', 600)})
                       if snap else None})
    last = max((a for a in agents if a['checkpoint']), default=None,
               key=lambda a: a['checkpoint']['saved_at'] or '')
    return {
        'initialized': True,
        'root': str(root),
        'name': (read_json(root / MARKER, {}) or {}).get('name', root.name),
        'agents': agents,
        'last_agent': last and last['id'],
        'docs': {key: {'path': str(root / rel), 'updated': mtime(root / rel)} for key, rel in DOCS.items()},
        'hidden_agents': load_agents(hidden=True),
        'recent': recent[:RECENT_IN_PANEL],
        'recent_total': len(recent),
    }
