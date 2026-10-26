"""`baton review`: ask another agent for a second opinion on the current changes.

The reviewer gets the diff, the goal of the change and a prompt that asks for a ranked critique; plain
"review" modes (e.g. `codex exec review`) only report high-confidence bugs and mostly say "no findings".
It runs read-only. Not a hook: this calls a model, takes a minute or two, and only runs when asked.
"""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .project import MEMORY_DIR, agent_binary, find_root, load_agents, read_json
from .recall import entries

MAX_DIFF = 200_000
MAX_CONTEXT = 3000
TIMEOUT = 900

PROMPT = """You are reviewing a teammate's change in this project (read AGENTS.md first). {source} You may read any \
file for context. Do not edit files, commit or run anything that changes state.

Goal of the change: {goal}{focus}

Give an honest critique, not a pass/fail: correctness, edge cases, performance, security, UX, test gaps and simpler \
alternatives. List at least 3 points ranked by importance, weaker ones included if the change is good. For each: \
what, why it matters, a concrete fix, and whether it is minor. Point to files and lines. End with one line: what \
you would change before merging."""


class ReviewError(Exception):
    pass


ENV_FLAG = 'BATON_REVIEW'  # Set for the reviewer: its hooks must not write shared memory (see hook.run).
MAX_OMITTED_NAMES = 20
MAX_NEW_FILES = 200  # One git process per new file: cap it, the rest is listed as omitted.
GIT_TIMEOUT = 120
COLLECT_TIMEOUT = 300  # For all git calls of one review together; each call gets what is left.
DEADLINE = []  # Monotonic deadline of the collection in progress (empty: none).
# Never run configured external diff or textconv programs while collecting: they could change state or hang.
SAFE_DIFF = ('--no-ext-diff', '--no-textconv')
# Processes running now, so a cancel (SIGTERM/SIGINT) at any stage stops them: (process, own process group?).
ACTIVE = []


def git(root, *args, ok=(0,), limit=None):
    """Git output as text; with `limit`, reading stops after that many bytes (huge diffs never load whole).
    stderr goes to a file so a chatty git cannot fill a pipe and block while stdout is being read."""
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(['git', *args], cwd=root, stdout=subprocess.PIPE, stderr=errors)
        ACTIVE.append((proc, False))
        # The deadline covers reading too: a stalled git is killed, which ends the read.
        budget = GIT_TIMEOUT if not DEADLINE else min(GIT_TIMEOUT, DEADLINE[-1] - time.monotonic())
        if budget <= 0:
            proc.kill()
            proc.wait()
            ACTIVE.remove((proc, False))
            raise ReviewError(f'collecting the changes took longer than {COLLECT_TIMEOUT} s')
        watchdog = threading.Timer(budget, proc.kill)
        watchdog.start()
        cut = False  # Set before reading: a cancel can interrupt the read, and `finally` still needs it.
        try:
            out = proc.stdout.read(limit + 1) if limit is not None else proc.stdout.read()
            cut = limit is not None and len(out) > limit
            if cut:
                proc.kill()
            proc.wait()
        finally:
            timed_out = not watchdog.is_alive() and not cut and proc.returncode is not None and proc.returncode < 0
            watchdog.cancel()
            ACTIVE.remove((proc, False))
        if timed_out:
            raise ReviewError(f'git {args[0]} took longer than {round(budget)} s' +
                              (' (the time for collecting the changes ran out)' if DEADLINE else ''))
        errors.seek(0)
        err = errors.read()
    if not cut and proc.returncode not in ok:
        raise ReviewError(f'git {args[0]} failed: {err.decode("utf-8", "replace").strip()[-300:]}')
    text = out[:limit].decode('utf-8', 'replace') if cut else out.decode('utf-8', 'replace')
    return text + ('\n[output cut here: too large to include]\n' if cut else '')


def git_root(start):
    if git(start, 'rev-parse', '--is-inside-work-tree', ok=(0, 128)).strip() != 'true':
        raise ReviewError('Review needs a git repository.')
    return Path(git(start, 'rev-parse', '--show-toplevel').strip())


def names_note(label, names):
    shown = ', '.join(names[:MAX_OMITTED_NAMES])
    more = f' and {len(names) - MAX_OMITTED_NAMES} more' if len(names) > MAX_OMITTED_NAMES else ''
    return f'{label} (read them if needed): {shown}{more}.'


