"""Project discovery, the agent registry and small file helpers."""
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

HOME = Path(__file__).resolve().parents[1]
MARKER = '.baton.json'
MEMORY_DIR = '.agent-memory'
HISTORY = 'history.jsonl'
ARCHIVE = 'history.archive.jsonl.gz'
# Per-user additions (e.g. a new model extension) live outside the repo.
USER_AGENTS = Path.home() / '.config' / 'ai-baton' / 'agents.json'
AGENT_KEYS = ('id', 'label', 'extension', 'openCommand', 'newCommand')
AGENT_ID_RE = re.compile(r'[a-z0-9][a-z0-9-]{0,39}')
# Files in .agent-memory/ next to the checkpoints (<agent>.json): no agent may be called this.
RESERVED_IDS = {'activity', 'seen', 'reviews'}
# Integrations a user-added agent gets from AI Baton itself, never from its own entry (add_agent keeps launch settings
# only): keyed by the agent id and its extension, which must both match.
INTEGRATIONS = {('copilot', 'github.copilot-chat'): {'hooks': 'copilot'}}


class AgentError(Exception):
    pass


def baton_command():
    """The command hooks run. The script is the stable launcher when installed (~/.ai-baton/bin/baton), else this
    checkout's bin/baton. The interpreter is `python3` when that is the one running now (a stable, short command), else
    the full path of the running one, so hooks use the same Python the extension checked."""
    script = os.environ.get('BATON_LAUNCHER') or str(HOME / 'bin' / 'baton')
    if os.name == 'nt':
        # Codex runs hook commands in the session's shell, PowerShell on Windows (cmd.exe when none is found). A quoted
        # program is only a string to PowerShell, so the interpreter goes unquoted (its short 8.3 name if the path has
        # spaces), which both shells run; the script path is a quoted argument. Forward slashes: no escapes anywhere.
        python, script = hook_argv()
        python = Path(short_path(python)).as_posix()
        if ' ' in python:  # Short names are turned off on this disk: PowerShell's call operator.
            return f'& "{python}" "{Path(script).as_posix()}"'
        return f'{python} "{Path(script).as_posix()}"'
    found = shutil.which('python3')
    same = found and os.path.realpath(found) == os.path.realpath(sys.executable)
    # Ordinary paths keep the "..." form (changing a hook command makes Codex ask for trust again); a path with
    # characters a shell would expand inside double quotes is quoted strictly.
    quoted = shlex.quote(script) if any(c in script for c in '$`"\\') else f'"{script}"'
    return f'{"python3" if same else shlex.quote(sys.executable)} {quoted}'


def short_path(path):
    """Windows: the 8.3 form of an existing path (no spaces), or the path itself."""
    if os.name != 'nt' or ' ' not in str(path):
        return str(path)
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
        return buffer.value if 0 < length < len(buffer) else str(path)
    except (OSError, AttributeError):
        return str(path)


def hook_argv():
    """[interpreter, launcher script] of the hook command, absolute (Windows hooks run them without a shell)."""
    return [sys.executable, os.environ.get('BATON_LAUNCHER') or str(HOME / 'bin' / 'baton')]


def agent_binary(kind):
    """The agent's own program if it is on this computer (PATH, or bundled in its VS Code extension), else None."""
    found = shutil.which(kind)
    if found:
        return found
    patterns = {'codex': '~/.vscode/extensions/openai.chatgpt-*/bin/*/codex',
                'claude': '~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude'}
    exe = '.exe' if os.name == 'nt' else ''
    candidates = glob.glob(os.path.expanduser(patterns.get(kind, '') + exe)) if kind in patterns else []
    return max(candidates, key=os.path.getmtime) if candidates else None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_root(start):
    """Nearest folder at or above `start` that was set up with `baton init`."""
    path = Path(start).expanduser().resolve()
    for candidate in (path, *path.parents):
        if (candidate / MARKER).is_file():
            return candidate
    return None


def builtin_agents():
    return json.loads((HOME / 'baton' / 'agents.json').read_text(encoding='utf-8'))


def load_agents(root=None, hidden=False):
    """Built-in agents minus the ones the user hid, then user and project additions.
    With hidden=True, return only the hidden built-ins (so the panel can offer them back)."""
    registry = user_registry()
    builtins = builtin_agents()
    if hidden:
        return [a for a in builtins if a['id'] in registry['hidden']]
    agents = [a for a in builtins if a['id'] not in registry['hidden']]
    project = read_json(Path(root) / MARKER, {}) if root else {}
    project = project.get('extraAgents', []) if isinstance(project, dict) else project
    for source, more in (('user', registry['agents']), ('project', project or [])):
        known = {a['id'] for a in builtins + agents}
        agents += [{**a, 'source': source} for a in more if a.get('id') not in known]
    return [with_integration(a) for a in agents]


