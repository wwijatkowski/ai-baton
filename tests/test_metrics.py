import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from baton import metrics, models

SECRET = 'PROMPT-TEXT-THAT-MUST-NOT-BE-STORED'
USE = {'input_tokens': 10, 'cache_creation_input_tokens': 100, 'cache_read_input_tokens': 1000, 'output_tokens': 5}


def lines(*records):
    return ''.join(json.dumps(r) + '\n' for r in records)


def claude_message(mid, *blocks, usage=USE, t='2026-10-28T10:00:00Z', **extra):
    return {'type': 'assistant', 'timestamp': t, 'cwd': '/work/demo', 'entrypoint': 'claude-vscode', **extra,
            'message': {'id': mid, 'model': 'claude-opus-5-5', 'usage': usage, 'content': list(blocks)}}


def user(content, t='2026-10-28T09:59:59Z'):
    return {'type': 'user', 'timestamp': t, 'message': {'content': content}}


def hook_context(text):
    return {'type': 'attachment', 'timestamp': '2026-10-28T09:59:58Z',
            'attachment': {'type': 'hook_additional_context', 'content': [text]}}


def tool(name, **args):
    return {'type': 'tool_use', 'name': name, 'input': args}


def text(value):
    return {'type': 'text', 'text': value}


DELIVERY = ('This project uses AI Baton. Rules: AGENTS.md.\nBelow are local, historical checkpoints from other agents '
            'and your other conversations.\n[codex] 2026-10-27 22:00 UTC · branch main\nDid things.\n\n'
            '[claude, your other conversation] 2026-10-27 21:00 UTC\nOther things.')


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.claude, self.codex, self.store = base / 'claude', base / 'codex', base / 'metrics' / 'conversations.json'
        (self.claude / 'proj').mkdir(parents=True)
        (self.codex / '2026' / '10' / '28').mkdir(parents=True)
        self.sources = {'claude': (self.claude, metrics.SOURCES['claude'][1]),
                        'codex': (self.codex, metrics.SOURCES['codex'][1])}
        patch = mock.patch.object(models, 'REVIEW_SESSIONS', base / 'reviews.json')
        patch.start()
        self.addCleanup(patch.stop)

    def collect(self):
        return metrics.collect(self.store, self.sources)

    def stored(self):
        return json.loads(self.store.read_text())['conversations']

    def conversation(self, key):
        return self.stored()[key]

    def test_claude_conversation(self):
        (self.claude / 'proj' / 's1.jsonl').write_text(lines(
            hook_context(DELIVERY),
            user(SECRET),
            # One API message is logged once per content block: counted once. The edit request is left out of the
            # orientation even when an earlier block of the same message was logged first.
            claude_message('m1', tool('Read', file_path='a.py')),
            claude_message('m1', tool('Bash', command='ls 2>&1 | head')),
            claude_message('m2', text('Now the change.'), t='2026-10-28T10:00:30Z'),
            claude_message('m2', tool('Edit', file_path='/work/demo/a.py'), t='2026-10-28T10:00:31Z'),
            claude_message('m3', text(SECRET), t='2026-10-28T10:01:00Z'),
            user([{'type': 'tool_result', 'content': 'ok'}]),  # Not a prompt.
            user([text('and one more thing')]),  # A prompt as blocks.
            # A later delivery: new checkpoints only, without the base text.
            hook_context('Below are local, historical checkpoints from other agents and your other conversations.\n'
                         '[codex] 2026-10-28 10:02 UTC · branch main\nMore.'),
        ))
        self.assertEqual(self.collect(), {'updated': 1, 'conversations': 1, 'errors': 0})
        c = self.conversation('claude:s1')
        self.assertEqual((c['agent'], c['session'], c['client'], c['models'], c['prompts']),
                         ('claude', 's1', 'claude-vscode', ['claude-opus-5-5'], 2))
        self.assertEqual(c['usage'], {'input': 30, 'cache_write': 300, 'cache_read': 3000, 'output': 15})
        self.assertEqual(c['tool_calls'], 3)
        self.assertEqual(c['first_edit'], {'kind': 'tool', 'tool_calls_before': 2, 'requests_before': 1, 'seconds': 33,
                                           'usage_before': {'input': 10, 'cache_write': 100, 'cache_read': 1000, 'output': 5}})
        self.assertEqual(c['baton']['deliveries'], 2)
        self.assertEqual(c['baton']['checkpoints'], {'own': 1, 'other_agent': 2})
        self.assertEqual(c['project'], metrics.project_id('/work/demo'))
        stored = self.store.read_text()
        self.assertNotIn(SECRET, stored)
        self.assertNotIn('/work/demo', stored)
        self.assertNotIn('a.py', stored)
        # Unchanged files are not parsed again; a deleted transcript keeps its summary.
        self.assertEqual(self.collect()['updated'], 0)
        (self.claude / 'proj' / 's1.jsonl').unlink()
        self.assertEqual(self.collect(), {'updated': 0, 'conversations': 1, 'errors': 0})

    def test_one_claude_conversation_in_two_files_and_its_subagents(self):
        shared = [user('go'), claude_message('m1', tool('Read', file_path='a.py'))]
        (self.claude / 'proj').joinpath('s2.jsonl').write_text(lines(*shared))
        (self.claude / 'other').mkdir()
        (self.claude / 'other' / 's2.jsonl').write_text(lines(*shared, claude_message('m2', text('done'))))
        sub = self.claude / 'proj' / 's2' / 'subagents'
        sub.mkdir(parents=True)
        (sub / 'agent-1.jsonl').write_text(lines(claude_message('x1', tool('Edit', file_path='b.py'), isSidechain=True)))
        self.collect()
        self.assertEqual(list(self.stored()), ['claude:s2'])
        c = self.conversation('claude:s2')
        self.assertEqual((c['requests'], c['prompts'], c['tool_calls'], len(c['source'])), (2, 1, 1, 3))
        self.assertEqual(c['subagents'], {'requests': 1, 'usage': {'input': 10, 'cache_write': 100, 'cache_read': 1000,
                                                                     'output': 5}})
        self.assertIsNone(c['first_edit'])  # A subagent's edit is not the conversation's own orientation.

    def test_what_is_not_a_first_edit(self):
        (self.claude / 'proj' / 's3.jsonl').write_text(lines(
            user('go'),
            claude_message('m1', tool('Write', file_path='/work/demo/docs/AGENT_HANDOFF.md')),
            claude_message('m2', tool('Bash', command='git restore --help')),
            claude_message('m4', tool('Bash', command='cat > docs/AGENT_HANDOFF.md <<EOF')),
            claude_message('m5', tool('Bash', command='Set-Content docs/STATUS.md done')),
            claude_message('m3', tool('Bash', command='Set-Content notes.md "x"')),
        ))
        self.collect()
        self.assertEqual(self.conversation('claude:s3')['first_edit']['tool_calls_before'], 4)
        self.assertTrue(metrics.shell_edit('echo x > docs/AGENT_HANDOFF.md > a.py'))  # Work as well as bookkeeping.

    def test_codex_conversation_and_its_resumed_file(self):
        token = lambda total, cached, out, t: {'type': 'event_msg', 'timestamp': t, 'payload': {
            'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': total, 'cached_input_tokens': cached,
                                                                   'output_tokens': out, 'total_tokens': total + out}}}}
        call = lambda code, t: {'type': 'response_item', 'timestamp': t,
                                'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': code}}
        message = lambda role, value: {'type': 'response_item', 'timestamp': '2026-10-28T10:00:01Z', 'payload': {
            'type': 'message', 'role': role, 'content': [{'type': 'input_text', 'text': value}]}}
        meta = {'type': 'session_meta', 'timestamp': '2026-10-28T10:00:00Z',
                'payload': {'id': 'c1', 'cwd': '/work/demo', 'originator': 'codex_vscode'}}
        first = [
            meta,
            {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol'}},
            message('developer', 'This project uses AI Baton.\n[claude] 2026-10-27 20:00 UTC\nDone.'),
            message('user', '# AGENTS.md instructions for /work/demo ... baton recall ...'),  # Not a delivery.
            message('user', SECRET),
            call('tools.exec_command({cmd:"cat a.py", max_output_tokens: 10}); x.filter(t => t)', '2026-10-28T10:00:05Z'),
            token(100, 40, 10, '2026-10-28T10:00:06Z'),
            token(100, 40, 10, '2026-10-28T10:00:07Z'),  # Repeated: nothing new spent.
            call('tools.apply_patch("*** Begin Patch\\n*** Update File: docs/AGENT_HANDOFF.md\\n")', '2026-10-28T10:00:08Z'),
            call('tools.exec_command({cmd:"echo hi > notes.md"})', '2026-10-28T10:00:09Z'),
            token(250, 140, 30, '2026-10-28T10:00:10Z'),
        ]
        day = self.codex / '2026' / '10' / '28'
        (day / 'rollout-1.jsonl').write_text(lines(*first))
        self.collect()
        c = self.conversation('codex:c1')
        self.assertEqual((c['agent'], c['prompts'], c['models']), ('codex', 1, ['gpt-6.1-sol']))
        self.assertEqual(c['usage'], {'input': 110, 'cache_write': 0, 'cache_read': 140, 'output': 30})
        self.assertEqual((c['first_edit']['kind'], c['first_edit']['tool_calls_before']), ('shell', 2))
        self.assertEqual((c['baton']['deliveries'], c['baton']['checkpoints']), (1, {'own': 0, 'other_agent': 1}))
        # Resumed: a new file of the same session repeats the old records, then goes on. One conversation.
        (day / 'rollout-2.jsonl').write_text(lines(*first, message('user', 'next'), token(300, 150, 40, '2026-10-28T11:00:00Z')))
        self.collect()
        self.assertEqual(list(self.stored()), ['codex:c1'])
        c = self.conversation('codex:c1')
        self.assertEqual((c['prompts'], c['usage']['output']), (2, 40))

    def test_reviews_unknown_usage_and_odd_files(self):
        for sid, first in (('work', 'fix the bug'), ('registered', 'review it'),
                           ('old-review', "You are reviewing a teammate's change in this project")):
            (self.claude / 'proj' / f'{sid}.jsonl').write_text(lines(user(first), claude_message(f'm-{sid}')))
        bench = claude_message('m-b')
        bench['cwd'] = '/tmp/baton-bench-B-shelf-file-x'
        (self.claude / 'proj' / 'bench.jsonl').write_text(lines(user('go'), bench))
        (self.claude / 'proj' / 'nousage.jsonl').write_text(lines(
            user('hello'), {'type': 'assistant', 'message': {'id': 'n1', 'content': [tool('Read'), tool('Write', file_path='x.py')]}}))
        (self.claude / 'proj' / 'odd.jsonl').write_text(lines(user('x'), {'type': 'assistant', 'message': {'content': 5}}))
        models.add_review_session('registered')
        result = self.collect()
        self.assertEqual(result['errors'], 0)
        nousage = self.conversation('claude:nousage')
        self.assertIsNone(nousage['usage'])  # Unknown, not zero.
        self.assertEqual((nousage['first_edit']['tool_calls_before'], nousage['first_edit']['usage_before']), (1, None))
        report = metrics.report(self.store)
        self.assertEqual((report['reviews_left_out'], report['bench_left_out']), (2, 1))
        [group] = report['groups']
        self.assertEqual((group['conversations'], group['usage_unknown'], group['with_edit_attempt']), (3, 2, 1))
        self.assertIsNone(group['median_tokens_before_first_edit'])
        self.assertEqual(group['median_tool_calls_before_first_edit'], 1)
        # A file that breaks the parser is counted as an error; the others are still saved.
        real = metrics.parse_claude

        def parse(summary, path, subagent=False):
            if path.stem == 'odd':
                raise RuntimeError('unexpected shape')
            return real(summary, path, subagent)
        self.store.unlink()
        with mock.patch.dict(metrics.PARSERS, {'claude': parse}):
            result = self.collect()
        self.assertEqual((result['errors'], result['conversations']), (1, 5))

    def test_an_older_store_is_rebuilt(self):
        (self.claude / 'proj' / 's9.jsonl').write_text(lines(user('go'), claude_message('m1')))
        self.store.parent.mkdir(parents=True)
        self.store.write_text(json.dumps({'version': 2, 'conversations': {
            'claude:0123456789abcdef': {'version': 2, 'agent': 'claude', 'session': 's9', 'baton': {'injections': 1}},
            'codex:gone': {'version': 2, 'agent': 'codex', 'session': 'gone'}}}))
        self.collect()
        self.assertEqual(list(self.stored()), ['claude:s9'])
        self.assertEqual(metrics.report(self.store)['conversations'], 1)

    def test_shell_edits(self):
        for command in ('cat a > out.txt', 'sed -i s/a/b/ f', 'git apply p.diff', 'tee notes.md', 'echo >> log',
                        'Set-Content a.txt x'):
            self.assertTrue(metrics.shell_edit(command), command)
        for command in ('ls 2>&1 | head', 'x => y', 'python3 - <<EOF', 'echo > /dev/null', 'cat > /tmp/x', None,
                        'git restore --help'):
            self.assertFalse(metrics.shell_edit(command), command)


if __name__ == '__main__':
    unittest.main()
