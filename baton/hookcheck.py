"""`baton hook-status`: are an agent's memory hooks installed, and (Codex) approved?

Codex runs project and user hooks only after the user trusts them (Review hooks in the chat box, /hooks in the CLI), and asks again whenever a hook
changes. Its app-server reports that per hook (`hooks/list` -> trustStatus), so we ask it instead of guessing.
Not a hook itself: this may take a moment and is only called by the panel and the CLI.
"""
import glob
import json
import os
import select
import shutil
import subprocess
import time
from pathlib import Path

from . import init_project
from .init_project import HOOK_FILES, has_baton_hooks, is_baton_hook
from .project import find_root, load_agents, read_json, write_json

CACHE = Path.home() / '.cache' / 'ai-baton' / 'hook-trust-v2.json'  # Bump the name when the result format changes.
CODEX_EVENTS = {'sessionStart', 'userPromptSubmit', 'stop'}
TIMEOUT = 8


def codex_binary():
    found = shutil.which('codex')
    if found:
        return found
    bundled = glob.glob(str(Path.home() / '.vscode' / 'extensions' / 'openai.chatgpt-*' / 'bin' / '*' / 'codex'))
    return max(bundled, key=os.path.getmtime) if bundled else None


def codex_hooks(binary, cwd):
    """The hooks Codex would run in `cwd`, with trustStatus, from a short-lived app-server."""
    proc = subprocess.Popen([binary, 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        def send(message):
            proc.stdin.write(json.dumps({'jsonrpc': '2.0', **message}) + '\n')
            proc.stdin.flush()

        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'ai-baton', 'version': '1'}}})
        send({'method': 'initialized'})
        send({'id': 2, 'method': 'hooks/list', 'params': {'cwds': [str(cwd)]}})
        # Raw reads with our own line framing: select() cannot see data a buffered reader already holds.
        fd, pending, deadline = proc.stdout.fileno(), b'', time.time() + TIMEOUT
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            *lines, pending = (pending + chunk).split(b'\n')
            for line in filter(None, lines):
                message = json.loads(line)
                if message.get('id') == 2:
                    if 'error' in message:
                        raise RuntimeError(message['error'].get('message', 'hooks/list failed'))
                    return [h for entry in message['result']['data'] for h in entry.get('hooks', [])]
        raise TimeoutError('Codex did not answer')
    finally:
        proc.kill()


def codex_trust(root):
    binary = codex_binary()
    if not binary:
        return {'state': 'unknown', 'detail': 'Codex CLI not found'}
    files = [Path.home() / '.codex' / 'config.toml', init_project.user_home() / HOOK_FILES['codex'], root / HOOK_FILES['codex']]
    key = '|'.join([str(root), binary] + [str(f.stat().st_mtime) if f.exists() else '-' for f in files])
    cache = read_json(CACHE, {}) or {}
    if key in cache:
        return cache[key]
    try:
        hooks = [h for h in codex_hooks(binary, root) if is_baton_hook(h.get('command', ''), 'codex')]
        # Per event, the user-level copy steps aside when the project hooks that event, so only that one counts.
        project_events = {h['eventName'] for h in hooks if h.get('source') == 'project'}
        hooks = [h for h in hooks if h.get('source') == 'project' or h['eventName'] not in project_events]
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        return {'state': 'unknown', 'detail': f'Could not ask Codex: {type(error).__name__}'}
    trusted = {h['eventName'] for h in hooks if h.get('trustStatus') == 'trusted' and h.get('enabled', True)}
    sources = sorted({h.get('source', '?') for h in hooks if h.get('trustStatus') == 'trusted'})
    if not hooks:
        result = {'state': 'missing', 'detail': 'Codex does not see AI Baton hooks here'}
    elif CODEX_EVENTS <= trusted:
        result = {'state': 'ok', 'detail': 'approved (' + ', '.join(sources) + ')'}
    else:
        result = {'state': 'untrusted', 'detail': 'not approved yet: in Codex click the hooks button next to the model picker (Review hooks), then Allow all'}
    # One entry per project is enough; drop stale keys for the same root.
    cache = {k: v for k, v in cache.items() if not k.startswith(str(root) + '|')}
    cache[key] = result
    write_json(CACHE, cache, private=True)
    return result


def user_status():
    """Which agents already have AI Baton hooks in user settings (no Codex query: install check only)."""
    return {a['id']: {'state': 'ok' if has_baton_hooks(init_project.user_home(), a['hooks']) else 'missing'}
            for a in load_agents() if a.get('hooks') in HOOK_FILES}


def status(start):
    root = find_root(start)
    if root is None:
        return {}
    result = {}
    for agent in load_agents(root):
        kind = agent.get('hooks')
        if kind not in HOOK_FILES:
            continue
        where = [name for name, base in (('project', root), ('user', init_project.user_home())) if has_baton_hooks(base, kind)]
        if not where:
            result[agent['id']] = {'state': 'missing', 'detail': 'memory hooks are not installed'}
        elif kind == 'codex':
            result[agent['id']] = codex_trust(root)
        else:
            result[agent['id']] = {'state': 'ok', 'detail': 'installed (' + ', '.join(where) + ')'}
    return result