def with_integration(agent):
    if agent.get('source') != 'user':
        return agent
    found = INTEGRATIONS.get((agent.get('id'), str(agent.get('extension') or '').lower()))
    return {**agent, **found} if found else agent


def user_registry():
    """The per-user file: {"agents": [...], "hidden": [...]}; a bare list (older format) means agents only."""
    if not USER_AGENTS.exists():
        return {'agents': [], 'hidden': []}
    data = read_json(USER_AGENTS)
    if isinstance(data, list):
        data = {'agents': data}
    if not isinstance(data, dict):
        raise AgentError(f'{USER_AGENTS} is not valid JSON')
    return {'agents': list(data.get('agents') or data.get('extraAgents') or []), 'hidden': list(data.get('hidden') or [])}


def add_agent(agent):
    """Show a hidden built-in agent again, or add or replace a user agent (plain launch settings only)."""
    registry = user_registry()
    builtin = next((a for a in builtin_agents() if a['id'] == agent.get('id')), None)
    if builtin:
        registry['hidden'] = [h for h in registry['hidden'] if h != builtin['id']]
        write_json(USER_AGENTS, registry)
        return builtin
    agent = {k: agent[k].strip() for k in AGENT_KEYS if isinstance(agent.get(k), str) and agent[k].strip()}
    if not valid_agent_id(agent.get('id', '')):
        raise AgentError('id must be lowercase letters, digits and dashes (not activity or seen)')
    if 'label' not in agent or 'openCommand' not in agent:
        raise AgentError('label and openCommand are required')
    registry['agents'] = [a for a in registry['agents'] if a.get('id') != agent['id']] + [agent]
    write_json(USER_AGENTS, registry)
    return agent


def valid_agent_id(agent_id):
    return isinstance(agent_id, str) and bool(AGENT_ID_RE.fullmatch(agent_id)) and agent_id not in RESERVED_IDS


def remove_agent(agent_id):
    """Delete a user agent, or hide a built-in one (its integration stays and can be shown again)."""
    registry = user_registry()
    if agent_id in {a['id'] for a in builtin_agents()}:
        if agent_id not in registry['hidden']:
            registry['hidden'].append(agent_id)
    else:
        kept = [a for a in registry['agents'] if a.get('id') != agent_id]
        if len(kept) == len(registry['agents']):
            raise AgentError(f'{agent_id} is not a known agent')
        registry['agents'] = kept
    write_json(USER_AGENTS, registry)


WORKING_STALE = timedelta(minutes=45)
TAIL_BYTES = 65536


def aware(value):
    """A timezone-aware datetime from an ISO string (naive means UTC), or None."""
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def turn_finished_after(transcript, since):
    """True if the transcript records a turn ending (Codex: task_complete or turn_aborted) after `since`.
    Codex writes these even when no Stop hook runs (`codex exec review`); Claude transcripts have none."""
    if not os.path.isfile(transcript):  # Regular files only: a FIFO could block the hook.
        return False
    with open(transcript, 'rb') as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - TAIL_BYTES))
        tail = stream.read().decode('utf-8', 'replace').splitlines()
    for line in reversed(tail):
        if '"event_msg"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get('type') != 'event_msg':
            continue
        payload = record.get('payload')
        kind = payload.get('type') if isinstance(payload, dict) else None
        if kind == 'task_started':
            return False
        if kind in ('task_complete', 'turn_aborted'):
            ended = aware(record.get('timestamp'))
            return bool(ended and ended > since)  # A marker from an earlier turn says nothing about this one.
    return False


def is_working(entry):
    """Marked working, not ended according to the transcript, and not older than WORKING_STALE."""
    if not isinstance(entry, dict) or entry.get('state') != 'working':
        return False
    at = aware(entry.get('at'))
    if at is None or datetime.now(timezone.utc) - at >= WORKING_STALE:
        return False
    transcript = entry.get('transcript')
    if isinstance(transcript, str) and transcript:
        try:
            return not turn_finished_after(transcript, at)
        except OSError:
            pass
    return True


def agent_sessions(entry):
    """An agent's activity per conversation. Files from before sessions were tracked hold one entry per agent: that
    entry is its only session."""
    if not isinstance(entry, dict):
        return {}
    sessions = entry.get('sessions')
    if isinstance(sessions, dict):
        return {str(k): v for k, v in sessions.items() if isinstance(v, dict)}
    return {str(entry.get('session_id') or ''): entry}


def moment(entry):
    """When an activity entry was recorded, for ordering; unreadable times sort first."""
    return aware(entry.get('at')) or datetime.min.replace(tzinfo=timezone.utc)


def marked_working(entry):
    """Recorded as working and not stale, without reading the transcript (cheap enough to run under a lock)."""
    at = aware(entry.get('at'))
    return entry.get('state') == 'working' and at is not None and datetime.now(timezone.utc) - at < WORKING_STALE


