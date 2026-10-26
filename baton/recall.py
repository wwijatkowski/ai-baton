"""`baton recall`: search every saved checkpoint, newest first (the cold memory tier)."""
import gzip
import json

from .project import ARCHIVE, HISTORY, MEMORY_DIR, find_root

SNIPPET = 220


def entries(mem):
    archive, history = mem / ARCHIVE, mem / HISTORY
    if archive.exists():
        with gzip.open(archive, 'rt') as stream:
            yield from stream
    if history.exists():
        yield from history.read_text().splitlines()


def searchable(snap):
    found = snap.get('changes') or {}
    return '\n'.join([snap.get('last_reply') or '', *(found.get('changed') or []), snap.get('changed_files') or ''])


def search(start, words=(), agent=None, limit=5):
    root = find_root(start)
    if root is None:
        raise LookupError('Project is not initialized. Run: baton init')
    words = [w.lower() for w in words]
    hits = []
    for line in entries(root / MEMORY_DIR):
        try:
            snap = json.loads(line)
        except ValueError:
            continue
        text = searchable(snap).lower()
        if (not agent or snap.get('agent') == agent) and all(w in text for w in words):
            hits.append(snap)
    return hits[::-1][:limit]


def snippets(text, words):
    low, spans = text.lower(), []
    for word in words:
        at = low.find(word.lower())
        if at != -1 and not any(start <= at < end for start, end in spans):
            spans.append((max(0, at - SNIPPET // 2), at + SNIPPET // 2))
    return ['…' + ' '.join(text[start:end].split()) + '…' for start, end in sorted(spans)]


def render(snap, words, full):
    found = snap.get('changes') or {}
    where = found.get('commit') or snap.get('commit') or ''
    head = f'[{snap.get("agent")}] {snap.get("saved_at", "")[:16].replace("T", " ")} UTC'
    head += f' · {found.get("kind", "git")} {where}' if where else ''
    if full:
        body = searchable(snap).strip()
    elif words:
        body = '\n'.join(snippets(searchable(snap), words))
    else:
        body = snap.get('summary') or ' '.join((snap.get('last_reply') or '').split())[:600]
    return f'{head}\n{body}'
