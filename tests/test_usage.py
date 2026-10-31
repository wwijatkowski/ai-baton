import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baton import usage  # noqa: E402

# Absolute on every system: summarize() resolves the project (on Windows /work/p becomes D:\work\p).
P, Q = str(Path('/work/p').resolve()), str(Path('/work/q').resolve())


def stamp(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace('+00:00', 'Z')


def claude_call(minutes_ago, message_id, fresh, read, write=0, output=10, model='claude-opus-5-5', **extra):
    return {'type': 'assistant', 'timestamp': stamp(minutes_ago), 'sessionId': 'c1', 'cwd': P,
            'entrypoint': 'claude-vscode', 'isSidechain': False,
            'message': {'id': message_id, 'model': model, 'role': 'assistant', 'content': [{'type': 'text', 'text': 'x'}],
                        'usage': {'input_tokens': fresh, 'cache_read_input_tokens': read,
                                  'cache_creation_input_tokens': write, 'output_tokens': output}}, **extra}


def codex_tokens(minutes_ago, last_input, total, window=475000):
    return {'timestamp': stamp(minutes_ago), 'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
        'total_token_usage': {'input_tokens': total, 'cached_input_tokens': 0, 'output_tokens': 5, 'total_tokens': total + 5},
        'last_token_usage': {'input_tokens': last_input, 'cached_input_tokens': 0, 'output_tokens': 5},
        'model_context_window': window}}}


def codex_meta(session, source='vscode', cwd=P):
    return [{'timestamp': stamp(60), 'type': 'session_meta', 'payload': {'id': session, 'cwd': cwd, 'source': source,
                                                                          'originator': 'codex_vscode'}},
            {'timestamp': stamp(60), 'type': 'turn_context', 'payload': {'cwd': cwd, 'model': 'gpt-6.1-sol'}}]


