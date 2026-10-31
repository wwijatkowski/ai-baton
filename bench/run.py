"""Handoff benchmark runner. Uses the real agents and your plan's tokens.

Pilot 1 (bench/PROTOCOL.md): shelf, textstats; a handoff file vs AI Baton.
    python3 bench/run.py prepare <task>        agent A (Codex) does part 1 once; frozen into bench/frozen/<task>/
    python3 bench/run.py pilot [--seed N]      the 12 B runs (Claude), results in bench/results/<stamp>/
Pilot 2 (bench/PROTOCOL-2.md): habits, pricing; a missing or stale handoff; nothing / pasted reply / AI Baton.
    python3 bench/run.py prepare2 <task>       agent A once; frozen into bench/frozen2/<task>/
    python3 bench/run.py pilot2 [--seed N]     the 12 B runs
Pilot 3 (bench/PROTOCOL-3.md): report, bundles; the spec only in A's first message; plain vs AI Baton workflow.
    python3 bench/run.py prepare3 <task>       2 pairs of A runs (plain, baton); frozen into bench/frozen3/<task>/
    python3 bench/run.py pilot3 [--seed N]     the 16 B runs
Both:
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
import redact  # noqa: E402  (bench/redact.py: no user config in saved transcripts)

BATON = ROOT / 'bin' / 'baton'
TASKS = ('shelf', 'textstats')
TASKS2 = ('habits', 'pricing')
TASKS3 = {'report': 'habits', 'bundles': 'pricing'}  # task -> base repo
PAIRS3 = 2
# The user knows part 1 is done and asks for the rest (the first wording made B stop after checking part 1).
PROMPT_B3 = 'Part 1 of the feature from our previous conversation is done. Please do part 2 now and finish it.'
CONDITIONS = ('missing', 'stale')
ARMS2 = ('none', 'paste', 'baton')
ARMS = ('file', 'baton')
REPEATS = 3
B_TIMEOUT = 30 * 60
A_MODEL, A_EFFORT = 'gpt-6.1-sol', 'medium'
B_MODEL, B_EFFORT = 'sonnet', 'medium'  # Pilot: sonnet (PROTOCOL.md, changes)
PROMPT_A = 'Implement part 1 of ISSUE.md as described in part1.md. Follow AGENTS.md.'
PROMPT_B = 'Continue the work on this project: finish ISSUE.md. Part 1 is done.'
PROMPT_A2 = 'Implement part 1 of ISSUE.md as described in part1.md.'
PROMPT_B2 = 'Continue the work on this project: finish ISSUE.md.'
# Pilot 2: in every arm's AGENTS.md, so no arm is told to trust old notes more than another.
NEUTRAL_RULE = ('\n## Notes from earlier work\nNotes from earlier work (handoff files, messages, checkpoints) may be out '
                'of date: check them against the code and git before relying on them.\n')
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
    if task in TASKS3:
        source, base = BENCH / 'tasks3' / task, BENCH / 'tasks' / TASKS3[task] / 'repo'
    else:
        source = BENCH / 'tasks' / task
        base = source / 'repo'
    print(task, 'reference:', tests_pass(source / 'reference', source / 'hidden'))
    print(task, 'base repo:', tests_pass(base, source / 'hidden'))


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
                          text=True, timeout=B_TIMEOUT, stdin=subprocess.DEVNULL)
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
        redact.copy(rollout, frozen / 'a-transcript.jsonl')
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


def run_b(task, arm, out, setup=None, prompt=PROMPT_B, label=None, hidden=None):
    label = label or f'{task}-{arm}'
    work = workdir(f'B-{label}')
    shutil.rmtree(work)
    (setup or setup_arm)(work, task, arm)
    session = str(uuid.uuid4())
    started = time.time()
    args = [agent_binary('claude'), '-p', prompt, '--model', B_MODEL, '--effort', B_EFFORT, '--output-format', 'json',
            '--setting-sources', 'project,local', '--permission-mode', 'acceptEdits', '--session-id', session,
            '--allowedTools', *B_TOOLS]
    try:
        proc = subprocess.run(args, cwd=work, capture_output=True, text=True, timeout=B_TIMEOUT, stdin=subprocess.DEVNULL)
        cli, exit_code, timed_out = proc.stdout, proc.returncode, False
    except subprocess.TimeoutExpired as error:
        cli, exit_code, timed_out = error.stdout or '', None, True
    seconds = round(time.time() - started)
    repo_ok, hidden_ok = tests_pass(work, hidden or BENCH / 'tasks' / task / 'hidden')
    transcripts = Path.home() / '.claude' / 'projects'
    found = [p for p in transcripts.glob(f'*/{session}.jsonl')]
    summary = None
    if found:
        s = metrics.Summary('claude')
        s.session = session
        for path in found + sorted(transcripts.glob(f'*/{session}/subagents/*.jsonl')):
            metrics.parse_claude(s, path, path.parent.name == 'subagents')
        summary = s.result(None)
        shutil.copy(found[0], out / f'{label}-{session}.jsonl')
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


# ---------- pilot 2 ----------

def prepare2(task):
    """Agent A once per task, in a project set up with AI Baton (its hooks capture the final reply); frozen with a
    neutral history: the project, then A's code and tests only (no docs, so B cannot find a handoff in git)."""
    frozen = BENCH / 'frozen2' / task
    if frozen.exists():
        sys.exit(f'{frozen} exists: a frozen A run is never replaced once B runs used it (see PROTOCOL-2.md)')
    source = BENCH / 'tasks' / task
    work = workdir(f'A-{task}')
    shutil.copytree(source / 'repo', work, dirs_exist_ok=True)
    (work / 'AGENTS.md').write_text((source / 'agents.md').read_text() + NEUTRAL_RULE)
    git(work, 'init', '-q')
    git(work, 'add', '-A')
    git(work, 'commit', '-q', '-m', 'Project')
    base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=work, capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run([sys.executable, str(BATON), 'init', str(work)], check=True, stdout=subprocess.DEVNULL)
    shutil.copy(source / 'part1.md', work / 'part1.md')
    started = time.time()
    proc = subprocess.run([agent_binary('codex'), 'exec', '--sandbox', 'workspace-write', '-m', A_MODEL,
                           '-c', f'model_reasoning_effort={A_EFFORT}', PROMPT_A2], cwd=work, capture_output=True,
                          text=True, timeout=B_TIMEOUT, stdin=subprocess.DEVNULL)
    rollout = newest_codex_rollout(work, started)
    repo_ok, _ = tests_pass(work)
    memory = work / '.agent-memory' / 'codex.json'
    print(f'A finished: exit {proc.returncode}, repo tests {"pass" if repo_ok else "FAIL"}, rollout {rollout}')
    if proc.returncode != 0 or not repo_ok or not memory.exists():
        sys.exit(f'A run not usable (kept for a look: {work}); fix the cause and prepare again')
    # What A changed outside its code and tests (docs, rules) is left out of the frozen history, and noted.
    changed = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=work, capture_output=True,
                             text=True, check=True).stdout.splitlines()
    paths = [line[3:] for line in changed]
    code = [p for p in paths if not (p.startswith(('docs/', '.agent-memory/', '.claude/', '.codex/')) or
                                     p in ('AGENTS.md', 'CLAUDE.md', '.baton.json', '.gitignore', 'part1.md'))]
    left_out = sorted(set(paths) - set(code))
    clean = workdir(f'A-{task}-frozen')
    shutil.rmtree(clean)
    subprocess.run(['git', 'clone', '-q', str(work), str(clean)], check=True, capture_output=True)
    subprocess.run(['git', 'checkout', '-q', base], cwd=clean, check=True)
    subprocess.run(['git', 'checkout', '-q', '-B', 'main'], cwd=clean, check=True)
    for path in code:
        target = clean / path
        if (work / path).exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(work / path, target)
        else:
            target.unlink(missing_ok=True)
    (clean / 'AGENTS.md').unlink()  # Each arm writes its own.
    git(clean, 'add', '-A')
    git(clean, 'commit', '-q', '-m', 'Part 1')
    if not tests_pass(clean)[0]:
        sys.exit(f'the frozen code alone fails its tests (kept: {work}, {clean})')
    frozen.mkdir(parents=True)
    subprocess.run(['git', 'bundle', 'create', str(frozen / 'repo.bundle'), 'main'], cwd=clean, check=True,
                   capture_output=True)
    with tarfile.open(frozen / 'agent-memory.tar.gz', 'w:gz') as tar:
        tar.add(work / '.agent-memory', arcname='.agent-memory')
    reply = json.loads(memory.read_text()).get('last_reply') or ''
    summary = None
    if rollout:
        s = metrics.Summary('codex')
        metrics.parse_codex(s, rollout)
        summary = s.result(None)
        redact.copy(rollout, frozen / 'a-transcript.jsonl')
    (frozen / 'a.json').write_text(json.dumps({
        'model': A_MODEL, 'effort': A_EFFORT, 'prompt': PROMPT_A2, 'exit': proc.returncode,
        'seconds': round(time.time() - started), 'summary': summary, 'final_reply': reply,
        'left_out_of_history': left_out, 'at': datetime.now(timezone.utc).isoformat()}, indent=2) + '\n')
    shutil.rmtree(work)
    shutil.rmtree(clean)
    print(f'frozen: {frozen}; left out of the history: {left_out}')


