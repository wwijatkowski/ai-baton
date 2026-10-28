"""Handoff benchmark runner (protocol: bench/PROTOCOL.md). Uses the real agents and your plan's tokens.

    python3 bench/run.py prepare <task>        agent A (Codex) does part 1 once; frozen into bench/frozen/<task>/
    python3 bench/run.py pilot [--seed N]      the 12 B runs (Claude), results in bench/results/<stamp>/
    python3 bench/run.py check <task>          the hidden tests against the reference solution (no agents)

Every run works in its own folder under /tmp/baton-bench-*; nothing of this checkout is visible to the agents.
"""
import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
sys.path.insert(0, str(ROOT))
import metrics  # noqa: E402  (bench/metrics.py)

BATON = ROOT / 'bin' / 'baton'
TASKS = ('shelf', 'textstats')
ARMS = ('file', 'baton')
REPEATS = 3
B_TIMEOUT = 30 * 60
A_MODEL, A_EFFORT = 'gpt-6.1-sol', 'medium'
B_MODEL, B_EFFORT = 'sonnet', 'medium'  # Pilot: sonnet (PROTOCOL.md, changes)
PROMPT_A = 'Implement part 1 of ISSUE.md as described in part1.md. Follow AGENTS.md.'
PROMPT_B = 'Continue the work on this project: finish ISSUE.md. Part 1 is done.'
# Same in both arms: edit files, run Python and read-only git; nothing else on this machine.
B_TOOLS = ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'Bash(python3:*)', 'Bash(python:*)', 'Bash(ls:*)', 'Bash(cat:*)',
           'Bash(git status:*)', 'Bash(git diff:*)', 'Bash(git log:*)', 'Bash(git show:*)']
# The file arm: the common practice without AI Baton (a handoff file the agents are asked to keep).
FILE_RULES = """## Working with multiple agents

Several coding agents take turns on this project.
- The previous agent's handoff is in docs/AGENT_HANDOFF.md: read it before you start.
- After significant work, update docs/AGENT_HANDOFF.md: what was done, how it was verified, what is left, the next step.
"""
GIT = ['git', '-c', 'user.name=bench', '-c', 'user.email=bench@example.invalid', '-c', 'commit.gpgsign=false']


def agent_binary(kind):
    home = Path.home() / '.vscode' / 'extensions'
    if kind == 'claude':
        found = sorted(home.glob('anthropic.claude-code-*/resources/native-binary/claude'))
    else:
        found = [Path(p) for p in [shutil.which('codex')] if p] or sorted(home.glob('openai.chatgpt-*/bin/*/codex'))
    if not found:
        sys.exit(f'{kind} CLI not found')
    return str(found[-1])


