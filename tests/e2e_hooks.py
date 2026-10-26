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
        run = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, encoding='utf-8',
                             errors='replace', stdin=subprocess.DEVNULL, timeout=300)
        print(f'{name} exited {run.returncode} (no login, expected): {(run.stdout + run.stderr).strip()[-160:]}')

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
    (home / '.codex').mkdir(exist_ok=True)
    with open(home / '.codex' / 'config.toml', 'a', encoding='utf-8') as config:
        for hook in hooks:
            config.write(f'[hooks.state.{json.dumps(hook["key"])}]\ntrusted_hash = "{hook["currentHash"]}"\n\n')
    shutil.rmtree(home / '.cache' / 'ai-baton', ignore_errors=True)  # hook-status caches Codex's answer.
    status = json.loads(baton('hook-status', '--json', str(project)))
    check(status['codex']['state'] == 'ok' and status['claude']['state'] == 'ok', f'hook-status after approval: {status}')

    # Claude's checkpoint reaches a Codex conversation, and Codex's reaches a Claude conversation.
    claude_at = checkpoint('claude', 'Claude wrote the démo plan.')
    agent([codex, 'exec', '--skip-git-repo-check', 'say hi'], 'codex')
    delivered = [s for s in seen('codex').values() if s.get('claude') == claude_at]
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


def check(ok, message):
    if not ok:
        sys.exit(f'FAIL: {message}')


if __name__ == '__main__':
    main()