def commit_patch(root, sha):
    """A commit's patch within MAX_DIFF, plus a note naming its files when the patch was cut."""
    # A merge's default combined diff hides cleanly merged changes; compare with the first parent instead.
    diff = git(root, 'show', *SAFE_DIFF, '--diff-merges=first-parent', '--stat', '--patch', sha, limit=MAX_DIFF)
    if '[output cut here' not in diff:
        return diff, ''
    names = [n for n in git(root, 'show', '--diff-merges=first-parent', '--name-only', '-z', '--format=', sha)
             .split('\0') if n.strip()]
    return diff, names_note('The commit patch was cut; files in the commit', names)


def collect_diff(root, commit=None, reviewer='codex'):
    """(diff, what it covers, notes for the reviewer). The uncommitted changes with new files, or one commit, or
    the last commit when clean. Collection stops at MAX_DIFF; left-out files are named in the notes. All git calls
    together get COLLECT_TIMEOUT."""
    DEADLINE.append(time.monotonic() + COLLECT_TIMEOUT)
    try:
        return collect(root, commit, reviewer)
    finally:
        DEADLINE.pop()


def collect(root, commit, reviewer):
    root = git_root(root)  # Same scope for the diff, the new files and the reviewer.
    if commit:
        sha = git(root, 'rev-parse', '--verify', '--quiet', commit + '^{commit}', ok=(0, 1)).strip()
        if not sha:
            raise ReviewError(f'{commit} is not a commit.')
        notes = (f'Files in the working tree may differ from that commit; read its versions with '
                 f'`git show {sha[:12]}:<path>`.' if reviewer == 'codex' else
                 'Files in the working tree may differ from that commit and you cannot run git: rely on the diff '
                 'and say when a conclusion comes from the current files.')
        diff, cut_note = commit_patch(root, sha)
        return diff, f'the commit {sha[:12]}', ' '.join(filter(None, [notes, cut_note]))
    has_head = git(root, 'rev-parse', '--verify', '--quiet', 'HEAD', ok=(0, 1)).strip() != ''
    if has_head:
        diff = git(root, 'diff', *SAFE_DIFF, 'HEAD', limit=MAX_DIFF)
    else:
        # No commit yet: the final content of tracked (staged) files against nothing, one patch per file.
        empty = git(root, 'hash-object', '-t', 'tree', '/dev/null').strip()  # SHA-1 or SHA-256, as the repo uses.
        diff = git(root, 'diff', *SAFE_DIFF, empty, limit=MAX_DIFF)
    tracked_cut = '[output cut here' in diff
    names = list(filter(None, git(root, 'ls-files', '-z', '--others', '--exclude-standard').split('\0')))
    omitted = []
    size = len(diff.encode())
    for i, name in enumerate(names):
        room = MAX_DIFF - size
        if room <= 0 or i >= MAX_NEW_FILES:
            omitted = names[i:]
            break
        part = git(root, 'diff', *SAFE_DIFF, '--no-index', '--', '/dev/null', name, ok=(0, 1), limit=room)  # 1: differs.
        diff += part
        size += len(part.encode())
    notes = []
    if tracked_cut:
        changed = git(root, 'diff', '--name-only', '-z', 'HEAD' if has_head else empty).split('\0')
        changed = [name for name in changed if name]
        notes.append(names_note('The diff of tracked files was cut; changed files', changed))
    if omitted:
        notes.append(names_note('New files not included because the diff is too large', omitted))
    notes = ' '.join(notes)
    if diff.strip():
        return diff, 'the uncommitted changes', notes
    if not has_head:
        return '', 'nothing', ''
    sha = git(root, 'rev-parse', 'HEAD').strip()
    diff, cut_note = commit_patch(root, sha)
    return diff, 'the last commit (there are no uncommitted changes)', cut_note


def binary(kind):
    return agent_binary(kind)


def stop(proc, group):
    """End a process we started. A group (the reviewer and anything it spawned) gets SIGTERM, then SIGKILL after a
    short grace period; either way it is reaped."""
    if not group:
        proc.kill()
        proc.wait()
        return
    for sig, grace in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(grace)
            os.killpg(proc.pid, 0)  # Raises once no descendant is left in the group.
        except subprocess.TimeoutExpired:
            continue
        except ProcessLookupError:
            break


def cancel(*_):
    for proc, group in list(ACTIVE):
        stop(proc, group)
    sys.exit(130)


