"""Where a checkpoint's changes live, so memory can point at them instead of copying them.

git     -> the project's own repository: branch, commit and `git status`
shadow  -> no repository: a private git repo in .agent-memory/ snapshots the files at each checkpoint
files   -> no git at all: the files modified since the previous checkpoint
"""
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SHADOW_DIR = 'shadow.git'
SKIP_DIRS = {'.git', '.agent-memory', 'node_modules', '.venv', 'venv', 'env', '__pycache__', 'dist', 'build',
             'target', '.next', '.cache', '.idea', '.vscode', '.pytest_cache', '.mypy_cache', '.tox'}
# Never copy credentials into the shadow repo, even though it stays local.
SECRET_FILES = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', '*.keystore', 'id_rsa*', 'id_ed25519*',
                'credentials*', '.netrc')
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_WALK = 20000
MAX_LISTED = 50
# Shadow commits must not pick up the user's signing keys or git hooks.
SHADOW_CONFIG = ('-c', 'user.name=AI Baton', '-c', 'user.email=baton@localhost', '-c', 'commit.gpgsign=false',
                 '-c', 'core.hooksPath=/dev/null', '-c', 'core.autocrlf=false')


def git(cwd, *args, git_dir=None, timeout=3):
    """Output of a git command, or None when git is missing or the command fails."""
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


def shadow_exclude(root):
    large = [rel for rel, st in walk(root) if st.st_size > MAX_FILE_BYTES]
    escape = lambda rel: '/' + re.sub(r'([*?\[\\!#])', r'\\\1', rel)
    return '\n'.join([f'{d}/' for d in sorted(SKIP_DIRS)] + list(SECRET_FILES) + [escape(r) for r in large]) + '\n'


def from_shadow(root, mem, message):
    git_dir = mem / SHADOW_DIR
    if not git_dir.exists() and git(root, 'init', '-q', git_dir=git_dir) is None:
        return None
    (git_dir / 'info').mkdir(exist_ok=True)
    (git_dir / 'info' / 'exclude').write_text(shadow_exclude(root))
    if git(root, 'add', '-A', git_dir=git_dir, timeout=6) is None:
        return None
    before = git(root, 'rev-parse', '-q', '--verify', 'HEAD', git_dir=git_dir)
    git(root, 'commit', '-q', '-m', message, git_dir=git_dir)  # Fails harmlessly when nothing changed.
    after = git(root, 'rev-parse', '--short', 'HEAD', git_dir=git_dir)
    if not after:
        return None
    diff = git(root, 'diff', '--name-status', before, 'HEAD', git_dir=git_dir) if before \
        else git(root, 'ls-files', git_dir=git_dir)
    lines = [re.sub(r'\t+', ' ', line) for line in (diff or '').splitlines()]
    return {'kind': 'shadow', 'commit': after, **listed(lines)}


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
