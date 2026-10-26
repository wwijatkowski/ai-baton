"""`baton recall`: search every saved checkpoint, newest first (the cold memory tier)."""
import json
import zlib

from .project import ARCHIVE, HISTORY, MEMORY_DIR, find_root

SNIPPET = 220


def archive_lines(path):
    """Lines of the gzip archive, one member at a time. A damaged member (e.g. from two writers before the history
    lock existed) is skipped by jumping to the next gzip header, so one bad spot never hides the rest."""
    data = path.read_bytes()
    pos = 0
    while pos < len(data):
        reader = zlib.decompressobj(31)
        try:
            text = reader.decompress(data[pos:])
            if not reader.eof:
                raise zlib.error('truncated member')
        except zlib.error:
            following = data.find(b'\x1f\x8b\x08', pos + 1)
            if following == -1:
                return
            pos = following
            continue
        yield from text.decode('utf-8', 'replace').splitlines()
        pos = len(data) - len(reader.unused_data)


def entries(mem):
    archive, history = mem / ARCHIVE, mem / HISTORY
    if archive.exists():
        yield from archive_lines(archive)
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