def setup_arm2(work, task, arm, condition):
    frozen, source = BENCH / 'frozen2' / task, BENCH / 'tasks' / task
    subprocess.run(['git', 'clone', '-q', '-b', 'main', str(frozen / 'repo.bundle'), str(work)], check=True,
                   capture_output=True)
    (work / 'AGENTS.md').write_text((source / 'agents.md').read_text() + NEUTRAL_RULE)
    if arm == 'baton':
        with tarfile.open(frozen / 'agent-memory.tar.gz') as tar:
            tar.extractall(work, filter='data') if hasattr(tarfile, 'data_filter') else tar.extractall(work)
        empty = Path(tempfile.mkdtemp(prefix='baton-bench-home-', dir='/tmp'))
        try:
            subprocess.run([sys.executable, str(BATON), 'init', str(work), '--agents=claude'], check=True,
                           env={**os.environ, 'HOME': str(empty)}, stdout=subprocess.DEVNULL)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        if not (work / '.claude' / 'settings.json').exists() or 'BEGIN AI-BATON' not in (work / 'AGENTS.md').read_text():
            raise RuntimeError('AI Baton not set up in the baton arm')
        # Only AI Baton itself: the docs `baton init` adds as templates would differ from the other arms.
        (work / 'docs' / 'STATUS.md').unlink(missing_ok=True)
        shutil.rmtree(work / 'docs' / 'knowledge', ignore_errors=True)
        (work / 'docs' / 'AGENT_HANDOFF.md').unlink(missing_ok=True)
    else:
        (work / 'CLAUDE.md').write_text('@AGENTS.md\n')  # How Claude Code reads AGENTS.md.
    git(work, 'add', '-A')
    git(work, 'commit', '-q', '-m', 'Workspace')
    if condition == 'stale':
        # Written before part 1, so it belongs to the first commit: git must not show it as newer than the code.
        tip = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=work, capture_output=True, text=True, check=True).stdout.strip()
        git(work, 'checkout', '-q', 'HEAD~2')
        (work / 'docs').mkdir(exist_ok=True)
        shutil.copy(source / 'stale-handoff.md', work / 'docs' / 'AGENT_HANDOFF.md')
        git(work, 'add', '-A')
        git(work, 'commit', '-q', '--amend', '--no-edit')
        git(work, 'cherry-pick', f'{tip}~1', tip)
        git(work, 'checkout', '-q', '-B', 'main')


