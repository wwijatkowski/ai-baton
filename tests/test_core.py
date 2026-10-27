import io
import shutil
import os
from datetime import datetime, timezone
import json
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baton import changes, hook, hookcheck, init_project, models, project, recall, review, status  # noqa: E402
from baton.project import read_json  # noqa: E402

# Tests never read the real per-user registry (a hidden agent there would change what init does).
project.USER_AGENTS = Path(tempfile.gettempdir()) / 'ai-baton-tests-none' / 'agents.json'
# Nor the real user-level hooks (with them installed, init would skip project hooks).
init_project.user_home = lambda: Path(tempfile.gettempdir()) / 'ai-baton-tests-none' / 'home'
# Nor the real list of review sessions (Claude reviews record theirs).
models.REVIEW_SESSIONS = Path(tempfile.gettempdir()) / f'ai-baton-tests-reviews-{os.getpid()}.json'
# Nor which agents happen to be installed here: tests assume both are.
init_project.agent_binary = lambda kind: f'/usr/bin/{kind}'


WINDOWS = os.name == 'nt'


def rmtree(path):
    """shutil.rmtree that also removes read-only files (git objects), which Windows refuses to delete otherwise."""
    def retry(func, name, _):
        os.chmod(name, 0o700)
        func(name)
    shutil.rmtree(path, onerror=retry)


def fake_tool(folder, name, code):
    """A stand-in command that runs the Python `code`: an executable script, or on Windows a .cmd wrapper (the form
    npm installs agents in). Returns its path."""
    script = folder / f'{name}.py'
    script.write_text('import sys\nsys.stdout.reconfigure(encoding="utf-8")\n' + code, encoding='utf-8')
    if WINDOWS:
        tool = folder / f'{name}.cmd'
        tool.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        tool = folder / name
        tool.write_text(f'#!{sys.executable}\n' + script.read_text(encoding='utf-8'), encoding='utf-8')
        tool.chmod(0o755)
    return tool


def alive(pid):
    if WINDOWS:  # os.kill(pid, 0) would terminate the process on Windows.
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def payload(project, event, session='s1', **extra):
    # Claude Code sends transcript_path with every event (hook.foreign_call).
    return {'cwd': str(project), 'hook_event_name': event, 'session_id': session, 'transcript_path': '', **extra}


def context(result):
    return (result.get('hookSpecificOutput') or {}).get('additionalContext', '')


class InitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / 'demo'
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_files_and_is_idempotent(self):
        init_project.init(self.project)
        init_project.init(self.project)
        for rel in ('.baton.json', 'AGENTS.md', 'CLAUDE.md', 'docs/AGENT_HANDOFF.md',
                    'docs/STATUS.md', 'docs/knowledge/DECISIONS.md'):
            self.assertTrue((self.project / rel).is_file(), rel)
        self.assertEqual((self.project / 'AGENTS.md').read_text().count('BEGIN AI-BATON'), 1)
        self.assertEqual((self.project / '.gitignore').read_text().count('.agent-memory/'), 1)
        for rel in ('.claude/settings.json', '.codex/hooks.json'):
            hooks = read_json(self.project / rel)['hooks']
            self.assertEqual(sorted(hooks), ['SessionStart', 'Stop', 'UserPromptSubmit'])
            self.assertEqual(len(hooks['Stop']), 1)

    def test_keeps_existing_content_and_other_hooks(self):
        (self.project / 'AGENTS.md').write_text('# My rules\n')
        (self.project / '.claude').mkdir()
        other = {'hooks': [{'type': 'command', 'command': 'echo lint'}]}
        (self.project / '.claude/settings.json').write_text(json.dumps({'model': 'x', 'hooks': {'Stop': [other]}}))
        init_project.init(self.project)
        self.assertTrue((self.project / 'AGENTS.md').read_text().startswith('# My rules'))
        settings = read_json(self.project / '.claude/settings.json')
        self.assertEqual(settings['model'], 'x')
        self.assertIn(other, settings['hooks']['Stop'])

    def test_refuses_legacy_hooks_without_flag(self):
        (self.project / '.codex').mkdir()
        legacy = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'python3 scripts/agent-memory.py codex'}]}]}}
        (self.project / '.codex/hooks.json').write_text(json.dumps(legacy))
        with self.assertRaises(init_project.InitError):
            init_project.init(self.project)
        self.assertFalse((self.project / '.baton.json').exists())
        init_project.init(self.project, replace_legacy=True)
        self.assertNotIn('agent-memory.py', (self.project / '.codex/hooks.json').read_text())


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / 'demo'
        self.project.mkdir()
        init_project.init(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ignores_uninitialized_folders(self):
        other = Path(self.tmp.name) / 'other'
        other.mkdir()
        self.assertEqual(hook.run('claude', payload(other, 'SessionStart')), {})

    def test_handoff_between_agents(self):
        self.assertIn('No checkpoint from another agent', context(hook.run('codex', payload(self.project, 'SessionStart', 'c1'))))
        hook.run('claude', payload(self.project, 'UserPromptSubmit', 'k1'))
        warning = context(hook.run('codex', payload(self.project, 'UserPromptSubmit', 'c1')))
        self.assertIn('agent claude may still be active', warning)

        hook.run('claude', payload(self.project / 'docs', 'Stop', 'k1',
                                   last_assistant_message='Did X.\napi_key=abc123'))
        saved = read_json(self.project / '.agent-memory/claude.json')
        self.assertIn('Did X', saved['last_reply'])
        self.assertNotIn('abc123', saved['last_reply'])

        first = context(hook.run('codex', payload(self.project, 'UserPromptSubmit', 'c1')))
        self.assertIn('Did X', first)
        self.assertNotIn('has been working', first)
        # Already delivered to this session: nothing more to inject.
        self.assertEqual(hook.run('codex', payload(self.project, 'UserPromptSubmit', 'c1')), {})
        # A new session gets it again.
        self.assertIn('Did X', context(hook.run('codex', payload(self.project, 'SessionStart', 'c2'))))

    def test_summary_cut_on_a_word_and_client_recorded(self):
        long = 'word ' * 200 + 'tail'
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_ENTRYPOINT': 'claude-desktop'}):
            hook.run('claude', payload(self.project, 'Stop', 's1', last_assistant_message=long))
        snap = read_json(self.project / '.agent-memory/claude.json')
        self.assertTrue(snap['summary'].endswith('word…'), snap['summary'][-20:])
        self.assertEqual(snap['client'], 'claude-desktop')
        transcript = self.project / 'rollout.jsonl'
        transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'originator': 'codex_vscode'}}) + '\n')
        # Codex started from inside Claude inherits Claude's variable; its own transcript still decides.
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_ENTRYPOINT': 'claude-vscode'}):
            hook.run('codex', payload(self.project, 'Stop', 'c1', last_assistant_message='hi', transcript_path=str(transcript)))
        self.assertEqual(read_json(self.project / '.agent-memory/codex.json')['client'], 'codex_vscode')
        self.assertEqual([e['client'] for e in status.recent_work(self.project / '.agent-memory')], ['codex_vscode', 'claude-desktop'])
        # A long Handoff block is cut on a word too, when saved and on the agent card.
        block = 'Done: ' + 'step ' * 600
        hook.run('claude', payload(self.project, 'Stop', 's2', last_assistant_message=f'Text.\n\n**Handoff:**\n{block}'))
        saved = read_json(self.project / '.agent-memory/claude.json')['summary']
        self.assertTrue(saved.endswith('step…'), saved[-15:])
        card = [a for a in status.project_status(self.project)['agents'] if a['id'] == 'claude'][0]['checkpoint']['summary']
        self.assertTrue(card.endswith('step…') and len(card) <= 600, card[-15:])

    def test_resumed_session_gets_checkpoints_again(self):
        hook.run('codex', payload(self.project, 'Stop', 'c1', last_assistant_message='Codex did Y.'))
        self.assertIn('Codex did Y', context(hook.run('claude', payload(self.project, 'SessionStart', 's1'))))
        self.assertNotIn('Codex did Y', context(hook.run('claude', payload(self.project, 'UserPromptSubmit', 's1', prompt='a'))))
        # Resume or compaction: same session id, fresh context window.
        again = context(hook.run('claude', payload(self.project, 'SessionStart', 's1', source='resume')))
        self.assertIn('Codex did Y', again)
        self.assertNotIn('No checkpoint from another agent', again)

    def test_own_checkpoint_reaches_the_agents_other_conversations(self):
        # One agent alone: a new chat continues from the previous one.
        hook.run('claude', payload(self.project, 'UserPromptSubmit', 's1', prompt='a'))
        hook.run('claude', payload(self.project, 'Stop', 's1', last_assistant_message='Claude built the login form.'))
        new_chat = context(hook.run('claude', payload(self.project, 'SessionStart', 's2')))
        self.assertIn('[claude, your other conversation]', new_chat)
        self.assertIn('Claude built the login form', new_chat)
        # The conversation that wrote it does not get it back, even after a resume.
        self.assertNotIn('login form', context(hook.run('claude', payload(self.project, 'SessionStart', 's1', source='resume'))))
        self.assertEqual(hook.run('claude', payload(self.project, 'UserPromptSubmit', 's1', prompt='b')), {})
        # A conversation running in parallel sees the other one's newer work on its next prompt, once.
        hook.run('claude', payload(self.project, 'Stop', 's1', last_assistant_message='Claude added validation.'))
        self.assertIn('added validation', context(hook.run('claude', payload(self.project, 'UserPromptSubmit', 's2', prompt='c'))))
        self.assertEqual(hook.run('claude', payload(self.project, 'UserPromptSubmit', 's2', prompt='d')), {})
        # Without a session id it cannot tell its own conversations apart: its own checkpoint stays out.
        self.assertNotIn('validation', context(hook.run('claude', payload(self.project, 'SessionStart'))))

    def test_copilot_running_claude_hooks_changes_nothing(self):
        # Copilot in VS Code runs Claude's hook files with its own payload (documented fields): it must not pass for
        # Claude, at any event.
        mem = self.project / '.agent-memory'
        before = sorted(p.name for p in mem.iterdir()) if mem.exists() else []
        for event, extra in (('SessionStart', {'source': 'new'}), ('UserPromptSubmit', {'prompt': 'hi'}),
                             ('Stop', {'transcript_path': '/t.jsonl', 'stop_reason': 'end_turn', 'stop_hook_active': False,
                                       'last_assistant_message': 'Copilot did X.'})):
            copilot = {'hook_event_name': event, 'session_id': 'cp1', 'cwd': str(self.project),
                       'timestamp': '2026-10-27T12:00:00Z', **extra}
            self.assertEqual(hook.run('claude', copilot), {})
        self.assertEqual(sorted(p.name for p in mem.iterdir()) if mem.exists() else [], before)
        self.assertFalse((mem / 'claude.json').exists())
        # Claude itself (transcript_path, no timestamp) still works.
        self.assertIn('This project uses AI Baton', context(hook.run('claude', payload(self.project, 'SessionStart'))))

    def test_claude_keeps_its_project_after_cd_into_another_repo(self):
        # The agent ran `cd` into a sibling repo: the payload cwd moved, the session start folder did not.
        sibling = Path(self.tmp.name) / 'app'
        sibling.mkdir()
        with mock.patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(self.project)}):
            hook.run('claude', payload(sibling, 'UserPromptSubmit', 'k1', prompt='go'))
            hook.run('claude', payload(sibling, 'Stop', 'k1', last_assistant_message='Fixed the app repo.'))
        self.assertIn('Fixed the app repo', read_json(self.project / '.agent-memory/claude.json')['summary'])
        activity = read_json(self.project / '.agent-memory/activity.json')['claude']['sessions']['k1']
        self.assertEqual(activity['state'], 'idle', 'no false "may still be active" afterwards')
        # Started outside any project but working in one: the payload cwd still counts. Other agents ignore the variable.
        with mock.patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(sibling)}):
            self.assertIn('This project uses AI Baton', context(hook.run('claude', payload(self.project, 'SessionStart', 'k2'))))
            self.assertEqual(hook.run('codex', payload(sibling, 'SessionStart', 'c1')), {})

    def test_foreign_call_signatures(self):
        # Claude Code's fields as captured from the real CLI (SessionStart, UserPromptSubmit) and as documented (Stop).
        claude = {
            'SessionStart': {'session_id': 's', 'transcript_path': '/t', 'cwd': '/p', 'hook_event_name': 'SessionStart',
                             'source': 'startup'},
            'UserPromptSubmit': {'session_id': 's', 'transcript_path': '/t', 'cwd': '/p', 'prompt_id': 'x',
                                 'permission_mode': 'default', 'hook_event_name': 'UserPromptSubmit', 'prompt': 'hi'},
            'Stop': {'session_id': 's', 'transcript_path': '/t', 'cwd': '/p', 'permission_mode': 'default',
                     'hook_event_name': 'Stop', 'stop_hook_active': False, 'last_assistant_message': 'Done.'},
        }
        for event, fields in claude.items():
            self.assertFalse(hook.foreign_call('claude', fields), event)
            # Copilot's documented payloads for the same events, with and without a transcript_path.
            copilot = {'hook_event_name': event, 'session_id': 's', 'cwd': '/p', 'timestamp': '2026-10-27T12:00:00Z'}
            self.assertTrue(hook.foreign_call('claude', copilot), event)
            self.assertTrue(hook.foreign_call('claude', {**copilot, 'transcript_path': '/t'}), event)
        self.assertFalse(hook.foreign_call('codex', {'hook_event_name': 'Stop'}), 'only Claude hook files are shared')

    def test_hook_context_says_turns_are_saved(self):
        text = context(hook.run('claude', payload(self.project, 'SessionStart')))
        self.assertIn(hook.SAVED_BY_HOOK.strip(), text)

    def test_empty_reply_keeps_previous_checkpoint(self):
        hook.run('codex', payload(self.project, 'Stop', last_assistant_message='First'))
        hook.run('codex', payload(self.project, 'Stop', last_assistant_message='  '))
        self.assertEqual(read_json(self.project / '.agent-memory/codex.json')['last_reply'], 'First')

    def test_cli_hook_never_fails(self):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/baton'), 'hook', 'claude'],
                                input='not json', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '{}')

    def test_hook_with_an_empty_environment(self):
        # Codex starts Windows hooks with a cleared environment (no USERPROFILE, PATH, SYSTEMROOT): still a checkpoint.
        # One unrelated variable: Python 3.9 on Windows cannot start a process with an entirely empty block.
        result = subprocess.run([sys.executable, str(ROOT / 'bin/baton'), 'hook', 'codex'], env={'BATON_TEST': '1'},
                                input=json.dumps(payload(self.project, 'Stop', 'bare', last_assistant_message='Done bare.')),
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '{}', result.stderr)
        self.assertEqual(read_json(self.project / '.agent-memory/codex.json')['last_reply'], 'Done bare.')


class MemoryTiersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / 'demo'
        self.project.mkdir()
        init_project.init(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def stop(self, agent, message, session='s1'):
        hook.run(agent, payload(self.project, 'Stop', session, last_assistant_message=message))
        return read_json(self.project / f'.agent-memory/{agent}.json')

    def test_handoff_block_is_the_summary(self):
        self.stop('claude', 'Long explanation nobody needs later.\n\n**Handoff:**\n- Done: login form\n- Next: tests')
        text = context(hook.run('codex', payload(self.project, 'SessionStart', 'c1')))
        self.assertIn('Done: login form', text)
        self.assertNotIn('Long explanation', text)
        self.assertIn('recall', text)

    def turn(self, agent, message, edit_handoff=False, session='s1'):
        hook.run(agent, payload(self.project, 'UserPromptSubmit', session, prompt='go'))
        if edit_handoff:
            (self.project / 'docs/AGENT_HANDOFF.md').write_text(f'# Agent handoff\nState from {agent}.\n')
        return self.stop(agent, message, session)

    def test_flags_handoff_doc_updates(self):
        # Written by init or by another agent before this turn: not this agent's update.
        self.assertFalse(self.turn('claude', 'First.')['handoff_updated'])
        self.assertFalse(self.turn('codex', 'Just read it.', session='c0')['handoff_updated'])
        self.assertTrue(self.turn('claude', 'Updated the handoff.', edit_handoff=True)['handoff_updated'])
        self.assertFalse(self.turn('codex', 'Reviewed, no edits.', session='c0')['handoff_updated'])
        text = context(hook.run('codex', payload(self.project, 'SessionStart', 'c1')))
        self.assertIn('updated docs/AGENT_HANDOFF.md', text)

    def test_user_and_project_hooks_run_once(self):
        home = Path(self.tmp.name) / 'home'
        with mock.patch.object(init_project, 'user_home', return_value=home):
            init_project.install_user_hooks()
            self.assertIn('--global', (home / '.claude/settings.json').read_text())
            # This project has its own hooks, so the user-level copy steps aside.
            stop = payload(self.project, 'Stop', 's1', last_assistant_message='Done once.')
            hook.run('claude', stop)
            self.assertEqual(hook.run('claude', stop, user_level=True), {})
            history = (self.project / '.agent-memory/history.jsonl').read_text().splitlines()
            self.assertEqual(sum('Done once.' in line for line in history), 1)
            # Still once when the agent is hidden from the panel.
            with mock.patch.object(project, 'USER_AGENTS', Path(self.tmp.name) / 'agents.json'):
                project.remove_agent('claude')
                self.assertEqual(hook.run('claude', stop, user_level=True), {})
            # A partial user-level set does not replace project hooks.
            settings = read_json(home / '.claude/settings.json')
            del settings['hooks']['SessionStart']
            (home / '.claude/settings.json').write_text(json.dumps(settings))
            self.assertFalse(init_project.has_baton_hooks(home, 'claude'))
            (home / '.claude/settings.json').unlink()
            init_project.install_user_hooks()
            # A quick repeat is a real turn, not a duplicate.
            hook.run('claude', stop)
            history = (self.project / '.agent-memory/history.jsonl').read_text().splitlines()
            self.assertEqual(sum('Done once.' in line for line in history), 2)
            # Codex is not installed here: a new project gets no .codex/, whatever the user-level hooks say.
            claude_only = Path(self.tmp.name) / 'claude-only'
            claude_only.mkdir()
            (home / '.codex/hooks.json').unlink()
            with mock.patch.object(init_project, 'agent_binary', lambda kind: '/usr/bin/claude' if kind == 'claude' else None):
                log = init_project.init(claude_only)
            self.assertFalse((claude_only / '.codex').exists())
            self.assertTrue(any('codex: not found on this computer' in line for line in log))
            init_project.install_user_hooks()
            # New projects get no project hooks; there the user-level hook does the work.
            fresh = Path(self.tmp.name) / 'fresh'
            fresh.mkdir()
            init_project.init(fresh)
            self.assertFalse((fresh / '.claude').exists())
            hook.run('claude', payload(fresh, 'Stop', 's2', last_assistant_message='Global works.'), user_level=True)
            self.assertEqual(read_json(fresh / '.agent-memory/claude.json')['summary'], 'Global works.')

    def test_working_ends_with_the_turn_in_the_transcript(self):
        transcript = self.project / 'rollout.jsonl'
        marker = lambda kind, ts: json.dumps({'timestamp': ts, 'type': 'event_msg', 'payload': {'type': kind}}) + '\n'
        # An earlier turn ended before this prompt (resumed session): that must not hide the new turn.
        transcript.write_text(marker('task_complete', '2020-01-01T00:00:00.000Z'))
        hook.run('codex', payload(self.project, 'UserPromptSubmit', 'c1', prompt='review', transcript_path=str(transcript)))
        busy = lambda: context(hook.run('claude', payload(self.project, 'UserPromptSubmit', 's1', prompt='hi')))
        self.assertIn('WARNING: agent codex may still be active', busy())
        with transcript.open('a') as stream:
            stream.write(marker('task_started', '2099-01-01T00:00:00Z'))
            stream.write('not json\n{"type":"event_msg","payload":[1]}\n')
        self.assertIn('WARNING', busy())
        # The turn ends without a Stop hook (`codex exec review`): idle at once.
        with transcript.open('a') as stream:
            stream.write(marker('turn_aborted', '2099-01-01T00:01:00Z'))
            stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'thread_settings_applied'}}) + '\n')
        self.assertNotIn('WARNING', busy())
        self.assertEqual(status.project_status(self.project)['agents'][1]['activity']['state'], 'idle')
        # A record that merely mentions event_msg is not a turn marker.
        hook.run('codex', payload(self.project, 'UserPromptSubmit', 'c2', prompt='again', transcript_path=str(transcript)))
        with transcript.open('a') as stream:
            stream.write(marker('task_started', '2099-01-02T00:00:00Z'))
            stream.write(json.dumps({'timestamp': '2099-01-02T00:00:01Z', 'type': 'response_item',
                                     'payload': {'type': 'task_complete', 'text': 'event_msg'}}) + '\n')
        self.assertIn('WARNING', busy())
        # A broken activity file never breaks the panel's status.
        (self.project / '.agent-memory/activity.json').write_text(json.dumps({'codex': ['bad']}))
        self.assertIsNone(status.project_status(self.project)['agents'][1]['activity'])

    def test_two_conversations_of_one_agent(self):
        prompt = lambda session: hook.run('claude', payload(self.project, 'UserPromptSubmit', session, prompt='go'))
        activity = lambda: read_json(self.project / '.agent-memory/activity.json')
        prompt('a')
        # A second Claude chat learns the first is still working, and the first one's state survives the second.
        self.assertIn('another claude conversation may still be active', context(prompt('b')))
        self.assertEqual(sorted(activity()['claude']['sessions']), ['a', 'b'])
        self.stop('claude', 'Finished in chat b.', session='b')
        claude = status.project_status(self.project)['agents'][0]
        self.assertEqual(claude['activity']['state'], 'working')  # Chat a still works.
        self.assertEqual(claude['activity']['session_id'], 'a')
        # The handoff doc counts as this chat's update only if edited after this chat's own turn began.
        (self.project / 'docs/AGENT_HANDOFF.md').write_text('# Handoff\nchat a was here\n')
        prompt('b')
        self.assertFalse(self.stop('claude', 'Chat b again.', session='b')['handoff_updated'])
        self.stop('claude', 'Finished in chat a.', session='a')
        self.assertEqual(status.project_status(self.project)['agents'][0]['activity']['state'], 'idle')
        self.assertNotIn('WARNING', context(prompt('c')) or '')
        # The older one-entry-per-agent format is read as that agent's only session.
        (self.project / '.agent-memory/activity.json').write_text(json.dumps(
            {'codex': {'state': 'working', 'at': datetime.now(timezone.utc).isoformat(), 'session_id': 'old'}}))
        self.assertEqual(status.project_status(self.project)['agents'][1]['activity']['state'], 'working')
        self.assertIn('agent codex may still be active', context(prompt('d')))
        hook.run('codex', payload(self.project, 'Stop', 'old', last_assistant_message='Done.'))
        self.assertEqual(sorted(activity()['codex']['sessions']), ['old'])
        # Many conversations: only the newest finished ones are kept, but one still working always stays.
        prompt('long')
        for i in range(hook.MAX_SESSIONS + 3):
            prompt(f'n{i}')
            self.stop('claude', 'Quick one.', session=f'n{i}')
        kept = activity()['claude']['sessions']
        self.assertIn('long', kept)
        self.assertNotIn('n0', kept)  # The oldest finished ones are dropped.
        self.assertIn(f'n{hook.MAX_SESSIONS + 2}', kept)
        self.assertLessEqual(sum(1 for e in kept.values() if e['state'] == 'idle'), hook.MAX_SESSIONS)
        self.assertEqual(status.project_status(self.project)['agents'][0]['activity']['session_id'], 'long')
        self.assertIn('another claude conversation', context(prompt('new')))
        # Times are compared as times: the same moment with an offset is not "newer" because of how it is written.
        from baton.project import agent_activity
        later = {'sessions': {'x': {'state': 'idle', 'at': '2026-01-01T10:30:00+02:00'},  # 08:30 UTC
                              'y': {'state': 'idle', 'at': '2026-01-01T09:00:00'}}}  # Naive means UTC.
        self.assertEqual(agent_activity(later)['at'], '2026-01-01T09:00:00')

    def test_parallel_hooks_keep_every_conversation(self):
        script = ('import sys; sys.path.insert(0, sys.argv[1]); from baton import hook; '
                  'hook.run("claude", {"cwd": sys.argv[2], "hook_event_name": "UserPromptSubmit", '
                  '"session_id": "p" + sys.argv[3], "prompt": "go", "transcript_path": ""})')
        procs = [subprocess.Popen([sys.executable, '-c', script, str(ROOT), str(self.project), str(i)]) for i in range(8)]
        for proc in procs:
            self.assertEqual(proc.wait(60), 0)
        sessions = read_json(self.project / '.agent-memory/activity.json')['claude']['sessions']
        self.assertEqual(sorted(sessions), sorted(f'p{i}' for i in range(8)))

    def test_is_working_survives_odd_entries(self):
        from baton.project import is_working
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()  # Naive: read as UTC.
        self.assertTrue(is_working({'state': 'working', 'at': recent}))
        self.assertTrue(is_working({'state': 'working', 'at': recent, 'transcript': str(self.project / 'missing')}))
        self.assertTrue(is_working({'state': 'working', 'at': recent, 'transcript': str(self.project)}))  # A folder.
        for odd in (None, [], {'state': 'working'}, {'state': 'working', 'at': 'yesterday'},
                    {'state': 'working', 'at': '2020-01-01T00:00:00+00:00'}, {'state': 'idle', 'at': recent}):
            self.assertFalse(is_working(odd), odd)

    def test_uninstall_hooks_keeps_other_hooks_and_settings(self):
        home = Path(self.tmp.name) / 'home'
        with mock.patch.object(init_project, 'user_home', return_value=home):
            init_project.install_user_hooks()
            settings = read_json(home / '.claude/settings.json')
            settings['model'] = 'opus'
            settings['hooks']['Stop'].append({'hooks': [{'type': 'command', 'command': 'echo lint'}]})
            (home / '.claude/settings.json').write_text(json.dumps(settings))
            log = init_project.uninstall_hooks(project=self.project)
            kept = read_json(home / '.claude/settings.json')
            self.assertEqual(kept['model'], 'opus')
            self.assertEqual(kept['hooks'], {'Stop': [{'hooks': [{'type': 'command', 'command': 'echo lint'}]}]})
            self.assertNotIn('hooks', read_json(home / '.codex/hooks.json'))
            self.assertFalse(init_project.has_baton_hooks(self.project, 'claude'))  # Project hooks gone too.
            self.assertTrue(any('removed 3' in line for line in log))
            self.assertEqual(init_project.uninstall_hooks(), [])  # Nothing left: nothing to do.
            # Look-alike commands of other tools are never touched, on install or uninstall.
            lookalikes = ['python3 /tools/baton-check.py hook validate', 'baton hook-runner --all', 'echo baton hook']
            (home / '.codex/hooks.json').write_text(json.dumps({'hooks': {'Stop': [{'hooks': [
                {'type': 'command', 'command': c} for c in lookalikes]}]}}))
            init_project.install_user_hooks()
            init_project.uninstall_hooks()
            left = [h['command'] for g in read_json(home / '.codex/hooks.json')['hooks']['Stop'] for h in g['hooks']]
            self.assertEqual(left, lookalikes)
            self.assertTrue(init_project.is_baton_hook("python3 '/odd $dir/bin/baton' hook claude --global", 'claude'))
            # An odd but valid file stops the run before anything is changed.
            init_project.install_user_hooks()
            before = (home / '.claude/settings.json').read_text()
            (home / '.codex/hooks.json').write_text('{"hooks": {"Stop": null}}')
            with self.assertRaises(init_project.InitError):
                init_project.uninstall_hooks()
            self.assertEqual((home / '.claude/settings.json').read_text(), before)

    def test_concurrent_checkpoints_keep_the_archive_readable(self):
        # Several agents stopping at the same moment once interleaved their gzip writes and broke the archive.
        script = (
            'import sys, json; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from baton import hook; '
            'hook.HISTORY_LIMIT = 3; mem = Path(sys.argv[2]); '
            '[hook.append_history(mem, {"agent": "a", "n": f"{sys.argv[3]}-{i}", "saved_at": "x"}) for i in range(15)]')
        mem = self.project / '.agent-memory'
        mem.mkdir(exist_ok=True)
        procs = [subprocess.Popen([sys.executable, '-c', script, str(ROOT), str(mem), str(w)]) for w in range(12)]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=60), 0)
        seen = [json.loads(line)['n'] for line in recall.entries(mem) if line.strip()]
        self.assertEqual(len(seen), 12 * 15)
        self.assertEqual(len(set(seen)), 12 * 15)

    def test_damaged_archive_is_skipped_not_fatal(self):
        import gzip
        mem = self.project / '.agent-memory'
        mem.mkdir(exist_ok=True)
        good = gzip.compress(b'{"agent": "a", "saved_at": "1", "summary": "before"}\n')
        later = gzip.compress(b'{"agent": "b", "saved_at": "3", "summary": "after"}\n')
        broken = gzip.compress(b'{"agent": "c"}\n' * 50)[:-30] + b'garbage'
        (mem / 'history.archive.jsonl.gz').write_bytes(good + broken + later)
        lines = list(recall.entries(mem))
        self.assertIn('before', ''.join(lines))
        self.assertIn('after', ''.join(lines))
        self.assertTrue(status.project_status(self.project)['initialized'])  # The panel's status still works.

    def test_recent_work_groups_replies_by_session(self):
        mem = self.project / '.agent-memory'
        mem.mkdir(exist_ok=True)
        rows = [{'agent': 'claude', 'session_id': 'a', 'saved_at': '1', 'summary': 'first'},
                {'agent': 'codex', 'session_id': 'b', 'saved_at': '2', 'summary': 'review'},
                {'agent': 'claude', 'session_id': 'a', 'saved_at': '3', 'summary': 'done', 'handoff_updated': True}]
        import gzip
        with gzip.open(mem / 'history.archive.jsonl.gz', 'wt') as stream:
            stream.write(json.dumps(rows[0]) + '\n')
        (mem / 'history.jsonl').write_text('\n'.join(map(json.dumps, rows[1:])) + '\nnot json\n')
        recent = status.recent_work(mem)
        self.assertEqual([(e['agent'], e['summary'], e['turns']) for e in recent], [('claude', 'done', 2), ('codex', 'review', 1)])
        self.assertTrue(recent[0]['handoff_updated'])
        self.assertEqual(status.clip('one two three', 9), 'one two…')
        self.assertEqual(status.clip('short', 9), 'short')
        self.assertEqual(status.clip('one twothree', 9), 'one…')
        self.assertEqual(status.clip('abcdefghijk', 5), 'abcd…')
        self.assertEqual(len(status.recent_work(mem, limit=1)), 1)
        self.assertEqual(len(status.project_recent(self.project)['sessions']), 2)

    def test_hot_tier_stays_within_budget(self):
        self.stop('claude', 'word ' * 5000)
        text = context(hook.run('codex', payload(self.project, 'SessionStart', 'c1')))
        self.assertLess(len(text), hook.HOT_BUDGET + 1500)
        self.assertEqual(len(read_json(self.project / '.agent-memory/claude.json')['last_reply']), 12000)

    def test_git_project_points_at_commit(self):
        run = lambda *a: subprocess.run(['git', *a], cwd=self.project, check=True, capture_output=True)
        run('init', '-q')
        rmtree(self.project / '.agent-memory' / changes.SHADOW_DIR)  # Init's baseline, taken before git existed.
        run('-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '-A')
        run('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'x')
        found = self.stop('claude', 'Done.')['changes']
        self.assertEqual(found['kind'], 'git')
        self.assertTrue(found['commit'])
        self.assertFalse((self.project / '.agent-memory' / changes.SHADOW_DIR).exists())

    def test_shadow_repo_without_git_project(self):
        (self.project / '.env').write_text('API=1')
        (self.project / 'app.py').write_text('print(1)')
        first = self.stop('claude', 'First.')['changes']
        self.assertEqual(first['kind'], 'shadow')
        self.assertIn('app.py', ' '.join(first['changed']))
        (self.project / 'app.py').write_text('print(2)')
        second = self.stop('codex', 'Second.')['changes']
        self.assertEqual(second['changed'], ['M app.py'])
        shadow = self.project / '.agent-memory' / changes.SHADOW_DIR
        tracked = changes.git(self.project, 'ls-files', git_dir=shadow)
        self.assertNotIn('.env', tracked.split())
        self.assertFalse((self.project / '.git').exists())

    def test_file_list_without_git(self):
        self.stop('claude', 'First.')
        (self.project / 'notes.txt').write_text('new')
        with mock.patch.object(changes.shutil, 'which', return_value=None):
            found = self.stop('codex', 'Second.')['changes']
        self.assertEqual(found['kind'], 'files')
        self.assertIn('M notes.txt', found['changed'])

    def test_recall_reaches_archived_checkpoints(self):
        with mock.patch.object(hook, 'HISTORY_LIMIT', 2):
            for i in range(5):
                self.stop('claude', f'Step {i} about payments' if i == 0 else f'Step {i}')
        self.assertTrue((self.project / '.agent-memory/history.archive.jsonl.gz').exists())
        hits = recall.search(self.project, ['payments'])
        self.assertEqual([h['last_reply'] for h in hits], ['Step 0 about payments'])
        self.assertEqual(len(recall.search(self.project, limit=10)), 5)
        self.assertIn('payments', recall.render(hits[0], ['payments'], False))


def copilot_events(user_text, *replies, partial=False, session='cp1'):
    """A Copilot events.jsonl as the runtime writes it (observed 2026-10-27, copilot-agent 1.0.100): `replies` are
    (phase, content, messageId) after the user's message."""
    events = [{'type': 'session.start', 'data': {'sessionId': session, 'producer': 'copilot-agent'}},
              {'type': 'user.message', 'data': {'content': user_text}},
              {'type': 'assistant.turn_start', 'data': {'turnId': '0'}}]
    events += [{'type': 'assistant.message', 'data': {'phase': phase, 'content': content, 'messageId': mid}}
               for phase, content, mid in replies]
    events.append({'type': 'assistant.turn_end', 'data': {'turnId': '0'}})
    text = ''.join(json.dumps(e) + '\n' for e in events)
    return text + ('{"type": "assistant.mess' if partial else '')


class CopilotHooksTest(unittest.TestCase):
    """Copilot's own hooks (~/.copilot/hooks/ai-baton.json): context at SessionStart, the reply read at Stop."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.project = base / 'demo'
        self.project.mkdir()
        init_project.init(self.project)
        self.home = base / 'copilot-home'
        self.registry = base / 'agents.json'
        self.registry.write_text(json.dumps({'agents': [{'id': 'copilot', 'label': 'Copilot', 'extension': 'GitHub.copilot-chat',
                                                         'openCommand': 'workbench.action.chat.open'}]}))
        for patch in (mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.home)}),
                      mock.patch.object(project, 'USER_AGENTS', self.registry),
                      mock.patch.object(init_project, 'user_home', return_value=base / 'home')):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop('COPILOT_PROJECT_DIR', None)

    def transcript(self, session, text):
        path = self.home / 'session-state' / session / 'events.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return str(path)

    def stop(self, session, path):
        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')  # Copilot's form.
        return hook.run('copilot', payload(self.project, 'Stop', session, transcript_path=path, timestamp=now,
                                           stop_reason='end_turn'), user_level=True)

    def test_install_status_and_uninstall(self):
        self.assertEqual([a.get('hooks') for a in project.load_agents() if a['id'] == 'copilot'], ['copilot'])
        self.assertEqual(hookcheck.status(self.project)['copilot']['state'], 'missing')
        init_project.install_user_hooks(None)  # Not named: Copilot has no CLI to detect, so it is left out.
        self.assertFalse(init_project.copilot_hook_file().exists())
        log = init_project.install_user_hooks({'copilot'})
        config = json.loads(init_project.copilot_hook_file().read_text())
        self.assertEqual(config['version'], 1)
        self.assertEqual(sorted(config['hooks']), sorted(init_project.EVENTS))
        entry = config['hooks']['Stop'][0]
        self.assertTrue(entry['command'].endswith(' hook copilot --global'), entry)
        self.assertEqual(entry['timeoutSec'], 10)
        self.assertIn('ai-baton.json', log[0])
        self.assertEqual(hookcheck.status(self.project)['copilot'], {'state': 'ok', 'detail': 'installed (user)'})
        self.assertEqual(hookcheck.user_status()['copilot']['state'], 'ok')
        self.assertFalse((self.project / '.github').exists())  # Never in a project.
        init_project.uninstall_hooks({'copilot'})
        self.assertFalse(init_project.copilot_hook_file().exists())
        self.assertTrue(init_project.copilot_hook_file().parent.exists())  # Copilot's folder stays.

    def test_only_the_real_copilot_entry_gets_hooks(self):
        self.registry.write_text(json.dumps({'agents': [
            {'id': 'copilot', 'label': 'Copilot', 'extension': 'someone.else', 'openCommand': 'x'},
            {'id': 'other', 'label': 'Other', 'extension': 'github.copilot-chat', 'openCommand': 'x'}]}))
        self.assertFalse([a for a in project.load_agents() if a.get('hooks') == 'copilot'])
        self.registry.write_text(json.dumps({'agents': []}))
        marker = self.project / project.MARKER
        data = json.loads(marker.read_text())
        data['extraAgents'] = [{'id': 'copilot', 'label': 'C', 'extension': 'github.copilot-chat', 'openCommand': 'x'}]
        marker.write_text(json.dumps(data))
        self.assertFalse([a for a in project.load_agents(self.project) if a.get('hooks') == 'copilot'])  # Not from a repo.

    def test_context_at_session_start_and_reply_saved_at_stop(self):
        hook.run('codex', payload(self.project, 'Stop', 'c1', last_assistant_message='Codex fixed the parser.'))
        start = hook.run('copilot', payload(self.project, 'SessionStart', 'cp1', timestamp='t', source='new'), user_level=True)
        self.assertEqual(list(start), ['additionalContext'])  # The Copilot runtime's documented output.
        self.assertIn('Codex fixed the parser.', start['additionalContext'])
        self.assertIn('Your AI Baton session_id: cp1', start['additionalContext'])
        self.assertIn('saved by AI Baton', start['additionalContext'])
        # Copilot drops this output: it only marks the turn, it must not mark checkpoints as seen.
        seen = (self.project / '.agent-memory' / 'seen.json').read_text()
        hook.run('codex', payload(self.project, 'Stop', 'c1', last_assistant_message='Codex added tests.'))
        self.assertEqual(hook.run('copilot', payload(self.project, 'UserPromptSubmit', 'cp1', timestamp='t'), user_level=True), {})
        self.assertEqual((self.project / '.agent-memory' / 'seen.json').read_text(), seen)
        activity = read_json(self.project / '.agent-memory' / 'activity.json')
        self.assertEqual(activity['copilot']['sessions']['cp1']['state'], 'working')
        again = hook.run('copilot', payload(self.project, 'SessionStart', 'cp1', timestamp='t'), user_level=True)
        self.assertIn('Codex added tests.', again['additionalContext'])  # SessionStart always delivers everything.

        path = self.transcript('cp1', copilot_events('fix it', ('commentary', 'Looking at the code.', 'm1'),
                                                     ('final_answer', 'Fixed the bug in parser.py.', 'm2'), partial=True))
        self.assertEqual(self.stop('cp1', path), {})
        snap = read_json(self.project / '.agent-memory' / 'copilot.json')
        self.assertEqual((snap['last_reply'], snap['message_id'], snap['client'], snap['session_id']),
                         ('Fixed the bug in parser.py.', 'm2', 'copilot-agent', 'cp1'))
        self.assertEqual(read_json(self.project / '.agent-memory' / 'activity.json')['copilot']['sessions']['cp1']['state'], 'idle')
        history = (self.project / '.agent-memory' / 'history.jsonl').read_text().splitlines()
        self.stop('cp1', path)  # The same Stop again: nothing new.
        self.assertEqual((self.project / '.agent-memory' / 'history.jsonl').read_text().splitlines(), history)
        self.assertIn('Fixed the bug in parser.py.', context(hook.run('codex', payload(self.project, 'SessionStart', 'c2'))))

    def test_unsure_transcripts_save_nothing(self):
        done = ('final_answer', 'Done.', 'm1')
        lines = lambda text: text.splitlines(keepends=True)
        good = lines(copilot_events('x', ('commentary', 'Working.', 'm0'), done, session='s'))
        bad_user = json.dumps({'type': 'user.message', 'data': None}) + '\n'
        cases = {
            'commentary only': copilot_events('x', ('commentary', 'Working on it.', 'm1'), session='s'),
            'no user message in it': ''.join(good[:1] + good[3:]),
            'not JSON': 'garbage\n',
            'damaged current user message': ''.join(good + [bad_user] + good[3:]),
            'damaged line inside the turn': ''.join(good[:3] + ['{"type": "assistant.mes\n'] + good[3:]),
            'damaged last record': ''.join(good) + '{"type": "user.mess\n',  # Complete (newline-ended), so not still being written.
            'header of another conversation': copilot_events('x', done, session='other'),
            'newer final without content': copilot_events('x', done, ('final_answer', None, 'm2'), session='s'),
            'newer final without messageId': copilot_events('x', done, ('final_answer', 'Later.', None), session='s'),
        }
        for name, text in cases.items():
            self.assertIsNone(hook.copilot_reply(self.transcript('s', text), 's'), name)
            self.assertEqual(self.stop('s', self.transcript('s', text)), {}, name)
        outside = Path(self.tmp.name) / 'events.jsonl'
        outside.write_text(copilot_events('x', ('final_answer', 'Done.', 'm1')))
        self.stop('s-out', str(outside))
        self.assertIsNone(hook.copilot_reply(str(outside)))
        if not WINDOWS:
            link = self.home / 'session-state' / 'link' / 'events.jsonl'
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)
            self.assertIsNone(hook.copilot_reply(str(link)))  # Resolves outside Copilot's folder.
        self.assertFalse((self.project / '.agent-memory' / 'copilot.json').exists())
        # A turn with a final answer later still saves.
        self.stop('s-ok', self.transcript('s-ok', copilot_events('x', ('final_answer', 'Done.', 'm9'), session='s-ok')))
        self.assertEqual(read_json(self.project / '.agent-memory' / 'copilot.json')['last_reply'], 'Done.')

    def test_long_transcript_reads_only_the_end(self):
        old = copilot_events('old', ('final_answer', 'Old answer.', 'm0'))
        filler = json.dumps({'type': 'session.usage_record', 'data': {'pad': 'x' * 1000}}) + '\n'
        text = old + filler * (hook.COPILOT_TAIL // len(filler) + 5) + copilot_events('new', ('final_answer', 'New answer.', 'm1'))
        self.assertEqual(hook.copilot_reply(self.transcript('long', text), 'cp1')['reply'], 'New answer.')
        # The turn's user message fell out of the tail: unsure, so nothing.
        text = copilot_events('new', ('commentary', 'x', 'm0')).rsplit('\n', 2)[0] + '\n' + filler * (hook.COPILOT_TAIL // len(filler) + 5)
        text += json.dumps({'type': 'assistant.message', 'data': {'phase': 'final_answer', 'content': 'Late.', 'messageId': 'm5'}}) + '\n'
        self.assertIsNone(hook.copilot_reply(self.transcript('long2', text), 'cp1'))

    def test_project_folder_from_copilot(self):
        other = Path(self.tmp.name) / 'sibling'
        other.mkdir()
        with mock.patch.dict(os.environ, {'COPILOT_PROJECT_DIR': str(self.project)}):
            start = hook.run('copilot', payload(other, 'SessionStart', 'cp1', timestamp='t'), user_level=True)
        self.assertIn('AI Baton', start['additionalContext'])

    def test_memory_tools_defer_to_hooks_that_ran(self):
        from baton import mcp
        server = mcp.Server('copilot')
        init_project.install_user_hooks({'copilot'})
        # Installed is not proof: a chat without the hook's session_id is asked to save.
        self.assertIn('call baton_checkpoint with it', server.baton_context({'project_path': str(self.project)}))
        self.assertIn('call baton_checkpoint with it', server.baton_context({'project_path': str(self.project), 'session_id': 'cp1'}))
        hook.run('copilot', payload(self.project, 'UserPromptSubmit', 'cp1', timestamp='t'), user_level=True)
        text = server.baton_context({'project_path': str(self.project), 'session_id': 'cp1'})
        self.assertNotIn('call baton_checkpoint with it', text)
        self.assertIn('saved by AI Baton', text)
        # Its own checkpoint through the tool keeps the hook mark.
        server.baton_checkpoint({'project_path': str(self.project), 'session_id': 'cp1', 'summary': 'Saved by hand.'})
        self.assertTrue(hook.hook_ran(self.project / '.agent-memory', 'copilot', 'cp1'))

    def test_a_stop_saves_once_per_reply_in_each_conversation(self):
        a = self.transcript('A', copilot_events('a', ('final_answer', 'Answer A.', 'mA'), session='A'))
        b = self.transcript('B', copilot_events('b', ('final_answer', 'Answer B.', 'mB'), session='B'))
        history = lambda: (self.project / '.agent-memory' / 'history.jsonl').read_text().count('"agent": "copilot"')
        self.stop('A', a)
        self.stop('B', b)
        self.stop('A', a)  # A late repeat of A's Stop must not put A's old answer over B's.
        self.assertEqual(history(), 2)
        self.assertEqual(read_json(self.project / '.agent-memory' / 'copilot.json')['last_reply'], 'Answer B.')
        for n in range(hook.MAX_SESSIONS + 2):  # Activity forgets older conversations; the receipts do not.
            self.stop(f'x{n}', self.transcript(f'x{n}', copilot_events('x', ('final_answer', f'X{n}.', f'mx{n}'), session=f'x{n}')))
        self.stop('A', a)
        self.assertEqual(history(), 2 + hook.MAX_SESSIONS + 2)
        # A late Stop reads the transcript as it is now, inside the lock: it never saves an older reply over a newer one.
        late = self.transcript('L', copilot_events('l', ('final_answer', 'Old L.', 'mL1'), session='L'))
        self.stop('L', late)
        Path(late).write_text(copilot_events('l', ('final_answer', 'Old L.', 'mL1'), session='L') +
                              copilot_events('l2', ('final_answer', 'New L.', 'mL2'), session='L').split('\n', 1)[1])
        self.stop('L', late)
        self.stop('L', late)
        self.assertEqual(read_json(self.project / '.agent-memory' / 'copilot.json')['last_reply'], 'New L.')
        base = history()
        import threading
        c = self.transcript('C', copilot_events('c', ('final_answer', 'Answer C.', 'mC'), session='C'))
        threads = [threading.Thread(target=self.stop, args=('C', c)) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(history(), base + 1)

    def test_a_stop_waiting_for_the_lock_reads_the_newest_reply(self):
        # The first Stop is held before the lock while a second one saves a newer reply; released, it must not put
        # the older reply back (it reads the transcript inside the lock).
        import threading
        path = self.transcript('R', copilot_events('r', ('final_answer', 'Old R.', 'mR1'), session='R'))
        real_lock, held, go = hook.file_lock, threading.Event(), threading.Event()

        def gated(lock):
            if threading.current_thread().name == 'first':
                held.set()
                go.wait(10)
            return real_lock(lock)

        errors = []

        def first():
            try:
                self.stop('R', path)
            except Exception as error:  # Reported below: a failing thread must fail the test.
                errors.append(error)

        with mock.patch.object(hook, 'file_lock', gated):
            worker = threading.Thread(target=first, name='first')
            worker.start()
            self.assertTrue(held.wait(10))
            Path(path).write_text(copilot_events('r', ('final_answer', 'Old R.', 'mR1'), session='R') +
                                  copilot_events('r2', ('final_answer', 'New R.', 'mR2'), session='R').split('\n', 1)[1])
            self.stop('R', path)
            go.set()
            worker.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(read_json(self.project / '.agent-memory' / 'copilot.json')['last_reply'], 'New R.')
        self.assertEqual((self.project / '.agent-memory' / 'history.jsonl').read_text().count('"message_id": "mR2"'), 1)

    def test_a_late_stop_leaves_the_next_turn_working(self):
        path = self.transcript('W', copilot_events('w', ('commentary', 'Still going.', 'm1'), session='W'))
        hook.run('copilot', payload(self.project, 'UserPromptSubmit', 'W', timestamp='t'), user_level=True)
        state = lambda: read_json(self.project / '.agent-memory' / 'activity.json')['copilot']['sessions']['W']['state']
        hook.run('copilot', payload(self.project, 'Stop', 'W', transcript_path=path, timestamp='2020-01-01T00:00:00.000Z'),
                 user_level=True)  # Fired before this turn started.
        self.assertEqual(state(), 'working')
        self.stop('W', path)  # Fired now, after the turn started.
        self.assertEqual(state(), 'idle')

    def test_odd_hook_files_and_uninstall_without_the_agent(self):
        init_project.copilot_hook_file().parent.mkdir(parents=True)
        for text in ('{"hooks": ["unexpected"]}', '[]', '{"version": 2, "hooks": {}}', 'not json'):
            init_project.copilot_hook_file().write_text(text)
            self.assertEqual(hookcheck.status(self.project)['copilot']['state'], 'missing', text)
        init_project.install_user_hooks({'copilot'})
        self.registry.write_text(json.dumps({'agents': []}))  # Copilot removed from the panel.
        self.assertTrue(init_project.uninstall_hooks({'copilot'}))
        self.assertFalse(init_project.copilot_hook_file().exists())


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        (home / '.codex').mkdir()
        self.toml = home / '.codex/config.toml'
        self.toml.write_text('service_tier = "default"\n\n[projects."/x"]\nmodel = "not-top-level"\n')
        self.toml.chmod(0o600)
        (home / '.codex/models_cache.json').write_text(json.dumps({'models': [
            {'slug': 'gpt-b', 'display_name': 'B', 'visibility': 'list', 'priority': 2,
             'supported_reasoning_levels': [{'effort': 'low'}, {'effort': 'high'}]},
            {'slug': 'gpt-a', 'display_name': 'A', 'visibility': 'list', 'priority': 1,
             'supported_reasoning_levels': [{'effort': 'medium'}]},
            {'slug': 'hidden', 'visibility': 'hide'}]}))
        self.settings = home / '.claude/settings.json'
        self.patches = [mock.patch.multiple(models, CLAUDE_SETTINGS=self.settings, CLAUDE_STATE=home / '.claude.json',
                                            CODEX_CONFIG=self.toml, CODEX_MODELS=home / '.codex/models_cache.json')]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_codex_lists_models_and_keeps_config_intact(self):
        info = models.codex()
        self.assertEqual([o['value'] for o in info['options']], ['gpt-a', 'gpt-b'])
        self.assertEqual(info['model'], '')
        models.set_model('codex', 'gpt-b', 'high')
        text = self.toml.read_text()
        self.assertTrue(text.startswith('model_reasoning_effort = "high"\nmodel = "gpt-b"\n'))
        self.assertIn('model = "not-top-level"', text)
        if not WINDOWS:  # No Unix mode bits there.
            self.assertEqual(self.toml.stat().st_mode & 0o777, 0o600)
        self.assertEqual((models.codex()['model'], models.codex()['effort']), ('gpt-b', 'high'))
        models.set_model('codex', 'default', 'default')
        self.assertEqual(self.toml.read_text(), 'service_tier = "default"\n\n[projects."/x"]\nmodel = "not-top-level"\n')

    def test_claude_settings_keep_other_keys(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({'permissions': {'allow': ['Bash(ls)']}}))
        models.set_model('claude', 'opus', 'high')
        saved = read_json(self.settings)
        self.assertEqual((saved['model'], saved['effortLevel']), ('opus', 'high'))
        self.assertEqual(saved['permissions'], {'allow': ['Bash(ls)']})
        models.set_model('claude', None, 'default')
        self.assertNotIn('effortLevel', read_json(self.settings))
        self.assertEqual(read_json(self.settings)['model'], 'opus')

    def test_cli_set_model_json(self):
        from baton import cli
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            cli.main(['set-model', 'codex', '--model', 'gpt-b', '--json'])
        info = json.loads(out.getvalue())['codex']
        self.assertEqual((info['model'], info['defaultLabel'], info['defaultEffort']), ('gpt-b', 'A', ''))

    def test_claude_default_is_last_used_model(self):
        log = Path(self.tmp.name) / '.claude/projects/p/s.jsonl'
        log.parent.mkdir(parents=True)
        log.write_text('{"message":{"model":"claude-opus-5-5"}}\n')
        with mock.patch.object(models, 'CLAUDE_PROJECTS', log.parents[1]):
            self.assertEqual(models.claude()['defaultLabel'], 'last used: Opus 5.5')
            # A newer transcript from a `baton review` run does not count; its tokens still do (usage reads it).
            with mock.patch.object(models, 'REVIEW_SESSIONS', Path(self.tmp.name) / 'reviews.json'):
                review_log = log.parent / '0f8e7c1a-3b2d-4e5f-8a9b-0c1d2e3f4a5b.jsonl'
                review_log.write_text('{"message":{"model":"claude-haiku-5-5"}}\n')
                os.utime(review_log, (time.time() + 60, time.time() + 60))
                self.assertEqual(models.claude()['defaultLabel'], 'last used: Haiku 5.5')
                models.add_review_session(review_log.stem)
                self.assertEqual(models.claude()['defaultLabel'], 'last used: Opus 5.5')
                import threading
                ids = [f'r{n}' for n in range(8)]
                threads = [threading.Thread(target=models.add_review_session, args=(i,)) for i in ids]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                self.assertTrue(set(ids) <= set(models.review_sessions()))  # None lost to a parallel review.

    def test_rejects_bad_values_and_broken_files(self):
        with self.assertRaises(models.ModelError):
            models.set_model('claude', 'opus', 'turbo')
        with self.assertRaises(models.ModelError):
            models.set_model('codex', 'x" \n[evil]', None)
        self.settings.parent.mkdir()
        self.settings.write_text('{broken')
        with self.assertRaises(models.ModelError):
            models.set_model('claude', 'opus', None)
        self.assertEqual(self.settings.read_text(), '{broken')


class AgentRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / 'ai-baton/agents.json'
        self.patch = mock.patch.object(project, 'USER_AGENTS', self.file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_add_replace_and_remove(self):
        cline = {'id': 'cline', 'label': 'Cline', 'extension': 'saoudrizwan.claude-dev',
                 'openCommand': 'workbench.view.extension.claude-dev-ActivityBar', 'hooks': 'claude'}
        project.add_agent(cline)
        project.add_agent({**cline, 'label': 'Cline 2'})
        added = [a for a in project.load_agents() if a['id'] == 'cline']
        self.assertEqual(len(added), 1)
        # Launch settings only: a user-added agent cannot claim another agent's hooks.
        self.assertEqual((added[0]['label'], added[0]['source'], added[0].get('hooks')), ('Cline 2', 'user', None))
        project.remove_agent('cline')
        self.assertNotIn('cline', [a['id'] for a in project.load_agents()])

    def test_hide_and_show_builtin(self):
        project.remove_agent('codex')
        self.assertEqual([a['id'] for a in project.load_agents()], ['claude'])
        self.assertEqual([a['id'] for a in project.load_agents(hidden=True)], ['codex'])
        # Re-adding restores the built-in entry, ignoring anything else passed in.
        self.assertEqual(project.add_agent({'id': 'codex', 'hooks': 'evil'})['hooks'], 'codex')
        self.assertEqual([a['id'] for a in project.load_agents()], ['claude', 'codex'])

    def test_reads_older_list_format(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text(json.dumps([{'id': 'cody', 'label': 'Cody', 'openCommand': 'x'}]))
        self.assertIn('cody', [a['id'] for a in project.load_agents()])

    def test_hidden_agent_checkpoints_still_reach_others(self):
        root = Path(self.tmp.name) / 'p'
        root.mkdir()
        init_project.init(root)
        (root / '.agent-memory').mkdir(exist_ok=True)
        (root / '.agent-memory/codex.json').write_text(json.dumps({'agent': 'codex', 'saved_at': 'x', 'summary': 's'}))
        project.remove_agent('codex')
        self.assertEqual([s['agent'] for s in hook.other_snapshots(root / '.agent-memory', 'claude', root)], ['codex'])

    def test_init_only_installs_chosen_hooks(self):
        root = Path(self.tmp.name) / 'p'
        root.mkdir()
        init_project.init(root, only={'claude'})
        self.assertTrue((root / '.claude/settings.json').is_file())
        self.assertFalse((root / '.codex').exists())

    def test_rejects_bad_agents(self):
        for bad in ({'id': 'Bad Id', 'label': 'X', 'openCommand': 'x'}, {'id': 'ok', 'label': 'X'}):
            with self.assertRaises(project.AgentError):
                project.add_agent(bad)
        with self.assertRaises(project.AgentError):
            project.remove_agent('nobody')
        self.assertFalse(self.file.exists())

    def test_cli_add_agent(self):
        from baton import cli
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            cli.main(['add-agent', json.dumps({'id': 'copilot', 'label': 'Copilot', 'openCommand': 'workbench.action.chat.open'})])
        self.assertEqual(json.loads(out.getvalue())['id'], 'copilot')
        with self.assertRaises(SystemExit):
            cli.main(['add-agent', '[1]'])




class ReviewTest(unittest.TestCase):
    """`baton review` with stand-in agent CLIs (no model calls)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / 'demo'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=self.project, check=True)
        subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', 'init'],
                       cwd=self.project, check=True)
        init_project.init(self.project)
        self.bin = Path(self.tmp.name) / 'bin'
        self.bin.mkdir()
        # Fake Codex: writes the prompt and stdin it got into the -o file. Fake Claude: prints them.
        self.tools = {}
        self.fake('codex', "import os\nargs = sys.argv[1:]\nout = open(args[args.index('-o') + 1], 'w', encoding='utf-8')\n"
                           "out.write('codex args: ' + ' '.join(args) + '\\ncodex saw: ' + args[-1] + '\\nenv: ' + "
                           "os.environ.get('BATON_REVIEW', '') + '\\n')\n"
                           "out.write(sys.stdin.buffer.read().decode('utf-8'))\n")
        self.fake('claude', "import os\nprint('claude args: ' + ' '.join(sys.argv[1:]))\n"
                            "print('env: ' + os.environ.get('BATON_REVIEW', ''))\n"
                            "print(sys.stdin.buffer.read().decode('utf-8'))\n")
        self.patch = mock.patch.object(review, 'binary', lambda kind: str(self.tools[kind]))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def fake(self, name, code):
        self.tools[name] = fake_tool(self.bin, name, code)

    def test_reviews_uncommitted_changes_including_new_files(self):
        (self.project / 'NEW.md').write_text('brand new line\n')
        result = review.review(self.project, 'codex', 'add a note')
        self.assertEqual(result['reviewed'], 'the uncommitted changes')
        self.assertIn('Goal of the change: add a note', result['review'])
        self.assertIn('at least 3 points ranked', result['review'])
        self.assertIn('brand new line', result['review'])
        # Without a stated goal the reviewer gets the authors' own notes; a focus is passed on as asked.
        hook.run('claude', payload(self.project, 'Stop', 's1', last_assistant_message='Made the README friendlier.'))
        noted = review.review(self.project, 'codex', focus='tone')['review']
        self.assertIn('Made the README friendlier', noted)
        self.assertIn('Recently done', noted)
        self.assertIn('pay special attention to: tone', noted)
        self.assertIn("take it from the authors' notes", noted)
        # A chosen session's own summary wins over the newest checkpoint of another session.
        hook.run('codex', payload(self.project, 'Stop', 'c9', last_assistant_message='Codex tidied the tests.'))
        chosen = review.review(self.project, 'codex', session='s1')['review']
        self.assertIn('Made the README friendlier', chosen)
        self.assertNotIn('Codex tidied the tests', chosen)
        claude = review.review(self.project, 'claude')['review']
        # Read-only by construction, and flagged so the reviewer's own hooks stay out of shared memory.
        self.assertIn('--tools Read,Grep,Glob', claude)
        self.assertRegex(claude, r'--session-id [0-9a-f-]{36}')  # Recorded, so it never sets the last used model.
        self.assertIn('--sandbox read-only', result['review'])
        self.assertIn('env: 1', claude)
        self.assertIn('env: 1', result['review'])
        codex_file = self.project / '.agent-memory/codex.json'
        before = codex_file.read_text() if codex_file.exists() else None
        with mock.patch.dict(os.environ, {'BATON_REVIEW': '1'}):
            self.assertEqual(hook.run('codex', payload(self.project, 'Stop', 'r1', last_assistant_message='A review.')), {})
        self.assertEqual(codex_file.read_text() if codex_file.exists() else None, before)

    def test_reviewer_model_and_effort_for_one_run(self):
        offered = {'efforts': ['low', 'medium', 'high'],
                   'options': [{'value': 'mini', 'efforts': ['low']}, {'value': 'opus'}]}
        with mock.patch.dict(models.PROVIDERS, {'claude': (lambda: offered, None), 'codex': (lambda: offered, None)}):
            claude = review.review(self.project, 'claude', model='opus', effort='high')
            self.assertEqual((claude['model'], claude['effort']), ('opus', 'high'))
            self.assertIn('--model=opus --effort=high', claude['review'])
            codex = review.review(self.project, 'codex', model='mini', effort='low')['review']
            self.assertIn('--model=mini -c model_reasoning_effort="low"', codex)
            # Not set: the agent runs as configured, with no extra flags.
            plain = review.review(self.project, 'codex', model='default')
            self.assertEqual((plain['model'], plain['effort']), ('', ''))
            args = plain['review'].splitlines()[0]
            self.assertNotIn('--model', args)
            self.assertNotIn('model_reasoning_effort', args)
            # The model's own efforts decide when it lists them, the configured model's when none is chosen; nothing
            # that looks like a flag gets through.
            offered['model'] = 'mini'
            with self.assertRaises(review.ReviewError):
                review.review(self.project, 'codex', effort='high')
            self.assertEqual(review.review(self.project, 'codex', effort='low')['effort'], 'low')
            del offered['model']
            for bad in ({'model': 'mini', 'effort': 'high'}, {'effort': 'ultra'}, {'model': '--yolo'}, {'model': 'a b'}):
                with self.assertRaises(review.ReviewError, msg=bad):
                    review.review(self.project, 'codex', **bad)
        out = subprocess.run([sys.executable, str(ROOT / 'bin/baton'), 'review', '--agent', 'claude', '--model=-x',
                              '--path', str(self.project)], capture_output=True, text=True)
        self.assertIn('Invalid model or effort', out.stderr)

    def test_falls_back_to_last_commit_and_rejects_unknown_reviewers(self):
        subprocess.run(['git', 'add', '-A'], cwd=self.project, check=True)
        subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'setup'],
                       cwd=self.project, check=True)
        self.assertIn('last commit', review.review(self.project, 'codex')['reviewed'])
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.project, capture_output=True, text=True).stdout.strip()
        by_commit = review.review(self.project, 'codex', commit='HEAD')
        self.assertEqual(by_commit['reviewed'], f'the commit {sha[:12]}')
        self.assertIn(f'git show {sha[:12]}:', by_commit['review'])
        with self.assertRaises(review.ReviewError):
            review.review(self.project, 'nobody')

    def test_unborn_head_odd_names_and_failed_reviewers(self):
        fresh = Path(self.tmp.name) / 'fresh'
        fresh.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=fresh, check=True)
        (fresh / 'staged.py').write_text('print("staged")\n')
        subprocess.run(['git', 'add', 'staged.py'], cwd=fresh, check=True)
        (fresh / 'staged.py').write_text('print("edited after staging")\n')
        (fresh / 'café.py').write_text('print("café")\n', encoding='utf-8')
        diff, what, notes = review.collect_diff(fresh)
        self.assertIn('edited after staging', diff)
        self.assertNotIn('print("staged")', diff)  # Only the final content, not the intermediate staged one.
        self.assertIn('print("café")', diff)
        # Over budget: big files are cut, later ones are named instead of silently dropped.
        with mock.patch.object(review, 'MAX_DIFF', 400):
            (fresh / 'big.txt').write_text('x' * 5000)
            (fresh / 'zz.txt').write_text('later\n')
            diff, what, notes = review.collect_diff(fresh)
            self.assertLess(len(diff), 700)
            self.assertIn('zz.txt', notes)
            # Tracked diff cut too: the reviewer still learns which files changed.
            subprocess.run(['git', 'add', 'big.txt'], cwd=fresh, check=True)
            diff, what, notes = review.collect_diff(fresh)
            self.assertIn('changed files', notes)
            self.assertIn('big.txt', notes)
        # A cut commit patch names the commit's files.
        with mock.patch.object(review, 'MAX_DIFF', 300):
            (self.project / 'one.txt').write_text('y' * 2000)
            subprocess.run(['git', 'add', '-A'], cwd=self.project, check=True)
            subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'big'],
                           cwd=self.project, check=True)
            diff, what, notes = review.collect_diff(self.project, commit='HEAD')
            self.assertIn('files in the commit', notes)
            self.assertIn('one.txt', notes)
        # A stalled git is stopped by the deadline instead of hanging the review.
        stalled = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.PIPE)  # Real, created before the patch.
        with mock.patch.object(review, 'GIT_TIMEOUT', 0.5), mock.patch.object(review.subprocess, 'Popen', return_value=stalled):
            started = time.time()
            with self.assertRaises(review.ReviewError) as caught:
                review.git(fresh, 'diff')
        self.assertIn('took longer', str(caught.exception))
        self.assertLess(time.time() - started, 10)
        self.assertIsNotNone(stalled.poll())  # Killed by the watchdog.
        # A clean merge is reviewed against its first parent, so the merged-in change is visible.
        g = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']
        # A cut diff of a conversation's commits still names their files.
        start = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.project, capture_output=True, text=True).stdout.strip()
        (self.project / 'two.txt').write_text('z' * 2000)
        subprocess.run(['git', 'add', '-A'], cwd=self.project, check=True)
        subprocess.run(g + ['commit', '-q', '-m', 'two'], cwd=self.project, check=True)
        with mock.patch.object(review, 'MAX_DIFF', 300):
            diff, what, notes = review.collect_diff(self.project, since=start)
        self.assertIn('since that conversation began', what)
        self.assertIn('two.txt', notes)
        subprocess.run(g + ['checkout', '-q', '-b', 'side'], cwd=self.project, check=True)
        (self.project / 'side.txt').write_text('from the side branch\n')
        subprocess.run(['git', 'add', 'side.txt'], cwd=self.project, check=True)
        subprocess.run(g + ['commit', '-q', '-m', 'side'], cwd=self.project, check=True)
        subprocess.run(g + ['checkout', '-q', '-'], cwd=self.project, check=True)
        subprocess.run(g + ['merge', '-q', '--no-ff', '-m', 'merge side', 'side'], cwd=self.project, check=True)
        diff, what, notes = review.collect_diff(self.project, commit='HEAD')
        self.assertIn('from the side branch', diff)
        # Many new files: one git call each is capped, the rest is named.
        crowd = Path(self.tmp.name) / 'crowd'
        crowd.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=crowd, check=True)
        for i in range(12):
            (crowd / f'f{i:02}.txt').write_text('')
        with mock.patch.object(review, 'MAX_NEW_FILES', 5):
            diff, what, notes = review.collect_diff(crowd)
        self.assertIn('f11.txt', notes)
        self.assertIn('f05.txt', notes)
        self.assertNotIn('f04.txt', notes)
        # External diff programs configured in git are never run.
        marker = Path(self.tmp.name) / 'ext-ran'
        subprocess.run(['git', 'config', 'diff.external', f'sh -c "touch {marker.as_posix()}"'], cwd=fresh, check=True)
        review.collect_diff(fresh)
        self.assertFalse(marker.exists())
        with self.assertRaises(review.ReviewError):
            review.collect_diff(fresh, commit='no-such-commit')
        with self.assertRaises(review.ReviewError):
            review.collect_diff(Path(self.tmp.name))  # Not a repository.
        # Text plus a failing exit code is an error, not a review.
        self.fake('claude', 'print("partial answer")\nraise SystemExit(2)\n')
        (self.project / 'X').write_text('x')
        with self.assertRaises(review.ReviewError):
            review.review(self.project, 'claude')

    def test_cancel_stops_the_reviewer(self):
        import signal
        # A reviewer that ignores SIGTERM still has to go (SIGKILL after the grace period), and so does its child.
        # On Windows the extension ends the whole tree with taskkill instead of signalling the CLI.
        tmp = Path(self.tmp.name)
        self.fake('codex', 'import os, signal, subprocess, time\n'
                           'if hasattr(signal, "SIGTERM"): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                           'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                           f'open({str(tmp / "child")!r}, "w").write(str(child.pid))\n'
                           f'open({str(tmp / "pid")!r}, "w").write(str(os.getpid()))\n'
                           'time.sleep(30)\n')
        (self.project / 'X').write_text('x')
        cli = subprocess.Popen([sys.executable, str(ROOT / 'bin' / 'baton'), 'review', '--agent', 'codex', '--path',
                                str(self.project)], env={**os.environ, 'PATH': f'{self.bin}{os.pathsep}{os.environ["PATH"]}'})
        pid_file = tmp / 'pid'
        for _ in range(200):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            time.sleep(0.05)
        if WINDOWS:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(cli.pid)], capture_output=True)
        else:
            cli.send_signal(signal.SIGTERM)
        cli.wait(timeout=15)
        time.sleep(0.5)
        for name in ('pid', 'child'):  # The reviewer and a process it started.
            self.assertFalse(alive(int((tmp / name).read_text())), name)

    def test_clean_tree_with_a_conversation_reviews_its_commits_or_its_replies(self):
        g = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']
        subprocess.run(['git', 'add', '-A'], cwd=self.project, check=True)
        subprocess.run(g + ['commit', '-q', '-m', 'setup'], cwd=self.project, check=True)
        # The first conversation has no checkpoint before it: its start is unknown, so no older commit stands in.
        hook.run('codex', payload(self.project, 'Stop', 'c0', last_assistant_message='Codex looked around.'))
        first = review.review(self.project, 'claude', session='c0')
        self.assertEqual(first['reviewed'], "Codex's replies in that conversation (no file changes)")
        self.assertIn('does not know where that conversation began', first['review'])
        hook.run('claude', payload(self.project, 'Stop', 's1', last_assistant_message='Plan: move hooks to ~/.ai-baton.'))
        # Nothing committed since the conversation began: its replies are the work, not some older commit.
        planned = review.review(self.project, 'codex', session='s1')
        self.assertEqual(planned['reviewed'], "Claude's replies in that conversation (no file changes)")
        self.assertIn('<replies>', planned['review'])
        self.assertIn('Plan: move hooks to ~/.ai-baton.', planned['review'])
        self.assertNotIn('Codex looked around.', planned['review'].split('<replies>')[1])
        # A commit made since then is reviewed as the conversation's work.
        (self.project / 'done.txt').write_text('moved\n')
        subprocess.run(['git', 'add', '-A'], cwd=self.project, check=True)
        subprocess.run(g + ['commit', '-q', '-m', 'move'], cwd=self.project, check=True)
        committed = review.review(self.project, 'codex', session='s1')
        self.assertIn('commits since that conversation began', committed['reviewed'])
        self.assertIn('done.txt', committed['review'])
        # Without a chosen conversation a clean tree still means the last commit.
        self.assertIn('last commit', review.review(self.project, 'codex')['reviewed'])

    def test_project_without_a_repository_uses_the_shadow_snapshots(self):
        plain = Path(self.tmp.name) / 'plain'
        plain.mkdir()
        (plain / 'notes.md').write_text('first draft\n')
        init_project.init(plain)
        hook.run('codex', payload(plain, 'Stop', 'c0', last_assistant_message='Codex wrote the draft.'))
        (plain / 'notes.md').write_text('second draft\n')
        hook.run('claude', payload(plain, 'Stop', 's1', last_assistant_message='Claude rewrote the notes.'))
        (plain / 'later.md').write_text('after the checkpoint\n')
        shadow = plain / '.agent-memory/shadow.git'
        # Git may touch an existing object's time when it is reused; names and the index must not change.
        stored = lambda: (sorted(str(f.relative_to(shadow)) for f in shadow.rglob('*') if f.is_file()),
                          (shadow / 'index').read_bytes())
        before = stored()
        chosen = review.review(plain, 'codex', session='s1')
        self.assertEqual(chosen['reviewed'], 'the changes since that conversation began')
        self.assertIn('+second draft', chosen['review'])
        self.assertIn('-first draft', chosen['review'])
        self.assertIn('after the checkpoint', chosen['review'])  # Not yet in a checkpoint, still part of the work.
        self.assertIn('no git repository', chosen['review'])
        self.assertIn('--skip-git-repo-check', chosen['review'])
        self.assertEqual(stored(), before)  # The shadow repo is only read: no new objects, its index untouched.
        latest = review.review(plain, 'claude')
        self.assertEqual(latest['reviewed'], 'the changes since the last checkpoint')
        self.assertIn('after the checkpoint', latest['review'])
        self.assertNotIn('second draft', latest['review'])
        (plain / 'later.md').unlink()
        self.assertEqual(review.review(plain, 'codex')['reviewed'], 'the changes at the last checkpoint')
        hook.run('claude', payload(plain, 'Stop', 's2', last_assistant_message='Only explained the setup.'))
        answered = review.review(plain, 'codex', session='s2')
        self.assertIn('replies in that conversation', answered['reviewed'])
        self.assertIn('Only explained the setup.', answered['review'])
        with self.assertRaises(review.ReviewError):
            review.review(plain, 'codex', commit='HEAD')
        # Git filters from .gitattributes (external programs) never run while collecting.
        marker = Path(self.tmp.name) / 'filter-ran'
        config = Path(self.tmp.name) / 'gitconfig'
        config.write_text(f'[filter "evil"]\n\tclean = "touch {marker.as_posix()}; cat"\n')
        (plain / '.gitattributes').write_text('*.md filter=evil\n')
        (plain / 'notes.md').write_text('third draft\n')
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config)}):
            self.assertIn('third draft', review.review(plain, 'codex')['review'])
        self.assertFalse(marker.exists())
        with self.assertRaises(review.ReviewError) as caught:
            review.review(Path(self.tmp.name), 'codex')  # Neither a repository nor an AI Baton project.
        self.assertIn('baton init', str(caught.exception))

    def test_first_conversation_without_a_repository_is_reviewed_as_a_change(self):
        # UI round 5, D6: a fresh folder without git, one conversation that creates a file.
        fresh = Path(self.tmp.name) / 'fresh-nogit'
        fresh.mkdir()
        log = init_project.init(fresh)
        self.assertTrue(any('first snapshot' in line for line in log))
        hook.run('claude', payload(fresh, 'UserPromptSubmit', 's1', prompt='create notes.txt'))
        (fresh / 'notes.txt').write_text('hello from round 5\n')
        hook.run('claude', payload(fresh, 'Stop', 's1', last_assistant_message='Created notes.txt.'))
        result = review.review(fresh, 'codex', session='s1')
        self.assertEqual(result['reviewed'], 'the changes since that conversation began')
        self.assertIn('+hello from round 5', result['review'])
        self.assertNotIn('+# AGENTS', result['review'])  # Init's own files are in the baseline, not the change.
        # A project set up before baselines existed gets one at the next prompt, before the agent works.
        older = Path(self.tmp.name) / 'older-nogit'
        older.mkdir()
        init_project.init(older)
        rmtree(older / '.agent-memory' / changes.SHADOW_DIR)
        hook.run('codex', payload(older, 'UserPromptSubmit', 'c1', prompt='go'))
        self.assertTrue((older / '.agent-memory' / changes.SHADOW_DIR).is_dir())
        # Out of time or interrupted (an empty shadow repo): no baseline now, a retry at the next prompt.
        rmtree(older / '.agent-memory' / changes.SHADOW_DIR)
        with mock.patch.object(changes, 'BASELINE_BUDGET', 0):
            hook.run('codex', payload(older, 'UserPromptSubmit', 'c1', prompt='go'))
        shadow = older / '.agent-memory' / changes.SHADOW_DIR
        subprocess.run(['git', 'init', '-q', '--bare', str(shadow)], check=True)
        hook.run('codex', payload(older, 'UserPromptSubmit', 'c1', prompt='go'))
        self.assertTrue(changes.git(older, 'rev-parse', '--verify', changes.BASELINE_REF, git_dir=shadow))
        # Snapshots never run git filters (external programs) from the project's .gitattributes.
        marker = Path(self.tmp.name) / 'filter-ran'
        config = Path(self.tmp.name) / 'gitconfig'
        config.write_text(f'[filter "evil"]\n\tclean = "touch {marker.as_posix()}; cat"\n')
        filtered = Path(self.tmp.name) / 'filtered-nogit'
        filtered.mkdir()
        (filtered / '.gitattributes').write_text('* filter=evil\n')
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config)}):
            init_project.init(filtered)
            (filtered / 'a.txt').write_text('a\n')
            hook.run('claude', payload(filtered, 'Stop', 's1', last_assistant_message='Added a.txt.'))
        self.assertFalse(marker.exists())
        # A first commit that is not a marked baseline (projects from before baselines) is never taken as one.
        legacy = Path(self.tmp.name) / 'legacy-nogit'
        legacy.mkdir()
        init_project.init(legacy)
        rmtree(legacy / '.agent-memory' / changes.SHADOW_DIR)
        hook.run('codex', payload(legacy, 'Stop', 'c0', last_assistant_message='Codex did earlier work.'))
        (legacy / 'mine.txt').write_text('mine\n')
        hook.run('claude', payload(legacy, 'Stop', 's1', last_assistant_message='Claude added mine.txt.'))
        lost = Path(self.tmp.name) / 'lost'
        (legacy / '.agent-memory' / 'history.jsonl').rename(lost)  # The checkpoint before s1 is gone.
        (legacy / '.agent-memory' / 'history.jsonl').write_text(lost.read_text().splitlines()[-1] + '\n')
        unknown = review.review(legacy, 'codex', session='s1')
        self.assertIn('replies in that conversation', unknown['reviewed'])
        self.assertIn('does not know where that conversation began', unknown['review'])
        # Git projects never get a shadow repo from the prompt hook.
        self.assertFalse((self.project / '.agent-memory' / changes.SHADOW_DIR).exists())
        hook.run('claude', payload(self.project, 'UserPromptSubmit', 's9', prompt='go'))
        self.assertFalse((self.project / '.agent-memory' / changes.SHADOW_DIR).exists())

    def test_without_git_installed_the_changed_files_are_listed(self):
        plain = Path(self.tmp.name) / 'nogit'
        plain.mkdir()
        init_project.init(plain)
        real_which = shutil.which
        no_git = lambda name, *a, **k: None if name == 'git' else real_which(name, *a, **k)
        with mock.patch.object(shutil, 'which', no_git):
            hook.run('codex', payload(plain, 'Stop', 'c0', last_assistant_message='Codex set up.'))
            time.sleep(0.05)
            (plain / 'recipe.txt').write_text('flour\n')
            for i in range(60):
                (plain / f'page{i:02}.txt').write_text('')
            hook.run('claude', payload(plain, 'Stop', 's1', last_assistant_message='Claude added a recipe.'))
            time.sleep(0.05)
            (plain / 'after.txt').write_text('edited after the checkpoint\n')
            result = review.review(plain, 'codex', session='s1')
        self.assertIn('git is not installed', result['reviewed'])
        self.assertIn('page59.txt', result['review'])
        self.assertIn('after.txt', result['review'])  # Edited after the last checkpoint, still listed.
        self.assertIn('Read them', result['review'])
        self.assertIn('more changed files were not recorded by name', result['review'])

    @unittest.skipIf(WINDOWS, 'SIGTERM handling; a stand-in git on PATH would also have to be an .exe')
    def test_cancel_while_collecting_stops_git(self):
        import signal
        real_git = shutil.which('git')
        pid_file = Path(self.tmp.name) / 'git-pid'
        # A git whose diff hangs; everything else goes to the real git.
        (self.bin / 'git').write_text(f'#!/bin/sh\nif [ "$1" = diff ]; then echo $$ > {pid_file}; exec sleep 30; fi\n'
                                      f'exec {real_git} "$@"\n')
        (self.bin / 'git').chmod(0o755)
        (self.project / 'X').write_text('x')
        cli = subprocess.Popen([sys.executable, str(ROOT / 'bin' / 'baton'), 'review', '--agent', 'codex', '--path',
                                str(self.project)], env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}'},
                               stderr=subprocess.PIPE, text=True)
        for _ in range(200):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            time.sleep(0.05)
        cli.send_signal(signal.SIGTERM)
        _, err = cli.communicate(timeout=15)
        self.assertEqual(cli.returncode, 130)
        self.assertNotIn('Traceback', err)
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)

    def test_nested_repository_and_overall_collection_deadline(self):
        # A separate repository inside the AI Baton project is reviewed on its own.
        nested = self.project / 'nested'
        nested.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=nested, check=True)
        (nested / 'inner.txt').write_text('inner change\n')
        (self.project / 'outer.txt').write_text('outer change\n')
        text = review.review(nested, 'codex')['review']
        self.assertIn('inner change', text)
        self.assertNotIn('outer change', text)
        # Individually fine but together slow git calls hit the shared deadline.
        if WINDOWS:
            return  # A stand-in git on PATH would have to be an .exe.
        real_git = shutil.which('git')
        slow = self.bin / 'git'
        slow.write_text(f'#!/bin/sh\n[ "$1" = diff ] && sleep 0.4\nexec {real_git} "$@"\n')
        slow.chmod(0o755)
        for i in range(6):
            (self.project / f'new{i}.txt').write_text('x\n')
        with mock.patch.dict(os.environ, {'PATH': f'{self.bin}:{os.environ["PATH"]}'}), \
                mock.patch.object(review, 'COLLECT_TIMEOUT', 1):
            with self.assertRaises(review.ReviewError) as caught:
                review.collect_diff(self.project)
        self.assertIn('collecting the changes', str(caught.exception))

    def test_empty_answer_is_an_error(self):
        self.fake('codex', 'raise SystemExit(3)\n')
        (self.project / 'X').write_text('x')
        with self.assertRaises(review.ReviewError):
            review.review(self.project, 'codex')



