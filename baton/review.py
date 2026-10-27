"""`baton review`: ask another agent (or the same one with another model or effort) for a second opinion.

The reviewer gets the diff, the goal of the change and a prompt that asks for a ranked critique; plain
"review" modes (e.g. `codex exec review`) only report high-confidence bugs and mostly say "no findings".
It runs read-only. Not a hook: this calls a model, takes a minute or two, and only runs when asked.

What is reviewed, by what the project has (see changes.py for how checkpoints record changes):
git      -> the uncommitted changes; else the commits since the chosen conversation began; else the last commit
shadow   -> no repository: AI Baton's private snapshots against the files now
files    -> no git at all: the files the conversation changed, listed for the reviewer to read
replies  -> no file changes: the agent's replies in the conversation (a plan, an answer, work outside the project)
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import changes, models
from .changes import BASELINE_REF, SHADOW_CONFIG, SHADOW_DIR
from .project import MEMORY_DIR, agent_binary, end_review, find_root, kill_tree, load_agents, read_json, start_review, \
    write_text
from .recall import entries

MAX_DIFF = 200_000
MAX_CONTEXT = 3000
MAX_REPLIES = 40_000  # Replies reviewed when no files changed, newest kept.
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


def git(root, *args, ok=(0,), limit=None, prefix=()):
    """Git output as text; with `limit`, reading stops after that many bytes (huge diffs never load whole).
    stderr goes to a file so a chatty git cannot fill a pipe and block while stdout is being read.
    `prefix` goes before the command (e.g. a --git-dir)."""
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(['git', *prefix, *args], cwd=root, stdout=subprocess.PIPE, stderr=errors)
        ACTIVE.append((proc, False))
        # The deadline covers reading too: a stalled git is killed, which ends the read.
        budget = GIT_TIMEOUT if not DEADLINE else min(GIT_TIMEOUT, DEADLINE[-1] - time.monotonic())
        if budget <= 0:
            proc.kill()
            proc.wait()
            ACTIVE.remove((proc, False))
            raise ReviewError(f'collecting the changes took longer than {COLLECT_TIMEOUT} s')
        fired = []  # The watchdog's kill; the exit code cannot tell (Windows reports 1, not a signal).
        watchdog = threading.Timer(budget, lambda: (fired.append(True), proc.kill()))
        watchdog.start()
        cut = False  # Set before reading: a cancel can interrupt the read, and `finally` still needs it.
        try:
            out = proc.stdout.read(limit + 1) if limit is not None else proc.stdout.read()
            cut = limit is not None and len(out) > limit
            if cut:
                proc.kill()
            proc.wait()
        finally:
            timed_out = bool(fired) and not cut
            watchdog.cancel()
            ACTIVE.remove((proc, False))
            proc.stdout.close()
        if timed_out:
            raise ReviewError(f'git {args[0]} took longer than {round(budget)} s' +
                              (' (the time for collecting the changes ran out)' if DEADLINE else ''))
        errors.seek(0)
        err = errors.read()
    if not cut and proc.returncode not in ok:
        raise ReviewError(f'git {args[0]} failed: {err.decode("utf-8", "replace").strip()[-300:]}')
    text = out[:limit].decode('utf-8', 'replace') if cut else out.decode('utf-8', 'replace')
    return text + ('\n[output cut here: too large to include]\n' if cut else '')


def in_repository(start):
    return bool(shutil.which('git')) and git(start, 'rev-parse', '--is-inside-work-tree', ok=(0, 128)).strip() == 'true'


def git_root(start):
    if not in_repository(start):
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


def collect_diff(root, commit=None, reviewer='codex', since=None):
    """(diff, what it covers, notes for the reviewer). The uncommitted changes with new files, or one commit, or
    the last commit when clean. With `since` (the commit a chosen conversation started from; '' when not known) a
    clean tree gives the commits after it instead, or nothing (its replies are the work) when there are none or the
    start is not known. Collection stops at MAX_DIFF; left-out files are named in the notes. All git calls together
    get COLLECT_TIMEOUT."""
    DEADLINE.append(time.monotonic() + COLLECT_TIMEOUT)
    try:
        return collect(root, commit, reviewer, since)
    finally:
        DEADLINE.pop()


def collect(root, commit, reviewer, since=None):
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
    if since is not None:
        base = since and git(root, 'rev-parse', '--verify', '--quiet', since + '^{commit}', ok=(0, 1)).strip()
        if base == sha:
            return '', 'nothing', ''  # No commits since the conversation began: its replies are the work.
        if not base:
            # Never pass an older commit off as this conversation's work.
            return '', 'nothing', (
                f'AI Baton does not know where that conversation began, so it cannot tell whether the last commit '
                f'{sha[:12]} is part of its work' +
                (f'; look at it with `git show {sha[:12]}` if the replies point to it.' if reviewer == 'codex' else '.'))
        diff = git(root, 'diff', *SAFE_DIFF, '--stat', '--patch', base, sha, limit=MAX_DIFF)
        note = '' if '[output cut here' not in diff else names_note(
            'The diff was cut; files changed in those commits',
            [n for n in git(root, 'diff', '--name-only', '-z', base, sha).split('\0') if n])
        return diff, f'the commits since that conversation began ({base[:12]}..{sha[:12]})', note
    diff, cut_note = commit_patch(root, sha)
    return diff, 'the last commit (there are no uncommitted changes)', cut_note


def collect_shadow(project, since=None, first=None):
    """No repository: the files now against AI Baton's private snapshot from `since` (the start of a chosen
    conversation; '' when not known), else the last checkpoint. When the start is not known, the baseline snapshot
    (BASELINE_REF, taken by `baton init` or the first prompt) stands in, unless it is `first`, the conversation's own
    checkpoint. The shadow repo is only read: the files are staged in a throwaway repository that borrows its
    objects, with git filters (`.gitattributes`) switched off."""
    shadow = project / MEMORY_DIR / SHADOW_DIR
    prefix = ('--git-dir', str(shadow), '--work-tree', str(project), *SHADOW_CONFIG)
    head = git(project, 'rev-parse', '--verify', '--quiet', 'HEAD', ok=(0, 1), prefix=prefix).strip()
    if not head:
        return '', 'nothing', ''
    resolve = lambda ref: ref and git(project, 'rev-parse', '--verify', '--quiet', ref + '^{commit}', ok=(0, 1),
                                      prefix=prefix).strip()
    base = resolve(since)
    if since is not None and not base:
        marked = resolve(BASELINE_REF)  # Only a real baseline; any other first commit may be someone's work.
        if marked and marked != resolve(first):
            base = marked
    if since is not None and not base:
        return '', 'nothing', ('AI Baton does not know where that conversation began, so its file changes cannot be '
                               'told apart from earlier work.')
    notes = ('This project has no git repository: the diff compares AI Baton\'s private snapshots '
             '(.agent-memory/shadow.git) with the files now. Read the files themselves; do not run git here.')
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / 'scratch'
        git(tmp, 'init', '-q', str(scratch))
        scratch_dir = scratch / '.git'
        # Git reads its own files byte by byte: LF only (Windows text mode would end the path with \r).
        write_text(scratch_dir / 'objects' / 'info' / 'alternates', str((shadow / 'objects').resolve()) + '\n')
        (scratch_dir / 'info').mkdir(exist_ok=True)
        # info/attributes outranks every .gitattributes in the project: no clean filter (an external program) runs.
        write_text(scratch_dir / 'info' / 'attributes', '* -filter\n')
        if (shadow / 'info' / 'exclude').exists():
            write_text(scratch_dir / 'info' / 'exclude', (shadow / 'info' / 'exclude').read_text(encoding='utf-8'))
        scratch_git = ('--git-dir', str(scratch_dir), '--work-tree', str(project), *SHADOW_CONFIG)
        git(project, 'add', '-A', prefix=scratch_git)
        diff = git(project, 'diff', '--cached', *SAFE_DIFF, '--stat', '--patch', base or head,
                   prefix=scratch_git, limit=MAX_DIFF)
        if '[output cut here' in diff:
            notes += ' ' + names_note('The diff was cut; changed files', [
                n for n in git(project, 'diff', '--cached', '--name-only', '-z', base or head,
                               prefix=scratch_git).split('\0') if n])
    if diff.strip():
        return diff, 'the changes since that conversation began' if base else 'the changes since the last checkpoint', notes
    if since is not None:
        return '', 'nothing', ''
    diff = git(project, 'show', *SAFE_DIFF, '--stat', '--patch', '--format=', head, prefix=prefix, limit=MAX_DIFF)
    if '[output cut here' in diff:
        notes += ' ' + names_note('The diff was cut; changed files', [
            n for n in git(project, 'show', '--name-only', '-z', '--format=', head, prefix=prefix).split('\0') if n])
    return diff, 'the changes at the last checkpoint', notes


def collect_files(project, snaps):
    """No git at all: the files the conversation's checkpoints say changed, plus files modified after its last one.
    There is no diff, so the reviewer reads them."""
    names, unnamed = [], 0
    later = [changes.from_files(project, snaps[-1].get('saved_at'))] if snaps else []
    for found in [s.get('changes') or {} for s in snaps] + later:
        listed = found.get('changed') or []
        unnamed += max(0, (found.get('changed_count') or 0) - len(listed))
        for line in listed:
            name = re.sub(r'^\s*\S+\s+', '', line)  # Drop the status letter ("M notes.md").
            if name and name not in names:
                names.append(name)
    if not names:
        return '', 'nothing', ''
    notes = 'Git is not installed, so there is no diff: the block lists the changed files. Read them; deleted files ' \
            'cannot be shown.' + (f' Up to {unnamed} more changed files were not recorded by name.' if unnamed else '')
    return '\n'.join(names), 'the files changed in that conversation (listed: git is not installed, so no diff)', notes


def collect_replies(snaps):
    """No file changes: the conversation's replies, newest last, are the work to review."""
    texts, size = [], 0
    for snap in reversed([s for s in snaps if s.get('last_reply')]):
        size += len(snap['last_reply'])
        if size > MAX_REPLIES and texts:
            break
        texts.insert(0, f'[{snap["agent"]}, {snap.get("saved_at", "")[:16]} UTC]\n{snap["last_reply"][:MAX_REPLIES]}')
    return '\n\n'.join(texts)