def versions():
    def out(args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=30).stdout.strip()[:200]
        except (OSError, subprocess.TimeoutExpired):
            return None
    return {'ai_baton_commit': out(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']),
            'claude': out([agent_binary('claude'), '--version']), 'codex': out([agent_binary('codex'), '--version'])}


def pilot2(seed):
    for task in TASKS2:
        if not (BENCH / 'frozen2' / task / 'repo.bundle').exists():
            sys.exit(f'{task} has no frozen A run: python3 bench/run.py prepare2 {task}')
    rng = random.Random(seed)
    plan = []
    for task in TASKS2:
        cells = [(task, condition, arm) for condition in CONDITIONS for arm in ARMS2]
        rng.shuffle(cells)
        plan += cells
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = BENCH / 'results' / f'{stamp}-pilot2'
    out.mkdir(parents=True)
    (out / 'plan.json').write_text(json.dumps({'seed': seed, 'model': B_MODEL, 'effort': B_EFFORT, 'prompt': PROMPT_B2,
                                               'tools': B_TOOLS, 'versions': versions(), 'plan': plan}, indent=2) + '\n')
    for i, (task, condition, arm) in enumerate(plan, 1):
        print(f'[{i}/{len(plan)}] {task} {condition} {arm}', flush=True)
        prompt = PROMPT_B2
        if arm == 'paste':
            reply = json.loads((BENCH / 'frozen2' / task / 'a.json').read_text())['final_reply']
            prompt += "\n\nThe previous agent's last message:\n\n" + reply
        row = {'order': i, 'condition': condition, **run_b(
            task, arm, out, setup=lambda w, t, a, c=condition: setup_arm2(w, t, a, c), prompt=prompt,
            label=f'{task}-{condition}-{arm}')}
        with open(out / 'runs.jsonl', 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
        usage = (row['summary'] or {}).get('usage') or {}
        print(f'    success={row["success"]} tokens={metrics.tokens(usage) if usage else "?"} seconds={row["seconds"]}', flush=True)
    print(f'results: {out}')


# ---------- pilot 3 ----------

def prepare3(task, seed, variant=''):
    """PAIRS3 independent pairs of A runs (plain, baton), order randomized in each pair; everything A writes is kept."""
    frozen = BENCH / f'frozen3{variant}' / task
    if frozen.exists():
        sys.exit(f'{frozen} exists: frozen A runs are never replaced once B runs used them (see PROTOCOL-3.md)')
    only = ('baton',) if variant == 'b' else ('plain', 'baton')  # 3b: the AI Baton arm again, with a newer rule.
    base = BENCH / 'tasks' / TASKS3[task]
    spec = (BENCH / 'tasks3' / task / 'spec.md').read_text()
    prompt = spec.rstrip() + '\n\nPlease do part 1 now; part 2 will be done later in another conversation.'
    rng = random.Random(f'{seed}-{task}')
    for pair in range(1, PAIRS3 + 1):
        kinds = [k for k in ('plain', 'baton') if k in only]
        rng.shuffle(kinds)
        for kind in kinds:
            work = workdir(f'A-{task}-{pair}-{kind}')
            shutil.copytree(base / 'repo', work, dirs_exist_ok=True)
            (work / 'ISSUE.md').unlink(missing_ok=True)  # Pilot 2's issue: the spec here is only in A's first message.
            (work / 'AGENTS.md').write_text((base / 'agents.md').read_text())
            git(work, 'init', '-q', '-b', 'main')
            git(work, 'add', '-A')
            git(work, 'commit', '-q', '-m', 'Project')
            if kind == 'baton':
                subprocess.run([sys.executable, str(BATON), 'init', str(work)], check=True, stdout=subprocess.DEVNULL)
                git(work, 'add', '-A')
                git(work, 'commit', '-q', '-m', 'Set up AI Baton')
            reply_file = workdir(f'A-reply-{task}-{pair}-{kind}') / 'reply.txt'
            started = time.time()
            proc = None
            for attempt in (1, 2):  # A crash (no reply) is rerun once; a poor result is never rerun.
                proc = subprocess.run([agent_binary('codex'), 'exec', '--sandbox', 'workspace-write', '-m', A_MODEL,
                                       '-c', f'model_reasoning_effort={A_EFFORT}', '-o', str(reply_file), prompt],
                                      cwd=work, capture_output=True, text=True, timeout=B_TIMEOUT,
                                      stdin=subprocess.DEVNULL)
                if reply_file.exists() and reply_file.read_text().strip():
                    break
                print(f'A {task} {pair} {kind}: no reply (exit {proc.returncode}), attempt {attempt}')
            reply = reply_file.read_text() if reply_file.exists() else ''
            shutil.rmtree(reply_file.parent, ignore_errors=True)
            rollout = newest_codex_rollout(work, started)
            repo_ok, _ = tests_pass(work)
            git(work, 'add', '-A')
            subprocess.run(GIT + ['commit', '-q', '-m', 'Work in progress'], cwd=work, capture_output=True)
            state = frozen / f'{pair}-{kind}'
            state.mkdir(parents=True)
            subprocess.run(['git', 'bundle', 'create', str(state / 'repo.bundle'), 'main'], cwd=work, check=True,
                           capture_output=True)
            if (work / '.agent-memory').exists():
                with tarfile.open(state / 'agent-memory.tar.gz', 'w:gz') as tar:
                    tar.add(work / '.agent-memory', arcname='.agent-memory')
            summary = None
            if rollout:
                s = metrics.Summary('codex')
                metrics.parse_codex(s, rollout)
                summary = s.result(None)
                redact.copy(rollout, state / 'a-transcript.jsonl')
            (state / 'a.json').write_text(json.dumps({
                'model': A_MODEL, 'effort': A_EFFORT, 'kind': kind, 'pair': pair, 'exit': proc.returncode,
                'repo_tests': repo_ok, 'seconds': round(time.time() - started), 'summary': summary,
                'final_reply': reply, 'at': datetime.now(timezone.utc).isoformat()}, indent=2) + '\n')
            shutil.rmtree(work)
            print(f'A {task} pair {pair} {kind}: exit {proc.returncode}, repo tests {"pass" if repo_ok else "FAIL"}, '
                  f'reply {len(reply)} chars', flush=True)


def setup_arm3(work, task, state, arm):
    subprocess.run(['git', 'clone', '-q', '-b', 'main', str(state / 'repo.bundle'), str(work)], check=True,
                   capture_output=True)
    if arm == 'baton':
        with tarfile.open(state / 'agent-memory.tar.gz') as tar:
            tar.extractall(work, filter='data') if hasattr(tarfile, 'data_filter') else tar.extractall(work)
        empty = Path(tempfile.mkdtemp(prefix='baton-bench-home-', dir='/tmp'))
        try:
            subprocess.run([sys.executable, str(BATON), 'init', str(work), '--agents=claude'], check=True,
                           env={**os.environ, 'HOME': str(empty)}, stdout=subprocess.DEVNULL)
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        if not (work / '.claude' / 'settings.json').exists():
            raise RuntimeError('no project hooks written for the baton arm')
    elif not (work / 'CLAUDE.md').exists():
        (work / 'CLAUDE.md').write_text('@AGENTS.md\n')  # How Claude Code reads AGENTS.md.
    git(work, 'add', '-A')
    subprocess.run(GIT + ['commit', '-q', '-m', 'Workspace'], cwd=work, capture_output=True)


def pilot3(seed, variant=''):
    rng = random.Random(seed)
    plan = []
    for task in TASKS3:
        states = sorted((BENCH / f'frozen3{variant}' / task).glob('*-*'))
        if len(states) != (1 if variant == 'b' else 2) * PAIRS3:
            sys.exit(f'{task}: {len(states)} frozen A states, expected {2 * PAIRS3}: python3 bench/run.py prepare3 {task}')
        cells = []
        for state in states:
            arms = ('baton',) if state.name.endswith('-baton') else ('none', 'paste', 'respec')
            cells += [(task, state.name, arm) for arm in arms]
        rng.shuffle(cells)
        plan += cells
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = BENCH / 'results' / f'{stamp}-pilot3{variant}'
    out.mkdir(parents=True)
    (out / 'plan.json').write_text(json.dumps({'seed': seed, 'model': B_MODEL, 'effort': B_EFFORT, 'prompt': PROMPT_B3,
                                               'tools': B_TOOLS, 'versions': versions(), 'plan': plan}, indent=2) + '\n')
    for i, (task, state_name, arm) in enumerate(plan, 1):
        state = BENCH / f'frozen3{variant}' / task / state_name
        print(f'[{i}/{len(plan)}] {task} {state_name} {arm}', flush=True)
        prompt = PROMPT_B3
        if arm == 'paste':
            prompt += "\n\nThe previous agent's last message:\n\n" + json.loads((state / 'a.json').read_text())['final_reply']
        elif arm == 'respec':
            prompt += '\n\nThe original request:\n\n' + (BENCH / 'tasks3' / task / 'spec.md').read_text()
        row = {'order': i, 'state': state_name, **run_b(
            task, arm, out, setup=lambda w, t, a, st=state: setup_arm3(w, t, st, a), prompt=prompt,
            label=f'{task}-{state_name}-{arm}', hidden=BENCH / 'tasks3' / task / 'hidden')}
        with open(out / 'runs.jsonl', 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
        usage = (row['summary'] or {}).get('usage') or {}
        print(f'    success={row["success"]} tokens={metrics.tokens(usage) if usage else "?"} seconds={row["seconds"]}', flush=True)
    print(f'results: {out}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'pilot', 'check', 'prepare2', 'pilot2', 'prepare3', 'pilot3'))
    parser.add_argument('task', nargs='?')
    parser.add_argument('--seed', type=int, default=20261028)
    parser.add_argument('--variant', default='', choices=('', 'b'), help='pilot 3b: the AI Baton arm only, new A runs')
    args = parser.parse_args()
    if args.command == 'pilot':
        pilot(args.seed)
    elif args.command == 'pilot2':
        pilot2(args.seed)
    elif args.command == 'pilot3':
        pilot3(args.seed, args.variant)
    elif args.command == 'prepare3':
        if args.task not in TASKS3:
            sys.exit(f'task: one of {", ".join(TASKS3)}')
        prepare3(args.task, args.seed, args.variant)
    elif args.task not in TASKS + TASKS2 + tuple(TASKS3):
        sys.exit(f'task: one of {", ".join(TASKS + TASKS2 + tuple(TASKS3))}')
    else:
        {'prepare': prepare, 'check': check, 'prepare2': prepare2}[args.command](args.task)


if __name__ == '__main__':
    main()