class ContextTest(unittest.TestCase):
    """The context size of each conversation (input of its last request), read from the agents' own logs."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.claude = self.tmp / 'claude'
        self.codex = self.tmp / 'codex'
        patches = [mock.patch.object(usage, 'SOURCES', {'claude': (self.claude, '*.jsonl'),
                                                         'codex': (self.codex, 'rollout-*.jsonl')}),
                   mock.patch.object(usage, 'CACHE', self.tmp / 'cache.json'),
                   mock.patch.object(usage, 'CLAUDE_CONFIG', self.tmp / 'none.json'),
                   mock.patch.object(usage, 'CODEX_TITLES', self.tmp / 'session_index.jsonl')]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, path, records, mode='w'):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode, encoding='utf-8') as stream:
            stream.write(''.join(json.dumps(r) + '\n' for r in records))

    def contexts(self, project=None):
        return usage.summarize(days=7, project=project)['contexts']

    def test_claude_last_main_request_and_compaction(self):
        transcript = self.claude / '-work-p' / 'c1.jsonl'
        self.write(transcript, [
            {'type': 'user', 'timestamp': stamp(30), 'sessionId': 'c1', 'message': {'role': 'user', 'content': 'hi'}},
            claude_call(29, 'm1', 5, 100_000, 2_000),
            claude_call(28, 'm1', 5, 100_000, 2_000),  # The same message logged once per content block.
            claude_call(27, 'm2', 3, 400_000, 10_000),
            claude_call(26, 's1', 1, 900_000, isSidechain=True),  # A subagent's request: not this context.
            'not json',
        ])
        transcript.write_text(transcript.read_text().replace('"not json"', 'not json'))
        [context] = self.contexts()
        self.assertEqual((context['agent'], context['session'], context['tokens'], context['window']),
                         ('claude', 'c1', 410_003, 1_000_000))
        self.assertEqual((context['compactions'], context['compacted']), (0, False))
        # Compaction: the old size is out of date until the next request reports one.
        self.write(transcript, [{'type': 'system', 'subtype': 'compact_boundary', 'timestamp': stamp(20),
                                 'compactMetadata': {'trigger': 'auto', 'preTokens': 410_003, 'postTokens': 9_000}}], 'a')
        [context] = self.contexts()
        self.assertEqual((context['compactions'], context['compacted']), (1, True))
        self.write(transcript, [claude_call(19, 'm3', 2, 30_000)], 'a')
        [context] = self.contexts()
        self.assertEqual((context['tokens'], context['compactions'], context['compacted']), (30_002, 1, False))
        # Spending is counted as before: each message once, the subagent's included.
        totals = usage.summarize(days=7)['agents']['claude']['today']
        self.assertEqual(totals['cache_read'], 1_430_000)

    def test_unattended_conversations_and_subagent_files_are_left_out(self):
        self.write(self.claude / '-work-p' / 'r.jsonl', [claude_call(5, 'r1', 1, 50_000, entrypoint='sdk-cli')])
        self.write(self.claude / '-work-p' / 'c1' / 'subagents' / 'agent-a.jsonl', [claude_call(5, 'a1', 1, 50_000)])
        self.write(self.codex / '2026' / 'rollout-exec.jsonl', codex_meta('x1', 'exec') + [codex_tokens(5, 50_000, 50_000)])
        self.write(self.codex / '2026' / 'rollout-sub.jsonl',
                   codex_meta('x2', {'subagent': {'other': 'guardian'}}) + [codex_tokens(5, 50_000, 50_000)])
        self.assertEqual(self.contexts(), [])

    def test_codex_window_and_compaction(self):
        rollout = self.codex / '2026' / 'rollout-a.jsonl'
        self.write(rollout, codex_meta('x1') + [codex_tokens(10, 200_000, 300_000), codex_tokens(9, 200_000, 300_000)])
        [context] = self.contexts()
        self.assertEqual((context['session'], context['tokens'], context['window'], context['model']),
                         ('x1', 200_000, 475_000, 'gpt-6.1-sol'))
        # Written the way Codex writes it (timestamp, ordinal, type first): its kept history is never decoded.
        with open(rollout, 'a', encoding='utf-8') as stream:
            stream.write(f'{{"timestamp":"{stamp(8)}","ordinal":7,"type":"compacted","payload":{{"message":"",'
                         '"replacement_history":[{"type":"message","role":"user","content":[]}]}}\n')
        # The same usage repeated after the compaction is no new request: it must not bring the old size back.
        self.write(rollout, [codex_tokens(7, 200_000, 300_000)], 'a')
        [context] = self.contexts()
        self.assertEqual((context['compactions'], context['compacted']), (1, True))
        self.write(rollout, [codex_tokens(6, 20_000, 320_000)], 'a')
        [context] = self.contexts()
        self.assertEqual((context['tokens'], context['compacted']), (20_000, False))

    def test_resumed_conversation_in_two_files(self):
        # Claude copies a resumed conversation's records into a new file; the one with the latest event wins.
        first = [claude_call(30, 'm1', 1, 400_000)]
        second = first + [{'type': 'system', 'subtype': 'compact_boundary', 'timestamp': stamp(20)}]
        for names in (('a', 'b'), ('b', 'a')):
            with self.subTest(order=names):
                shutil.rmtree(self.claude, ignore_errors=True)
                (self.tmp / 'cache.json').unlink(missing_ok=True)
                self.write(self.claude / '-work-p' / f'{names[0]}.jsonl', first)
                self.write(self.claude / '-work-p' / f'{names[1]}.jsonl', second)
                [context] = self.contexts()
                self.assertEqual((context['compacted'], context['compactions']), (True, 1))

    def test_newest_copy_wins_before_filters(self):
        # The newest copy is unattended or in another folder: the older interactive copy must not stand in for it.
        older = [claude_call(30, 'm1', 1, 400_000)]
        for newer in ([claude_call(10, 'm2', 1, 500_000, entrypoint='sdk-cli')],
                      [claude_call(10, 'm2', 1, 500_000, cwd=Q)]):
            for names in (('a', 'b'), ('b', 'a')):
                with self.subTest(newer=newer[0].get('entrypoint') or newer[0]['cwd'], order=names):
                    shutil.rmtree(self.claude, ignore_errors=True)
                    (self.tmp / 'cache.json').unlink(missing_ok=True)
                    self.write(self.claude / '-work-p' / f'{names[0]}.jsonl', older)
                    self.assertEqual(len(self.contexts(project=P)), 1)  # Shown until a newer copy exists.
                    self.write(self.claude / '-work-p' / f'{names[1]}.jsonl', older + newer)
                    self.assertEqual(self.contexts(project=P), [])

    def test_codex_compaction_is_never_decoded(self):
        for ordinal in (',"ordinal":7', ''):
            with self.subTest(ordinal=bool(ordinal)):
                line = (f'{{"timestamp":"{stamp(8)}"{ordinal},"type":"compacted","payload":{{"message":"",'
                        '"replacement_history":[]}}').encode()
                entry = {}
                with mock.patch.object(usage.json, 'loads', side_effect=AssertionError('decoded')):
                    usage.parse_codex([line], entry)
                self.assertEqual(entry['context']['compactions'], 1)

    def test_resumed_interactively_after_print_mode(self):
        transcript = self.claude / '-work-p' / 'c1.jsonl'
        self.write(transcript, [claude_call(10, 'm1', 1, 1000, entrypoint='sdk-cli')])
        self.assertEqual(self.contexts(), [])
        self.write(transcript, [claude_call(5, 'm2', 1, 2000)], 'a')
        self.assertEqual([c['tokens'] for c in self.contexts()], [2001])

    def test_window_unknown_or_exceeded_project_filter_and_age(self):
        self.write(self.claude / '-work-p' / 'a.jsonl', [claude_call(5, 'a1', 1, 50_000, model='future-model')])
        self.write(self.claude / '-work-p' / 'b.jsonl',
                   [claude_call(4, 'b1', 1, 300_000, model='claude-haiku-4-5', sessionId='b')])
        self.write(self.claude / '-work-q' / 'c.jsonl', [claude_call(3, 'c1', 1, 10, sessionId='c', cwd=Q)])
        self.write(self.claude / '-work-p' / 'd.jsonl', [claude_call(60 * 30, 'd1', 1, 10, sessionId='d')])
        windows = {c['session']: c['window'] for c in self.contexts()}
        # No window for an unknown model, nor for one past its table entry (the table must be wrong then).
        self.assertEqual(windows, {'c1': None, 'b': None, 'c': 1_000_000})
        self.assertEqual({c['session'] for c in self.contexts(project=P)}, {'c1', 'b'})

    def test_chat_titles(self):
        # Claude: the generated title, replaced by one the user gave; Codex: its index, where later lines are renames.
        self.write(self.claude / '-work-p' / 'c1.jsonl', [
            claude_call(10, 'm1', 1, 1000), {'type': 'ai-title', 'aiTitle': 'Generated', 'sessionId': 'c1'}])
        self.assertEqual([c['title'] for c in self.contexts()], ['Generated'])
        self.write(self.claude / '-work-p' / 'c1.jsonl', [{'type': 'custom-title', 'customTitle': ' Mine ', 'sessionId': 'c1'},
                                                          {'type': 'ai-title', 'aiTitle': 'Newer', 'sessionId': 'c1'}], 'a')
        self.assertEqual([c['title'] for c in self.contexts()], ['Mine'])
        self.write(self.codex / '2026' / 'rollout-a.jsonl', codex_meta('x1') + [codex_tokens(5, 2000, 2000)])
        self.write(self.tmp / 'session_index.jsonl', [{'id': 'x1', 'thread_name': 'First'}, {'id': 'x1', 'thread_name': 'Renamed'}])
        report = usage.summarize(days=7, project=P)
        self.assertEqual({c['session']: c['title'] for c in report['contexts']}, {'c1': 'Mine', 'x1': 'Renamed'})
        self.assertEqual(report['titles'], {'c1': 'Mine', 'x1': 'Renamed'})
        self.assertEqual(usage.summarize(days=7, project=Q)['titles'], {})

    def test_titles_agree_across_copies_in_any_order(self):
        older = [claude_call(30, 'm1', 1, 1000), {'type': 'ai-title', 'aiTitle': 'Old name', 'sessionId': 'c1'}]
        newer = older + [claude_call(10, 'm2', 1, 2000), {'type': 'ai-title', 'aiTitle': 'New name', 'sessionId': 'c1'}]
        renamed = older + [{'type': 'custom-title', 'customTitle': 'Mine', 'sessionId': 'c1'}]  # A rename, no request.
        for second, expected in ((newer, 'New name'), (renamed, 'Mine')):
            for names in (('a', 'b'), ('b', 'a')):
                with self.subTest(expected=expected, order=names):
                    shutil.rmtree(self.claude, ignore_errors=True)
                    (self.tmp / 'cache.json').unlink(missing_ok=True)
                    self.write(self.claude / '-work-p' / f'{names[0]}.jsonl', older)
                    self.write(self.claude / '-work-p' / f'{names[1]}.jsonl', second)
                    report = usage.summarize(days=7, project=P)
                    self.assertEqual(([c['title'] for c in report['contexts']], report['titles']), ([expected], {'c1': expected}))

    def test_title_goes_with_its_transcript(self):
        transcript = self.claude / '-work-p' / 'c1.jsonl'
        self.write(transcript, [claude_call(10, 'm1', 1, 1000), {'type': 'ai-title', 'aiTitle': 'Private', 'sessionId': 'c1'}])
        self.assertEqual(usage.summarize(days=7)['titles'], {'c1': 'Private'})
        if os.name != 'nt':
            self.assertEqual((self.tmp / 'cache.json').stat().st_mode & 0o777, 0o600)
        transcript.unlink()
        report = usage.summarize(days=7)
        self.assertEqual(report['titles'], {})
        self.assertNotIn('Private', (self.tmp / 'cache.json').read_text())
        self.assertEqual(report['agents']['claude']['today']['cache_read'], 1000)  # The numbers stay.

    def test_damaged_codex_index(self):
        self.write(self.codex / '2026' / 'rollout-a.jsonl', codex_meta('x1') + [codex_tokens(5, 2000, 2000)])
        (self.tmp / 'session_index.jsonl').write_bytes(
            b'\xff\xfe not utf-8\n{"id": ["x1"], "thread_name": "list id"}\n{"id": "x1", "thread_name": 7}\n[1]\n'
            b'{"id": "x1", "thread_name": "Good"}\n{"id": "x1", "thread_na')
        report = usage.summarize(days=7)
        self.assertEqual((report['titles'], report['agents']['codex']['today']['input']), ({'x1': 'Good'}, 2000))

    def test_claude_window_table(self):
        self.assertEqual(usage.claude_window('claude-haiku-4-5'), 200_000)
        self.assertEqual(usage.claude_window('claude-sonnet-4-5-20250929'), 200_000)
        self.assertEqual(usage.claude_window('claude-sonnet-5-5'), 1_000_000)
        self.assertEqual(usage.claude_window('claude-haiku-5-5'), 1_000_000)
        self.assertEqual(usage.claude_window('claude-sonnet-4-20250514'), 200_000)
        # Unknown ids, even of a known family, get no window rather than a guess.
        self.assertIsNone(usage.claude_window('claude-opus-unrecognized'))
        self.assertIsNone(usage.claude_window('claude-opus-6'))
        self.assertIsNone(usage.claude_window('gpt-6.1-sol'))
        self.assertIsNone(usage.claude_window(None))


if __name__ == '__main__':
    unittest.main()
