"""The real Claude Code and Codex CLIs run AI Baton's installed memory hooks, on any system, without an account.

Both agents run their SessionStart and UserPromptSubmit hooks before they call a model, so a prompt in a throwaway
home with no login (Claude gets an invalid API key) still exercises everything up to the model call: the hook
commands as written to the agents' settings (on Windows: Claude's exec form, Codex through cmd.exe), Codex's hook
approval as `baton hook-status` reports it, and one agent's checkpoint reaching the other's context. No tokens are
used. Not part of unittest: it needs both CLIs (`npm install -g @anthropic-ai/claude-code @openai/codex`) and network.
Run: python3 tests/e2e_hooks.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    claude, codex = shutil.which('claude'), shutil.which('codex')
    if not claude or not codex:
        sys.exit(f'Install both CLIs first (claude: {claude}, codex: {codex})')
    tmp = Path(tempfile.mkdtemp(prefix='baton-e2e-'))
    home, project = tmp / 'home', tmp / 'démo project'
    home.mkdir()
    project.mkdir()
    # Nothing of the real user's: settings, sessions and logins all live in the throwaway home.
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'CODEX_HOME': str(home / '.codex'),
           'CLAUDE_CONFIG_DIR': str(home / '.claude'), 'ANTHROPIC_API_KEY': 'sk-ant-invalid-for-baton-tests'}
    env.pop('OPENAI_API_KEY', None)
    mem = project / '.agent-memory'

    def baton(*args, payload=None):
        run = subprocess.run([sys.executable, str(ROOT / 'bin' / 'baton'), *args], env=env, capture_output=True,
                             text=True, encoding='utf-8', input=payload)
        check(run.returncode == 0, f'baton {args[0]} failed: {run.stderr}')
        return run.stdout

    def agent(command, name):
        # Codex's debug log says why a hook failed (exit code, stderr, timeout).
        run = subprocess.run(command, cwd=project, env={**env, 'RUST_LOG': 'debug'} if name == 'codex' else env, capture_output=True, text=True, encoding='utf-8',
                             errors='replace', stdin=subprocess.DEVNULL, timeout=300)
        print(f'{name} exited {run.returncode} (no login, expected): {(run.stdout + run.stderr).strip()[-160:]}')
        lines = [line for line in (run.stdout + run.stderr).splitlines() if 'hook' in line.lower()]
        for line in lines[:60]:
            print(f'  {name}: {line[-500:]}')

    def seen(by):
        """{session: {agent: saved_at}}: what `by`'s hooks delivered to each of its conversations."""
        return (json.loads((mem / 'seen.json').read_text(encoding='utf-8')) if (mem / 'seen.json').exists() else {}).get(by, {})

    def checkpoint(name, text):
        baton('hook', name, payload=json.dumps({'cwd': str(project), 'hook_event_name': 'Stop',
                                                'session_id': f'seed-{name}', 'last_assistant_message': text}))
        return json.loads((mem / f'{name}.json').read_text(encoding='utf-8'))['saved_at']

    baton('init', str(project), '--agents=')  # No project hooks: the user-level ones below do the work.
    baton('install-hooks', '--agents=claude,codex')

    # Codex: hooks are unapproved at first, then approved the way its "Allow all" does it (trusted hash per hook).
    status = json.loads(baton('hook-status', '--json', str(project)))
    check(status['codex']['state'] == 'untrusted', f'hook-status before approval: {status}')
    sys.path.insert(0, str(ROOT))
    os.environ.update({k: env[k] for k in ('HOME', 'USERPROFILE', 'CODEX_HOME')})
    from baton import hookcheck
    hooks = hookcheck.codex_hooks(codex, project)
    check(len(hooks) == 3, f'Codex lists our 3 hooks: {hooks}')
    approve(home, hooks)
    shutil.rmtree(home / '.cache' / 'ai-baton', ignore_errors=True)  # hook-status caches Codex's answer.
    status = json.loads(baton('hook-status', '--json', str(project)))
    check(status['codex']['state'] == 'ok' and status['claude']['state'] == 'ok', f'hook-status after approval: {status}')

    # Claude's checkpoint reaches a Codex conversation, and Codex's reaches a Claude conversation.
    claude_at = checkpoint('claude', 'Claude wrote the démo plan.')
    agent([codex, 'exec', '--skip-git-repo-check', 'say hi'], 'codex')
    delivered = [s for s in seen('codex').values() if s.get('claude') == claude_at]
    if not delivered:
        diagnose_codex(home, project, env)
    check(delivered, f"Codex's hooks delivered Claude's checkpoint: {seen('codex')}")
    codex_at = checkpoint('codex', 'Codex reviewed the démo plan.')
    agent([claude, '-p', 'say hi'], 'claude')
    delivered = [s for s in seen('claude').values() if s.get('codex') == codex_at]
    check(delivered, f"Claude's hooks delivered Codex's checkpoint: {seen('claude')}")

    # Each prompt hook marked its conversation as working.
    activity = json.loads((mem / 'activity.json').read_text(encoding='utf-8'))
    for name in ('claude', 'codex'):
        sessions = (activity.get(name) or {}).get('sessions') or {}
        check(any(sid != f'seed-{name}' and e['state'] == 'working' for sid, e in sessions.items()),
              f"{name}'s UserPromptSubmit hook ran: {activity.get(name)}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'Real agents ran AI Baton hooks on {sys.platform}: OK')


def approve(home, hooks):
    """Trust these Codex hooks the way its "Allow all" does: their current hash in config.toml."""
    (home / '.codex').mkdir(exist_ok=True)
    (home / '.codex' / 'config.toml').write_text(''.join(
        f'[hooks.state.{json.dumps(h["key"])}]\ntrusted_hash = "{h["currentHash"]}"\n\n' for h in hooks), encoding='utf-8')


def diagnose_codex(home, project, env):
    """What went wrong: the hook command run the way Codex runs it, and what Codex recorded about its hooks."""
    hook = json.loads((home / '.codex' / 'hooks.json').read_text(encoding='utf-8'))['hooks']['SessionStart'][0]['hooks'][0]
    payload = json.dumps({'cwd': str(project), 'hook_event_name': 'SessionStart', 'session_id': 'diagnose'})
    # Codex: `%COMSPEC% /C "<command>"` on Windows, `$SHELL -lc <command>` elsewhere.
    command = f'cmd.exe /C "{hook["command"]}"' if os.name == 'nt' else ['/bin/sh', '-lc', hook['command']]
    run = subprocess.run(command, cwd=project, env=env, input=payload, capture_output=True, text=True, encoding='utf-8',
                         errors='replace')
    print(f'hook command: {hook["command"]}\nrun as Codex does: exit {run.returncode}\n'
          f'stdout: {run.stdout[:300]}\nstderr: {run.stderr[-1500:]}')
    # Codex clears the environment for hooks on Windows and replays only part of it.
    bare = {k: v for k, v in env.items() if k.upper() in ('PATH', 'COMSPEC', 'HOME', 'USERPROFILE')}
    run = subprocess.run(command, cwd=project, env=bare, input=payload, capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    print(f'with a bare environment: exit {run.returncode}\nstderr: {run.stderr[-800:]}')
    # Run it inside Codex once more, next to a hook that dumps the environment Codex gives hooks; both write files.
    trace = home / 'trace'
    trace.mkdir(exist_ok=True)
    out, err, envdump = (str(trace / n).replace('\\', '/') for n in ('out.txt', 'err.txt', 'env.txt'))
    # A script, so the command line Codex quotes stays simple: dump the environment, then run our hook with its
    # output in files.
    if os.name == 'nt':
        script = trace / 'trace.cmd'
        script.write_text(f'@set > "{envdump}"\r\n@{hook["command"]} > "{out}" 2> "{err}"\r\n', encoding='utf-8')
    else:
        script = trace / 'trace.sh'
        script.write_text(f'env > "{envdump}"\n{hook["command"]} > "{out}" 2> "{err}"\n', encoding='utf-8')
        script.chmod(0o755)
    config = json.loads((home / '.codex' / 'hooks.json').read_text(encoding='utf-8'))
    config['hooks']['SessionStart'] = [{'hooks': [{'type': 'command', 'timeout': 10,
                                                   'command': f'"{script}"'}]}]
    (home / '.codex' / 'hooks.json').write_text(json.dumps(config), encoding='utf-8')
    from baton import hookcheck
    approve(home, hookcheck.codex_hooks(shutil.which('codex'), project))
    subprocess.run([shutil.which('codex'), 'exec', '--skip-git-repo-check', 'say hi'], cwd=project, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    for name in ('out.txt', 'err.txt', 'env.txt'):
        path = trace / name
        text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else '(not written)'
        if name == 'env.txt' and path.exists():  # Names only, plus the ones that decide how Python starts.
            keep = ('PATH', 'SYSTEMROOT', 'COMSPEC', 'HOME', 'USERPROFILE', 'TEMP', 'PYTHONHOME', 'PATHEXT')
            text = '\n'.join(line if line.split('=')[0].upper() in keep else line.split('=')[0]
                             for line in text.splitlines())
        print(f'--- inside Codex, {name}:\n{text[-2500:]}')
    for rollout in (home / '.codex' / 'sessions').rglob('*.jsonl'):
        for line in rollout.read_text(encoding='utf-8', errors='replace').splitlines():
            if 'hook' in line.lower():
                print('rollout:', line[:1500])
    for log in (home / '.codex').rglob('*.log'):
        for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
            if 'hook' in line.lower():
                print('log:', line[:600])


def check(ok, message):
    if not ok:
        sys.exit(f'FAIL: {message}')


if __name__ == '__main__':
    main()