def git(cwd, *args):
    subprocess.run(GIT + list(args), cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def workdir(label):
    return Path(tempfile.mkdtemp(prefix=f'baton-bench-{label}-', dir='/tmp'))


def tests_pass(cwd, hidden=None):
    """(repo tests ok, hidden tests ok or None): hidden tests are copied in only for this check, then removed."""
    def run(args):
        return subprocess.run([sys.executable, '-m', 'unittest', *args], cwd=cwd, capture_output=True, text=True,
                              timeout=300).returncode == 0
    repo = run(['discover', '-s', 'tests'])
    if hidden is None:
        return repo, None
    copies = []
    for test in sorted(hidden.glob('test_*.py')):
        shutil.copy(test, cwd / test.name)
        copies.append(cwd / test.name)
    try:
        ok = run([p.stem for p in copies])
    finally:
        for p in copies:
            p.unlink(missing_ok=True)
    return repo, ok


def check(task):
    reference = BENCH / 'tasks' / task / 'reference'
    print(task, 'reference:', tests_pass(reference, BENCH / 'tasks' / task / 'hidden'))
    print(task, 'base repo:', tests_pass(BENCH / 'tasks' / task / 'repo', BENCH / 'tasks' / task / 'hidden'))


def prepare(task):
    """Agent A: part 1 in a project set up with AI Baton (Codex's global hooks save its checkpoint), then frozen."""
    frozen = BENCH / 'frozen' / task
    if frozen.exists():
        sys.exit(f'{frozen} exists: a frozen A run is never replaced once B runs used it (see PROTOCOL.md)')
    work = workdir(f'A-{task}')
    shutil.copytree(BENCH / 'tasks' / task / 'repo', work, dirs_exist_ok=True)
    git(work, 'init', '-q')
    git(work, 'add', '-A')
    git(work, 'commit', '-q', '-m', 'Project before the tags work' if task == 'shelf' else 'Project before part 1')
    subprocess.run([sys.executable, str(BATON), 'init', str(work)], check=True, stdout=subprocess.DEVNULL)
    shutil.copy(BENCH / 'tasks' / task / 'part1.md', work / 'part1.md')
    git(work, 'add', '-A')
    git(work, 'commit', '-q', '-m', 'Set up AI Baton; part 1 brief')
    started = time.time()
    proc = subprocess.run([agent_binary('codex'), 'exec', '--sandbox', 'workspace-write', '-m', A_MODEL,
                           '-c', f'model_reasoning_effort={A_EFFORT}', PROMPT_A], cwd=work, capture_output=True,
                          text=True, timeout=B_TIMEOUT)
    rollout = newest_codex_rollout(work, started)
    repo_ok, _ = tests_pass(work)
    print(f'A finished: exit {proc.returncode}, repo tests {"pass" if repo_ok else "FAIL"}, rollout {rollout}')
    if proc.returncode != 0 or not repo_ok or not (work / '.agent-memory' / 'codex.json').exists():
        sys.exit(f'A run not usable (kept for a look: {work}); fix the cause and prepare again')
    (work / 'part1.md').unlink()
    git(work, 'add', '-A')
    git(work, 'commit', '-q', '-m', 'Part 1')
    frozen.mkdir(parents=True)
    subprocess.run(['git', 'bundle', 'create', str(frozen / 'repo.bundle'), '--all'], cwd=work, check=True,
                   capture_output=True)
    with tarfile.open(frozen / 'agent-memory.tar.gz', 'w:gz') as tar:
        tar.add(work / '.agent-memory', arcname='.agent-memory')
    summary = None
    if rollout:
        s = metrics.Summary('codex')
        metrics.parse_codex(s, rollout)
        summary = s.result(None)
        shutil.copy(rollout, frozen / 'a-transcript.jsonl')
    (frozen / 'a.json').write_text(json.dumps({
        'model': A_MODEL, 'effort': A_EFFORT, 'prompt': PROMPT_A, 'exit': proc.returncode, 'seconds': round(time.time() - started),
        'summary': summary, 'at': datetime.now(timezone.utc).isoformat()}, indent=2) + '\n')
    shutil.rmtree(work)
    print(f'frozen: {frozen}')


def newest_codex_rollout(cwd, since):
    found = []
    for path in (Path.home() / '.codex' / 'sessions').glob('**/rollout-*.jsonl'):
        if path.stat().st_mtime < since:
            continue
        try:
            with open(path, encoding='utf-8') as stream:
                meta = json.loads(stream.readline())
        except (OSError, ValueError):
            continue
        if os.path.realpath((meta.get('payload') or {}).get('cwd') or '') == os.path.realpath(cwd):
            found.append(path)
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def setup_arm(work, task, arm):
    """A fresh copy of the frozen project for one B run, as the arm's user would have it."""
    frozen = BENCH / 'frozen' / task
    subprocess.run(['git', 'clone', '-q', str(frozen / 'repo.bundle'), str(work)], check=True, capture_output=True)
    if arm == 'file':
        # A's own AGENTS.md content stays; only AI Baton's block is replaced by the plain handoff rule.
        agents = (work / 'AGENTS.md').read_text()
        agents, found = re.subn(r'<!-- BEGIN AI-BATON -->.*<!-- END AI-BATON -->\n?', FILE_RULES, agents, flags=re.S)
        if found != 1:
            raise RuntimeError('AGENTS.md has no AI Baton block')
        (work / 'AGENTS.md').write_text(agents)
        (work / '.baton.json').unlink(missing_ok=True)
        (work / 'CLAUDE.md').write_text('@AGENTS.md\n')  # How Claude Code reads AGENTS.md.
    else:
        with tarfile.open(frozen / 'agent-memory.tar.gz') as tar:
            tar.extractall(work, filter='data') if hasattr(tarfile, 'data_filter') else tar.extractall(work)
        # AI Baton's Claude hooks for this project only (no user settings apply in B runs): `baton init` writes
        # project hooks when it finds no global ones, so it runs with an empty HOME.
        empty = Path(tempfile.mkdtemp(prefix='baton-bench-home-', dir='/tmp'))
        try:
            subprocess.run([sys.executable, str(BATON), 'init', str(work), '--agents=claude'], check=True,
                           env={**os.environ, 'HOME': str(empty)}, stdout=subprocess.DEVNULL)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        if not (work / '.claude' / 'settings.json').exists():
            raise RuntimeError('no project hooks written for the baton arm')
    git(work, 'add', '-A')
    git(work, 'commit', '-q', '-m', 'Workspace')


def run_b(task, arm, out):
    work = workdir(f'B-{task}-{arm}')
    shutil.rmtree(work)
    setup_arm(work, task, arm)
    session = str(uuid.uuid4())
    started = time.time()
    args = [agent_binary('claude'), '-p', PROMPT_B, '--model', B_MODEL, '--effort', B_EFFORT, '--output-format', 'json',
            '--setting-sources', 'project,local', '--permission-mode', 'acceptEdits', '--session-id', session,
            '--allowedTools', *B_TOOLS]
    try:
        proc = subprocess.run(args, cwd=work, capture_output=True, text=True, timeout=B_TIMEOUT)
        cli, exit_code, timed_out = proc.stdout, proc.returncode, False
    except subprocess.TimeoutExpired as error:
        cli, exit_code, timed_out = error.stdout or '', None, True
    seconds = round(time.time() - started)
    repo_ok, hidden_ok = tests_pass(work, BENCH / 'tasks' / task / 'hidden')
    transcripts = Path.home() / '.claude' / 'projects'
    found = [p for p in transcripts.glob(f'*/{session}.jsonl')]
    summary = None
    if found:
        s = metrics.Summary('claude')
        s.session = session
        for path in found + sorted(transcripts.glob(f'*/{session}/subagents/*.jsonl')):
            metrics.parse_claude(s, path, path.parent.name == 'subagents')
        summary = s.result(None)
        shutil.copy(found[0], out / f'{task}-{arm}-{session}.jsonl')
        for folder in {p.parent for p in found}:
            if folder.name.startswith('-private-tmp-baton-bench') or folder.name.startswith('-tmp-baton-bench'):
                shutil.rmtree(folder, ignore_errors=True)
    try:
        cli_json = json.loads(cli) if cli else None
    except ValueError:
        cli_json = {'unparsed': cli[-2000:]}
    shutil.rmtree(work, ignore_errors=True)
    return {'task': task, 'arm': arm, 'session': session, 'seconds': seconds, 'exit': exit_code, 'timed_out': timed_out,
            'repo_tests': repo_ok, 'hidden_tests': hidden_ok, 'success': bool(repo_ok and hidden_ok and not timed_out),
            'summary': summary, 'cli': cli_json and {k: cli_json.get(k) for k in ('usage', 'num_turns', 'total_cost_usd',
                                                                                  'duration_ms', 'terminal_reason', 'is_error')}}


def pilot(seed):
    for task in TASKS:
        if not (BENCH / 'frozen' / task / 'repo.bundle').exists():
            sys.exit(f'{task} has no frozen A run: python3 bench/run.py prepare {task}')
    rng = random.Random(seed)
    plan = []
    for repeat in range(REPEATS):
        for task in TASKS:
            arms = list(ARMS)
            rng.shuffle(arms)  # Both arms of a task in each block, in random order.
            plan += [(repeat, task, arm) for arm in arms]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = BENCH / 'results' / stamp
    out.mkdir(parents=True)
    (out / 'plan.json').write_text(json.dumps({'seed': seed, 'model': B_MODEL, 'effort': B_EFFORT, 'prompt': PROMPT_B,
                                               'tools': B_TOOLS, 'plan': plan}, indent=2) + '\n')
    for i, (repeat, task, arm) in enumerate(plan, 1):
        print(f'[{i}/{len(plan)}] {task} {arm} (repeat {repeat + 1})', flush=True)
        row = {'repeat': repeat, 'order': i, **run_b(task, arm, out)}
        with open(out / 'runs.jsonl', 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
        usage = (row['summary'] or {}).get('usage') or {}
        print(f'    success={row["success"]} tokens={metrics.tokens(usage) if usage else "?"} seconds={row["seconds"]}', flush=True)
    print(f'results: {out}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'pilot', 'check'))
    parser.add_argument('task', nargs='?')
    parser.add_argument('--seed', type=int, default=20261028)
    args = parser.parse_args()
    if args.command == 'pilot':
        pilot(args.seed)
    elif args.task not in TASKS:
        sys.exit(f'task: one of {", ".join(TASKS)}')
    else:
        (prepare if args.command == 'prepare' else check)(args.task)


if __name__ == '__main__':
    main()