class HookTrustTest(unittest.TestCase):
    """hookcheck.codex_hooks talks JSON-RPC to a short-lived `codex app-server` (stand-ins here)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_reads_the_answer_split_across_writes(self):
        server = fake_tool(self.dir, 'codex', 'import json\n'
                           'for line in sys.stdin:\n'
                           '    msg = json.loads(line)\n'
                           '    if msg.get("id") == 2:\n'
                           '        out = json.dumps({"id": 2, "result": {"data": [{"hooks": [{"eventName": "stop", "command": "x"}]}]}})\n'
                           '        sys.stdout.write("\\n" + out[:10]); sys.stdout.flush()\n'
                           '        sys.stdout.write(out[10:] + "\\n"); sys.stdout.flush()\n')
        self.assertEqual(hookcheck.codex_hooks(str(server), self.dir), [{'eventName': 'stop', 'command': 'x'}])

    def test_a_silent_server_and_its_child_are_stopped(self):
        # On Windows the stand-in is a .cmd wrapper, as npm installs Codex: the app-server behind it must go too.
        server = fake_tool(self.dir, 'codex', 'import os, subprocess, time\n'
                           'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                           f'open({str(self.dir / "pids")!r}, "w").write(f"{{os.getpid()}} {{child.pid}}")\n'
                           'time.sleep(30)\n')
        with mock.patch.object(hookcheck, 'TIMEOUT', 2):
            started = time.time()
            with self.assertRaises(TimeoutError):
                hookcheck.codex_hooks(str(server), self.dir)
        self.assertLess(time.time() - started, 15)
        time.sleep(0.5)
        server_pid, child_pid = map(int, (self.dir / 'pids').read_text().split())
        self.assertFalse(alive(server_pid))
        if WINDOWS:  # On Unix the child is only re-parented; a killed real app-server takes its own children along.
            self.assertFalse(alive(child_pid))


class LicenseTest(unittest.TestCase):
    def test_hook_command_quotes_odd_paths(self):
        import shlex
        from baton.project import baton_command
        plain = '/Users/me/.ai-baton/bin/baton'
        if WINDOWS:
            # An unquoted interpreter (PowerShell, Codex's shell there, and cmd both run it) and a quoted script.
            launcher = 'C:\\Users\\Jan Kowalski\\.ai-baton\\bin\\baton'
            with mock.patch.dict(os.environ, {'BATON_LAUNCHER': launcher}):
                command = baton_command()
            self.assertEqual(command, f'{Path(sys.executable).as_posix()} "C:/Users/Jan Kowalski/.ai-baton/bin/baton"')
            line = f'{Path(sys.executable).as_posix()} -c "print(41 + 1)"'
            # As Codex starts them: its PowerShell, or `cmd.exe /C "<line>"` (a raw command line) when none is found.
            for shell in (['powershell', '-NoProfile', '-Command', line], f'cmd.exe /C "{line}"'):
                run = subprocess.run(shell, capture_output=True, text=True)
                self.assertEqual(run.stdout.strip(), '42', (shell, run.stderr))
            with mock.patch.object(project, 'short_path', lambda p: 'C:/Program Files/Python/python.exe'):
                self.assertTrue(baton_command().startswith('& "C:/Program Files/Python/python.exe" '))
            return
        with mock.patch.dict(os.environ, {'BATON_LAUNCHER': plain}):
            self.assertTrue(baton_command().endswith(f'"{plain}"'))  # Today's form, so hooks stay unchanged.
        odd = '/tmp/a $(touch x) `b` "c"/baton'
        with mock.patch.dict(os.environ, {'BATON_LAUNCHER': odd}):
            self.assertEqual(shlex.split(baton_command())[-1], odd)  # One argument, nothing expanded.

    def test_extension_ships_the_same_license(self):
        # vsce packages vscode-extension/, so it carries its own copy of the root LICENSE.
        root, ext = (ROOT / 'LICENSE').read_text(), (ROOT / 'vscode-extension' / 'LICENSE').read_text()
        self.assertEqual(root, ext)
        self.assertIn('PolyForm Shield License 1.0.0', root)
        self.assertEqual(json.loads((ROOT / 'vscode-extension' / 'package.json').read_text())['license'],
                         'SEE LICENSE IN LICENSE')


class CliInstallTest(unittest.TestCase):
    """vscode-extension/cli-install.js: versions side by side, current-version switched by rename, a stable launcher."""

    def run_node(self, script):
        if not shutil.which('node'):
            self.skipTest('node is not installed')
        installer = ROOT / 'vscode-extension' / 'cli-install.js'
        code = f'const {{ installCli }} = require({json.dumps(str(installer))});\n{script}'
        result = subprocess.run(['node', '-e', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def bundle(self, bundled, version):
        shutil.rmtree(bundled, ignore_errors=True)
        shutil.copytree(ROOT / 'baton', bundled / 'baton', ignore=shutil.ignore_patterns('__pycache__'))
        (bundled / 'bin').mkdir()
        shutil.copy(ROOT / 'bin' / 'baton', bundled / 'bin' / 'baton')
        (bundled / 'VERSION').write_text(version + '\n')

    def test_install_update_lock_and_launcher(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bundled, target = Path(tmp.name) / 'cli', Path(tmp.name) / 'home' / '.ai-baton'
        current = lambda: (target / 'current-version').read_text().strip()
        call = f'console.log(JSON.stringify(installCli({json.dumps(str(bundled))}, {json.dumps(str(target))})))'
        self.bundle(bundled, '0.3.0')
        self.assertEqual(json.loads(self.run_node(call)), {'home': str(target), 'updated': True})
        self.assertEqual(current(), '0.3.0')
        if not WINDOWS:
            self.assertTrue(os.access(target / 'bin' / 'baton', os.X_OK))
        self.assertFalse(json.loads(self.run_node(call))['updated'])  # Same version: nothing to do.
        # The launcher runs the current version and hooks installed through it point at the launcher itself.
        home = Path(tmp.name) / 'home'
        env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home)}
        run = subprocess.run([sys.executable, str(target / 'bin' / 'baton'), 'install-hooks', '--agents=claude'],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        hook = json.loads((home / '.claude' / 'settings.json').read_text())['hooks']['Stop'][0]['hooks'][0]
        command = init_project.hook_text(hook)
        self.assertIn(f'{(target / "bin" / "baton").as_posix()}', command.replace('\\', '/'))
        self.assertTrue(command.endswith(' hook claude --global'), command)
        self.assertTrue(init_project.is_baton_hook(command, 'claude'))
        # An update switches current-version and keeps the previous version for hooks still running it.
        self.bundle(bundled, '0.3.1')
        launcher = (target / 'bin' / 'baton').read_text()
        self.assertTrue(json.loads(self.run_node(call))['updated'])
        self.assertEqual(current(), '0.3.1')
        if not WINDOWS:
            self.assertEqual(os.readlink(target / 'current'), 'versions/0.3.1')
        self.assertEqual(sorted(os.listdir(target / 'versions')), ['0.3.0', '0.3.1'])
        self.assertEqual((target / 'bin' / 'baton').read_text(), launcher)  # Hook command unchanged.
        status = subprocess.run([sys.executable, str(target / 'bin' / 'baton'), 'status', str(tmp.name)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(status.returncode, 0, status.stderr)
        # A lock whose owner is gone is taken over; a live owner's lock is respected.
        self.bundle(bundled, '0.3.2')
        (target / '.install.lock').write_text('999999:0:dead')
        self.assertTrue(json.loads(self.run_node(call))['updated'])
        self.assertFalse((target / '.install.lock').exists())
        self.bundle(bundled, '0.3.1')
        self.run_node(call)
        self.bundle(bundled, '0.3.2')
        (target / '.install.lock').write_text(f'{os.getpid()}:0:alive')
        self.assertEqual(json.loads(self.run_node(call)).get('busy'), True)
        self.assertEqual(current(), '0.3.1')
        self.assertEqual((target / '.install.lock').read_text(), f'{os.getpid()}:0:alive')  # Not someone else's to remove.
        (target / '.install.lock').unlink()
        self.run_node(call)
        self.assertEqual(sorted(os.listdir(target / 'versions')), ['0.3.1', '0.3.2'])  # Older ones are dropped.
        # Same version, other files (a test build): the build hash in BUILD names a new folder and switches to it.
        (target / '.install.lock').unlink(missing_ok=True)
        self.bundle(bundled, '0.3.2')
        (bundled / 'BUILD').write_text('abc123def456\n')
        self.assertTrue(json.loads(self.run_node(call))['updated'])
        self.assertEqual(current(), '0.3.2-abc123def456')
        self.assertFalse(json.loads(self.run_node(call))['updated'])
        (bundled / 'BUILD').write_text('0123456789ab\n')
        self.assertTrue(json.loads(self.run_node(call))['updated'])
        self.assertEqual(sorted(os.listdir(target / 'versions')), ['0.3.2-0123456789ab', '0.3.2-abc123def456'])
        status = subprocess.run([sys.executable, str(target / 'bin' / 'baton'), 'status', str(tmp.name)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(status.returncode, 0, status.stderr)
        # No bundle (a development copy of the extension): nothing to install.
        self.assertEqual(self.run_node(f'console.log(JSON.stringify(installCli("/nonexistent", {json.dumps(str(target))})))'), 'null')

    @unittest.skipIf(WINDOWS or not shutil.which('sh'), 'bundle-cli.sh is a POSIX shell script')
    def test_bundle_build_hash_follows_the_files(self):
        # A copy of the repo layout bundle-cli.sh expects, so the real vscode-extension/cli is never touched.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / 'repo'
        (repo / 'scripts').mkdir(parents=True)
        shutil.copy(ROOT / 'scripts' / 'bundle-cli.sh', repo / 'scripts')
        (repo / 'baton' / '__pycache__').mkdir(parents=True)
        (repo / 'baton' / 'cli.py').write_text('print(1)\n')
        (repo / 'bin').mkdir()
        (repo / 'bin' / 'baton').write_text('launcher\n')
        (repo / 'vscode-extension').mkdir()
        (repo / 'vscode-extension' / 'package.json').write_text('{"version": "0.9.0"}')

        def build():
            run = subprocess.run(['sh', str(repo / 'scripts' / 'bundle-cli.sh')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            return (repo / 'vscode-extension' / 'cli' / 'BUILD').read_text().strip()

        first = build()
        self.assertRegex(first, r'^[0-9a-f]{12}$')
        (repo / 'baton' / '__pycache__' / 'cli.pyc').write_bytes(b'cache')
        self.assertEqual(build(), first)  # Same files (caches are left out): same hash.
        self.assertFalse(list((repo / 'vscode-extension' / 'cli').rglob('__pycache__')))
        (repo / 'baton' / 'cli.py').write_text('print(2)\n')
        changed = build()
        self.assertNotEqual(changed, first)  # Same version, other code: another hash, so the extension reinstalls.
        (repo / 'baton' / 'new.py').write_text('')
        self.assertNotIn(build(), (first, changed))

    @unittest.skipIf(WINDOWS, 'installs from before current-version used a symlink, which Windows did not support anyway')
    def test_upgrades_a_symlink_install(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bundled, target = Path(tmp.name) / 'cli', Path(tmp.name) / '.ai-baton'
        self.bundle(bundled, '0.3.0')
        shutil.copytree(bundled, target / 'versions' / '0.3.0')
        os.symlink('versions/0.3.0', target / 'current')
        self.bundle(bundled, '0.4.0')
        self.run_node(f'installCli({json.dumps(str(bundled))}, {json.dumps(str(target))})')
        self.assertEqual((target / 'current-version').read_text().strip(), '0.4.0')
        self.assertEqual(os.readlink(target / 'current'), 'versions/0.4.0')  # Still there for older launchers.
        self.assertEqual(sorted(os.listdir(target / 'versions')), ['0.3.0', '0.4.0'])  # The old one may still run.
        # The new launcher still works with only the old symlink (current-version not written yet).
        (target / 'current-version').unlink()
        run = subprocess.run([sys.executable, str(target / 'bin' / 'baton'), 'status', str(tmp.name)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)


class WebviewTest(unittest.TestCase):
    def test_webviews_render_cleanly(self):
        # Syntax checks and code review missed a panel printing "false[object HTMLElement]"; this renders them.
        import shutil
        if not shutil.which('node'):
            self.skipTest('node is not installed')
        result = subprocess.run(['node', str(ROOT / 'tests' / 'webview_smoke.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_flows(self):
        # extension.js against a fake VS Code API and CLI: review, initialize, agents, Python lookup, cancelling.
        if not shutil.which('node'):
            self.skipTest('node is not installed')
        result = subprocess.run(['node', str(ROOT / 'tests' / 'extension_flows.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
