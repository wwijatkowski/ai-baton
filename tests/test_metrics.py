import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from baton import metrics, models

SECRET = 'PROMPT-TEXT-THAT-MUST-NOT-BE-STORED'


def lines(*records):
    return ''.join(json.dumps(r) + '\n' for r in records)


def claude_message(mid, usage, *blocks, t='2026-10-28T10:00:00Z'):
    return {'type': 'assistant', 'timestamp': t, 'cwd': '/work/demo', 'entrypoint': 'claude-vscode',
            'message': {'id': mid, 'model': 'claude-opus-5-5', 'usage': usage, 'content': list(blocks)}}


def tool(name, **args):
    return {'type': 'tool_use', 'name': name, 'input': args}


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.claude, self.codex, self.store = base / 'claude', base / 'codex', base / 'metrics' / 'conversations.json'
        (self.claude / 'proj').mkdir(parents=True)
        (self.codex / '2026' / '10' / '28').mkdir(parents=True)
        self.sources = {'claude': (self.claude, '*/*.jsonl'), 'codex': (self.codex, '**/rollout-*.jsonl')}
        patch = mock.patch.object(models, 'REVIEW_SESSIONS', base / 'reviews.json')
        patch.start()
        self.addCleanup(patch.stop)

    def collect(self):
        return metrics.collect(self.store, self.sources)

    def stored(self):
        return json.loads(self.store.read_text())['conversations']

    def test_claude_conversation(self):
        usage = {'input_tokens': 10, 'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 1000, 'output_tokens': 5}
        (self.claude / 'proj' / 's1.jsonl').write_text(lines(
            {'type': 'attachment', 'timestamp': '2026-10-28T09:59:58Z',
             'attachment': {'type': 'hook_additional_context', 'content': [
                 'This project uses AI Baton. Below are local, historical checkpoints from other agents. ...']}},
            {'type': 'user', 'timestamp': '2026-10-28T09:59:59Z', 'message': {'content': SECRET}},
            # One API message logged once per content block: counted once.
            claude_message('m1', usage, tool('Read', file_path='a.py')),
            claude_message('m1', usage, tool('Bash', command='ls 2>&1 | head')),
            claude_message('m2', usage, tool('Edit', file_path='a.py'), t='2026-10-28T10:00:30Z'),
            claude_message('m3', usage, {'type': 'text', 'text': SECRET}, t='2026-10-28T10:01:00Z'),
            {'type': 'assistant', 'isSidechain': True, 'message': {'id': 'sub', 'usage': usage, 'content': []}},
        ))
        self.assertEqual(self.collect(), (1, 1))
        [c] = self.stored().values()
        self.assertEqual((c['agent'], c['session'], c['client'], c['models'], c['prompts']),
                         ('claude', 's1', 'claude-vscode', ['claude-opus-5-5'], 1))
        self.assertEqual(c['usage'], {'input': 30, 'cache_write': 300, 'cache_read': 3000, 'output': 15})
        self.assertEqual(c['tool_calls'], 3)
        # Before the edit: two calls and m1 only (the request that made the edit is left out).
        self.assertEqual(c['first_edit'], {'kind': 'tool', 'tool_calls_before': 2, 'requests_before': 1, 'seconds': 32,
                                           'usage_before': {'input': 10, 'cache_write': 100, 'cache_read': 1000, 'output': 5}})
        self.assertEqual((c['baton']['injections'], c['baton']['other_checkpoint']), (1, True))
        self.assertEqual(c['project'], metrics.project_id('/work/demo'))
        self.assertNotIn(SECRET, self.store.read_text())  # Counts only.
        self.assertNotIn('/work/demo', self.store.read_text())
        # Unchanged files are not parsed again; a deleted transcript keeps its summary.
        self.assertEqual(self.collect(), (0, 1))
        (self.claude / 'proj' / 's1.jsonl').unlink()
        self.assertEqual(self.collect(), (0, 1))

    def test_codex_conversation(self):
        token = lambda total, cached, out: {'type': 'event_msg', 'timestamp': '2026-10-28T10:00:10Z', 'payload': {
            'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': total, 'cached_input_tokens': cached,
                                                                   'output_tokens': out, 'total_tokens': total + out}}}}
        call = lambda code: {'type': 'response_item', 'timestamp': '2026-10-28T10:00:05Z',
                             'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': code}}
        user = lambda text: {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                                  'content': [{'type': 'input_text', 'text': text}]}}
        path = self.codex / '2026' / '10' / '28' / 'rollout-1.jsonl'
        path.write_text(lines(
            {'type': 'session_meta', 'timestamp': '2026-10-28T10:00:00Z',
             'payload': {'id': 'c1', 'cwd': '/work/demo', 'originator': 'codex_vscode'}},
            {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer',
                                                  'content': [{'type': 'input_text', 'text': 'This project uses AI Baton.'}]}},
            user('# AGENTS.md instructions for /work/demo'),
            user(SECRET),
            call('tools.exec_command({cmd:"cat a.py", max_output_tokens: 10}); x.filter(t => t)'),
            token(100, 40, 10),
            token(100, 40, 10),  # Repeated: nothing new spent.
            call('tools.exec_command({cmd:"echo hi > notes.md"})'),
            token(250, 140, 30),
            call('tools.apply_patch("...")'),
        ))
        self.collect()
        [c] = self.stored().values()
        self.assertEqual((c['agent'], c['session'], c['prompts'], c['models']), ('codex', 'c1', 1, ['gpt-6.1-sol']))
        self.assertEqual(c['usage'], {'input': 110, 'cache_write': 0, 'cache_read': 140, 'output': 30})
        self.assertEqual((c['first_edit']['kind'], c['first_edit']['tool_calls_before']), ('shell', 1))
        self.assertEqual(c['tool_calls'], 3)
        self.assertEqual((c['baton']['injections'], c['baton']['other_checkpoint']), (1, False))
        # A resumed session in another file is another conversation, not an overwrite.
        (path.parent / 'rollout-2.jsonl').write_text(path.read_text())
        self.collect()
        self.assertEqual(len(self.stored()), 2)

    def test_review_runs_are_left_out_of_the_report(self):
        usage = {'input_tokens': 1, 'output_tokens': 1}
        for sid in ('work', 'review'):
            (self.claude / 'proj' / f'{sid}.jsonl').write_text(lines(
                {'type': 'user', 'message': {'content': 'x'}}, claude_message(f'm-{sid}', usage)))
        models.add_review_session('review')
        self.collect()
        report = metrics.report(self.store)
        self.assertEqual((report['conversations'], report['reviews_left_out']), (1, 1))
        self.assertEqual(report['groups'][0]['group'], 'no AI Baton context')

    def test_shell_edits(self):
        for command in ('cat a > out.txt', 'sed -i s/a/b/ f', 'git apply p.diff', 'tee notes.md', 'echo >> log'):
            self.assertTrue(metrics.shell_edit(command), command)
        for command in ('ls 2>&1 | head', 'x => y', 'python3 - <<EOF', 'echo > /dev/null', 'cat > /tmp/x', None):
            self.assertFalse(metrics.shell_edit(command), command)


if __name__ == '__main__':
    unittest.main()