def run(command, root, stdin):
    """Run the reviewer in its own process group so cancelling `baton review` stops it and its children too."""
    proc = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True, env={**os.environ, ENV_FLAG: '1'})
    ACTIVE.append((proc, True))
    try:
        out, err = proc.communicate(stdin, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        stop(proc, True)
        raise ReviewError(f'the reviewer took longer than {TIMEOUT // 60} minutes')
    finally:
        ACTIVE.remove((proc, True))
    return proc.returncode, out, err


def run_reviewer(kind, root, prompt, diff, notes=''):
    """The prompt stays small and fixed on the command line; the diff and notes go through stdin."""
    exe = binary(kind)
    if not exe:
        raise ReviewError(f'{kind} CLI not found')
    stdin = (f'<notes>\n{notes}\n</notes>\n' if notes else '') + f'<diff>\n{diff}\n</diff>\n'
    if kind == 'codex':
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'last.md'
            # Read-only sandbox and never ask for approval, whatever the user's config says.
            code, _, err = run([exe, 'exec', '--sandbox', 'read-only', '-c', 'approval_policy="never"',
                                '--skip-git-repo-check', '-o', str(out), prompt], root, stdin)
            text = out.read_text() if out.exists() else ''
    else:
        # --tools limits which tools exist (not just which are allowed), so user settings cannot widen it.
        code, text, err = run([exe, '-p', prompt, '--tools', 'Read,Grep,Glob', '--strict-mcp-config'], root, stdin)
    if code != 0:
        # Never pass a failed or partial run off as a review.
        raise ReviewError(f'{kind} failed (exit {code}): {(err or text).strip()[-300:]}')
    if not text.strip():
        raise ReviewError(f'{kind} returned no review: {err.strip()[-300:]}')
    return text.strip()


def session_summary(project, session):
    """The newest checkpoint of one session (history and archive)."""
    found = None
    for line in entries(project / MEMORY_DIR):
        try:
            snap = json.loads(line)
        except ValueError:
            continue
        if isinstance(snap, dict) and snap.get('session_id') == session and snap.get('summary'):
            found = snap
    return found


def author_context(project, session=None):
    """What the change is for, as the authors described it: the chosen session's last checkpoint (else the newest
    checkpoint of any agent) and the handoff's "Recently done". Nobody has to restate the goal."""
    if project is None:
        return ''
    parts = []
    chosen = session_summary(project, session) if session else None
    snaps = [chosen] if chosen else [read_json(f) or {} for f in (project / MEMORY_DIR).glob('*.json')]
    snaps = [x for x in snaps if isinstance(x, dict) and x.get('agent') and x.get('saved_at') and x.get('summary')]
    if snaps:
        last = max(snaps, key=lambda x: x['saved_at'])
        parts.append(f'Last checkpoint, {last["agent"]} at {last["saved_at"][:16]} UTC:\n{last["summary"][:MAX_CONTEXT // 2]}')
    try:
        handoff = (project / 'docs' / 'AGENT_HANDOFF.md').read_text()
    except OSError:
        handoff = ''
    match = re.search(r'^## Recently done\n(.*?)(?=^## |\Z)', handoff, re.S | re.M)
    if match and match.group(1).strip():
        parts.append('docs/AGENT_HANDOFF.md, Recently done:\n' + match.group(1).strip()[:MAX_CONTEXT // 2])
    return '\n\n'.join(parts)


def review(start, agent, goal=None, commit=None, focus=None, session=None):
    # A cancel at any stage (collecting the diff or reviewing) stops whatever is running, then exits.
    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return reviewed(start, agent, goal, commit, focus, session)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def reviewed(start, agent, goal, commit, focus, session):
    project = find_root(start)  # AI Baton context (agents, memory, handoff) only.
    agents = load_agents(project)
    reviewer = next((a for a in agents if a['id'] == agent), None)
    if not reviewer or reviewer.get('review') not in ('codex', 'claude'):
        raise ReviewError(f'{agent} cannot review; choose one of: {", ".join(a["id"] for a in agents if a.get("review"))}')
    # The repository is the one around `start`, even inside a bigger AI Baton project; the reviewer runs there too.
    root = git_root(Path(start).resolve())
    diff, what, notes = collect_diff(root, commit, reviewer['review'])
    if not diff.strip():
        raise ReviewError('Nothing to review: no changes and no commits.')
    context = author_context(project, session)
    if context:
        notes = (notes + '\n\n' if notes else '') + \
            'What the authors said about their recent work (may be incomplete or out of date):\n' + context
    source = f'The diff of {what} is in the <diff> block' + (', with notes in the <notes> block.' if notes else '.')
    prompt = PROMPT.format(
        source=source,
        goal=goal or 'not stated; take it from the authors\' notes in the <notes> block and the diff',
        focus=f'\nThe user asks you to pay special attention to: {focus}' if focus else '')
    return {'agent': agent, 'reviewed': what, 'review': run_reviewer(reviewer['review'], root, prompt, diff, notes)}
