"""Where a checkpoint's changes live, so memory can point at them instead of copying them.

git     -> the project's own repository: branch, commit and `git status`
shadow  -> no repository: a private git repo in .agent-memory/ snapshots the files at each checkpoint
files   -> no git at all: the files modified since the previous checkpoint
"""
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .project import write_text

SHADOW_DIR = 'shadow.git'
SKIP_DIRS = {'.git', '.agent-memory', 'node_modules', '.venv', 'venv', 'env', '__pycache__', 'dist', 'build',
             'target', '.next', '.cache', '.idea', '.vscode', '.pytest_cache', '.mypy_cache', '.tox'}
# Never copy credentials into the shadow repo, even though it stays local.
SECRET_FILES = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', '*.keystore', 'id_rsa*', 'id_ed25519*',
                'credentials*', '.netrc')
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_WALK = 20000
MAX_LISTED = 50
BASELINE_BUDGET = 5  # Seconds for the first snapshot, taken inside a prompt hook (10 s limit, context still to come).
BASELINE_REF = 'refs/baton/baseline'
# Shadow commits must not pick up the user's signing keys or git hooks.
SHADOW_CONFIG = ('-c', 'user.name=AI Baton', '-c', 'user.email=baton@localhost', '-c', 'commit.gpgsign=false',
                 '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false')


def git(cwd, *args, git_dir=None, timeout=3, deadline=None):
    """Output of a git command, or None when git is missing, the command fails or the `deadline` (monotonic) passed."""
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            return None
    cmd = ['git', '--git-dir', str(git_dir), '--work-tree', str(cwd), *SHADOW_CONFIG] if git_dir else ['git']
    try:
        return subprocess.run([*cmd, *args], cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def walk(root):
    """(relative path, stat) for project files, skipping dependency and build folders."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            seen += 1
            if seen > MAX_WALK:
                return
            path = Path(dirpath, name)
            try:
                yield path.relative_to(root).as_posix(), path.stat()
            except OSError:
                continue


def listed(lines):
    return {'changed': lines[:MAX_LISTED], 'changed_count': len(lines)}


def from_git(root):
    lines = (git(root, 'status', '--short') or '').splitlines()
    return {'kind': 'git', 'branch': git(root, 'branch', '--show-current') or '',
            'commit': git(root, 'rev-parse', '--short', 'HEAD') or '', **listed(lines)}


def shadow_exclude(root, deadline=None):
    """The shadow repo's exclude list, or None when the `deadline` passed (large files might then go unlisted)."""
    large = [rel for rel, st in walk(root) if st.st_size > MAX_FILE_BYTES]
    if deadline is not None and time.monotonic() > deadline:
        return None
    escape = lambda rel: '/' + re.sub(r'([*?\[\\!#])', r'\\\1', rel)
    return '\n'.join([f'{d}/' for d in sorted(SKIP_DIRS)] + list(SECRET_FILES) + [escape(r) for r in large]) + '\n'


def from_shadow(root, mem, message, deadline=None):
    git_dir = mem / SHADOW_DIR
    run = lambda *args, timeout=3: git(root, *args, git_dir=git_dir, timeout=timeout, deadline=deadline)
    if not git_dir.exists() and git(root, 'init', '-q', git_dir=git_dir, deadline=deadline) is None:
        return None
    exclude = shadow_exclude(root, deadline)
    if exclude is None:
        return None
    (git_dir / 'info').mkdir(exist_ok=True)
    write_text(git_dir / 'info' / 'exclude', exclude)
    # Outranks the project's .gitattributes: no clean filter (an external program) runs while snapshotting.
    write_text(git_dir / 'info' / 'attributes', '* -filter\n')
    if run('add', '-A', timeout=6) is None:
        return None
    before = run('rev-parse', '-q', '--verify', 'HEAD')
    # The first commit may be empty (an empty folder); later ones fail harmlessly when nothing changed.
    run('commit', '-q', *(['--allow-empty'] if before is None else []), '-m', message)
    after = run('rev-parse', '--short', 'HEAD')
    if not after:
        return None
    diff = run('diff', '--name-status', before, 'HEAD') if before else run('ls-files')
    lines = [re.sub(r'\t+', ' ', line) for line in (diff or '').splitlines()]
    return {'kind': 'shadow', 'commit': after, **listed(lines)}


def baseline(root, mem):
    """No repository: snapshot the files once, before any agent works, and mark it with BASELINE_REF, so the first
    conversation's changes can be told apart (see review.py). Runs until the shadow repo has a commit: a failed or
    timed-out attempt is retried at the next prompt. After that it costs one quick git call."""
    git_dir = mem / SHADOW_DIR
    if git_dir.exists():
        if git(root, 'rev-parse', '-q', '--verify', 'HEAD', git_dir=git_dir) is not None:
            return None  # Snapshots exist (a baseline, or checkpoints from before baselines).
    elif not shutil.which('git') or git(root, 'rev-parse', '--is-inside-work-tree') == 'true':
        return None
    deadline = time.monotonic() + BASELINE_BUDGET
    found = from_shadow(root, mem, 'baseline', deadline)
    if found and git(root, 'update-ref', BASELINE_REF, 'HEAD', git_dir=git_dir, deadline=deadline) is None:
        return None
    return found


def from_files(root, since):
    try:
        cutoff = datetime.fromisoformat(since).timestamp() if since else None
    except ValueError:
        cutoff = None
    recent = [] if cutoff is None else sorted(
        ((st.st_mtime, rel) for rel, st in walk(root) if st.st_mtime > cutoff), reverse=True)
    return {'kind': 'files', **listed(['M ' + rel for _, rel in recent])}


def capture(root, mem, since, message):
    """Describe what changed at this checkpoint, using the best source available."""
    if git(root, 'rev-parse', '--is-inside-work-tree') == 'true':
        return from_git(root)
    if shutil.which('git'):
        result = from_shadow(root, mem, message)
        if result:
            return result
    return from_files(root, since)