def agent_activity(entry, working=is_working):
    """The agent-level view of its sessions: the newest working one if any (the agent is busy), else the newest."""
    ranked = sorted(agent_sessions(entry).values(), key=lambda e: (working(e), moment(e)), reverse=True)
    return dict(ranked[0]) if ranked else None


def clip(text, chars):
    """At most `chars` characters, cut at a word boundary with an ellipsis; None means no limit."""
    if chars is None or len(text) <= chars:
        return text
    cut = text[:chars - 1]
    if not cut[-1:].isspace() and not text[chars - 1].isspace() and ' ' in cut.strip():
        cut = cut.rsplit(None, 1)[0]  # Drop the word that was cut in half.
    return cut.rstrip(' ,;:.') + '…'


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def kill_tree(proc, timeout=5):
    """End a Windows process and everything it started (a .cmd wrapper's child too), bounded by `timeout` seconds,
    then reap it. Falls back to killing only `proc` when taskkill fails or hangs."""
    try:
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout)


@contextmanager
def file_lock(path, timeout=3):
    """Hold an exclusive lock on `path` (created if missing) across processes. Gives up with TimeoutError after
    `timeout` seconds, so a stuck writer cannot hold a hook past its time limit."""
    with open(path, 'a+b') as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if fcntl:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)  # Byte 0, also when the file is empty.
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f'{path} is locked')
                time.sleep(0.05)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(stream, fcntl.LOCK_UN)
            else:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def write_json(path, data, private=False):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n', private)


def write_text(path, text, private=False):
    """Atomic write so a reader never sees half a file; an existing file keeps its mode and symlink."""
    path = Path(path)
    if path.is_symlink():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        elif not private:
            os.chmod(temp, 0o644)
        # Windows refuses to replace a file another process has open (a reader, an antivirus scan) for a moment.
        for attempt in range(20):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def memory_dir(root):
    path = Path(root) / MEMORY_DIR
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


# Reviews running now (`baton review`): .agent-memory/reviews.json, {token: {agent, model, effort, started, pid}}.
# Only for the panel's "reviewing" badge: a review is not project work, so it never touches checkpoints or activity.
REVIEWS = 'reviews.json'
MAX_REVIEW_HOURS = 2  # An entry older than this is a review that died without cleaning up.


def process_alive(pid):
    """Whether process `pid` still runs; never signals it (os.kill(pid, 0) would end it on Windows)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid < 2 ** 31:
        return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.GetLastError() == 5  # Access denied: it exists, owned by someone else.
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # EPERM: it exists, owned by someone else.
    return True


def review_entry(entry):
    """(started, entry) for a review that is still running, else None. Damaged entries count as not running."""
    if not isinstance(entry, dict) or not isinstance(entry.get('agent'), str):
        return None
    started = aware(entry.get('started'))
    if started is None or datetime.now(timezone.utc) - started > timedelta(hours=MAX_REVIEW_HOURS):
        return None
    return (started, entry) if process_alive(entry.get('pid')) else None


def update_reviews(root, change):
    """Apply `change` to the running reviews under the lock, dropping finished or damaged ones. Best effort: the
    badge is optional, so a failure here (permissions, a busy lock, a symlink planted as reviews.json) never stops
    or spoils a review."""
    try:
        mem = memory_dir(root)
        path = mem / REVIEWS
        if path.is_symlink():
            return
        with file_lock(mem / '.reviews.lock'):
            running = read_json(path, {}) or {}
            running = {k: v for k, v in running.items() if review_entry(v)} if isinstance(running, dict) else {}
            change(running)
            write_json(path, running, private=True)
    except (OSError, TimeoutError, ValueError):
        pass


def start_review(root, agent, model='', effort=''):
    """Mark a review as running; returns the token for end_review."""
    token = f'{os.getpid()}-{time.time_ns()}'
    entry = {'agent': agent, 'model': model or '', 'effort': effort or '', 'started': now_iso(), 'pid': os.getpid()}
    update_reviews(root, lambda running: running.__setitem__(token, entry))
    return token


def end_review(root, token):
    update_reviews(root, lambda running: running.pop(token, None))


def running_reviews(mem):
    """{agent: the newest running review}: read only, for the panel."""
    path = Path(mem) / REVIEWS
    running = {} if path.is_symlink() else read_json(path, {}) or {}
    found = {}
    for value in (running.values() if isinstance(running, dict) else []):
        live = review_entry(value)
        if live and (value['agent'] not in found or live[0] > found[value['agent']][0]):
            found[value['agent']] = live
    return {agent: {k: entry.get(k) for k in ('model', 'effort', 'started')} for agent, (_, entry) in found.items()}