def binary(kind):
    return agent_binary(kind)


def stop(proc, group):
    """End a process we started. A group (the reviewer and anything it spawned) gets SIGTERM, then SIGKILL after a
    short grace period; either way it is reaped. Windows has no process groups to signal: taskkill ends the tree."""
    if not group:
        proc.kill()
        proc.wait()
        return
    if os.name == 'nt':
        kill_tree(proc)
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
    group = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    proc = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='replace', env={**os.environ, ENV_FLAG: '1'}, **group)
    ACTIVE.append((proc, True))
    try:
        out, err = proc.communicate(stdin, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        stop(proc, True)
        raise ReviewError(f'the reviewer took longer than {TIMEOUT // 60} minutes')
    finally:
        ACTIVE.remove((proc, True))
    return proc.returncode, out, err


def run_reviewer(kind, root, prompt, diff, notes='', block='diff', model='', effort=''):
    """The prompt stays small and fixed on the command line; the diff (or replies) and notes go through stdin.
    `model` and `effort` apply to this run only; empty keeps what the user configured for the agent."""
    exe = binary(kind)
    if not exe:
        raise ReviewError(f'{kind} CLI not found')
    stdin = (f'<notes>\n{notes}\n</notes>\n' if notes else '') + f'<{block}>\n{diff}\n</{block}>\n'
    if exe.lower().endswith(('.cmd', '.bat')):
        # A Windows batch wrapper (npm installs one) goes through cmd.exe, which cuts arguments at a line break and
        # expands % and quotes: the prompt goes through stdin too, behind a fixed one-line argument.
        stdin = f'<instructions>\n{prompt}\n</instructions>\n' + stdin
        prompt = 'Follow the <instructions> block at the start of the input.'
    if kind == 'codex':
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'last.md'
            # Read-only sandbox and never ask for approval, whatever the user's config says.
            choice = ([f'--model={model}'] if model else []) + \
                (['-c', f'model_reasoning_effort="{effort}"'] if effort else [])
            code, _, err = run([exe, 'exec', '--sandbox', 'read-only', '-c', 'approval_policy="never"', *choice,
                                '--skip-git-repo-check', '-o', str(out), prompt], root, stdin)
            text = out.read_text(encoding='utf-8') if out.exists() else ''
    else:
        # --tools limits which tools exist (not just which are allowed), so user settings cannot widen it.
        choice = ([f'--model={model}'] if model else []) + ([f'--effort={effort}'] if effort else [])
        # A known session id, so its transcript (kept: usage counts its tokens) never passes for the user's last model.
        session = str(uuid.uuid4())
        models.add_review_session(session)
        code, text, err = run([exe, '-p', prompt, '--tools', 'Read,Grep,Glob', '--strict-mcp-config',
                               '--session-id', session, *choice], root, stdin)
    if code != 0:
        # Never pass a failed or partial run off as a review.
        raise ReviewError(f'{kind} failed (exit {code}): {(err or text).strip()[-300:]}')
    if not text.strip():
        raise ReviewError(f'{kind} returned no review: {err.strip()[-300:]}')
    return text.strip()


def checkpoints(project):
    """Every checkpoint, oldest first (archive, then history)."""
    for line in entries(project / MEMORY_DIR):
        try:
            snap = json.loads(line)
        except ValueError:
            continue
        if isinstance(snap, dict) and snap.get('agent'):
            yield snap


def session_work(project, session):
    """(the session's checkpoints, the checkpoint saved just before its first one: the state its work began from).
    Without `session`, the newest conversation of any agent."""
    snaps = list(checkpoints(project))
    if not session and snaps:
        session = snaps[-1].get('session_id')
    own = [i for i, snap in enumerate(snaps) if session and snap.get('session_id') == session]
    if not own:
        return [], None
    return [snaps[i] for i in own], (snaps[own[0] - 1] if own[0] else None)


def session_summary(project, session):
    """The newest checkpoint of one session that has a summary."""
    return next((s for s in reversed(session_work(project, session)[0]) if s.get('summary')), None)


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
        handoff = (project / 'docs' / 'AGENT_HANDOFF.md').read_text(encoding='utf-8')
    except OSError:
        handoff = ''
    match = re.search(r'^## Recently done\n(.*?)(?=^## |\Z)', handoff, re.S | re.M)
    if match and match.group(1).strip():
        parts.append('docs/AGENT_HANDOFF.md, Recently done:\n' + match.group(1).strip()[:MAX_CONTEXT // 2])
    return '\n\n'.join(parts)


def review(start, agent, goal=None, commit=None, focus=None, session=None, model=None, effort=None):
    # A cancel at any stage (collecting the diff or reviewing) stops whatever is running, then exits.
    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        # The panel shows a "reviewing" badge meanwhile (best effort); nothing else in the project's memory changes.
        root = find_root(start)
        token = start_review(root, agent, model, effort) if root else None
        try:
            return reviewed(start, agent, goal, commit, focus, session, model, effort)
        finally:
            if token:
                end_review(root, token)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def reviewer_choice(reviewer, model, effort):
    """Check a model and effort for one review run (the agent's own settings stay as they are); empty or 'default'
    means what the user configured. Any model id is passed on (the agent knows its models best), but never one that
    could be read as a flag; the effort must be one the agent offers."""
    model, effort = ('' if v in (None, 'default') else v.strip() for v in (model, effort))
    for value in (model, effort):
        if value.startswith('-') or not models.VALUE_RE.match(value):
            raise ReviewError(f'Invalid model or effort: {value!r}')
    provider = models.PROVIDERS.get(reviewer.get('models'))
    if effort and provider:
        try:
            info = provider[0]()
        except (models.ModelError, OSError):
            info = {}
        # Without a model of its own the review runs on the configured one (else the agent's default): check that one.
        effective = model or info.get('model') or info.get('defaultModel') or ''
        option = next((o for o in info.get('options', []) if o['value'] == effective), {})
        offered = option.get('efforts') or info.get('efforts') or []
        if offered and effort not in offered:
            raise ReviewError(f'{reviewer["id"]}{" " + model if model else ""} does not support effort {effort!r}; '
                              f'choose one of: {", ".join(offered)}')
    return model, effort


def reviewed(start, agent, goal, commit, focus, session, model=None, effort=None):
    project = find_root(start)  # AI Baton context (agents, memory, handoff) only.
    agents = load_agents(project)
    reviewer = next((a for a in agents if a['id'] == agent), None)
    if not reviewer or reviewer.get('review') not in ('codex', 'claude'):
        raise ReviewError(f'{agent} cannot review; choose one of: {", ".join(a["id"] for a in agents if a.get("review"))}')
    model, effort = reviewer_choice(reviewer, model, effort)
    start = Path(start).resolve()
    snaps, before = session_work(project, session) if project and (session or not commit) else ([], None)
    started = (before or {}).get('changes') or {}
    block = 'diff'
    if in_repository(start):
        # The repository is the one around `start`, even inside a bigger AI Baton project; the reviewer runs there too.
        root = git_root(start)
        # For a chosen conversation, '' means its start is not known: never fall back to an unrelated commit.
        since = ((started.get('kind') == 'git' and started.get('commit')) or '') if session else None
        diff, what, notes = collect_diff(root, commit, reviewer['review'], since)
    elif project is None:
        raise ReviewError('Review needs a git repository or a project set up with AI Baton (baton init).')
    elif commit:
        raise ReviewError('--commit needs a git repository.')
    else:
        root = project
        if shutil.which('git') and (project / MEMORY_DIR / SHADOW_DIR).is_dir():
            since = ((started.get('kind') == 'shadow' and started.get('commit')) or '') if session else None
            first = next((s['changes'].get('commit') for s in snaps if (s.get('changes') or {}).get('kind') == 'shadow'), None)
            diff, what, notes = collect_shadow(project, since, first)
        else:
            diff, what, notes = collect_files(project, snaps)
    if not diff.strip():
        # No file changes: the work was the conversation itself (a plan, an answer, changes outside the project).
        diff, block = collect_replies(snaps), 'replies'
        if not diff:
            raise ReviewError('Nothing to review: no changes and no conversation.')
        author = next((a['label'] for a in agents if a['id'] == snaps[-1]['agent']), snaps[-1]['agent'])
        what = f'{author}\'s replies in that conversation (no file changes)'
    context = author_context(project, session)
    if context:
        notes = (notes + '\n\n' if notes else '') + \
            'What the authors said about their recent work (may be incomplete or out of date):\n' + context
    source = (f'The diff of {what} is in the <diff> block' if block == 'diff' else
              f'Nothing in the project files changed; the work to review is {what}, in the <replies> block (newest '
              f'last). Check their claims, reasoning and any steps they describe against the project') + \
        (', with notes in the <notes> block.' if notes else '.')
    prompt = PROMPT.format(
        source=source,
        goal=goal or 'not stated; take it from the authors\' notes in the <notes> block and the diff',
        focus=f'\nThe user asks you to pay special attention to: {focus}' if focus else '')
    text = run_reviewer(reviewer['review'], root, prompt, diff, notes, block, model, effort)
    return {'agent': agent, 'model': model, 'effort': effort, 'reviewed': what, 'review': text}
