import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from baton import continuation, usage  # noqa: E402
from baton.continuation import ContinueError  # noqa: E402

SESSION = '9a475490-addc-4237-b4c2-62a18e1b4e2d'
CODEX = '01a18d77-b8f3-7123-a9ea-9a0ff0c5f0f3'


class Claude:
    """A Claude transcript in the structure Claude Code 2.1 writes; the message texts are invented."""

    def __init__(self, cwd):
        self.cwd, self.records, self.last, self.count = str(cwd), [], None, 0

    def add(self, kind, parent='last', **fields):
        self.count += 1
        uuid = fields.pop('uuid', f'u{self.count}')
        record = {'type': kind, 'uuid': uuid, 'parentUuid': self.last if parent == 'last' else parent,
                  'sessionId': SESSION, 'cwd': self.cwd, 'entrypoint': 'claude-vscode', 'isSidechain': False,
                  'timestamp': f'2026-10-30T10:{self.count:02d}:00.000Z', **fields}
        self.records.append(record)
        self.last = uuid
        return uuid

    def human(self, content, **fields):
        return self.add('user', message={'role': 'user', 'content': content}, origin={'kind': 'human'},
                        promptId='p', **fields)

    def reply(self, text='done', **fields):
        return self.add('assistant', message={'role': 'assistant', 'content': [{'type': 'text', 'text': text}]},
                        **fields)

    def tool_result(self):
        return self.add('user', message={'role': 'user', 'content': [{'type': 'tool_result', 'content': 'out'}]},
                        toolUseResult={'stdout': 'out'})


def codex_user(item_id, items, kinds=None, at='2026-10-30T10:00:00Z'):
    payload = {'type': 'message', 'role': 'user', 'id': item_id,
               'content': [{'type': 'input_text', 'text': t} if isinstance(t, str) else t for t in items]}
    if kinds is not None:
        payload['internal_chat_message_metadata_passthrough'] = {'content_item_kinds': kinds}
    return {'timestamp': at, 'type': 'response_item', 'payload': payload}


class ContinueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = (self.tmp / 'proj').resolve()
        (self.project / 'src').mkdir(parents=True)
        (self.project / '.baton.json').write_text('{}')
        self.claude_dir = self.tmp / 'claude'
        self.codex_dir = self.tmp / 'codex'
        for patch in (mock.patch.object(continuation, 'CLAUDE_PROJECTS', self.claude_dir),
                      mock.patch.object(continuation, 'CODEX_DIRS', (self.codex_dir,)),
                      mock.patch.object(usage, 'CODEX_TITLES', self.tmp / 'session_index.jsonl')):
            patch.start()
            self.addCleanup(patch.stop)

    def save_claude(self, chat, folder='-proj', session=SESSION):
        path = self.claude_dir / folder / f'{session}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in chat.records))
        return path

    def save_codex(self, records, session=CODEX, cwd=None, source='vscode'):
        meta = {'timestamp': '2026-10-30T09:59:00Z', 'type': 'session_meta',
                'payload': {'id': session, 'cwd': str(cwd or self.project), 'source': source}}
        path = self.codex_dir / '2026' / '10' / '30' / f'rollout-2026-10-30T09-59-00-{session}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in [meta, *records]))
        return path

    def load(self, agent='claude', session=SESSION, **kw):
        return continuation.load(agent, session, str(self.project), **kw)

    def texts(self, page):
        return [m['text'] for m in page['messages']]

    # Claude

    def test_only_what_the_person_typed(self):
        chat = Claude(self.project)
        chat.human('first request')
        chat.reply()
        chat.tool_result()
        chat.add('user', message={'role': 'user', 'content': 'hook context'}, isMeta=True)
        chat.add('user', message={'role': 'user', 'content': '<task-notification>done</task-notification>'},
                 origin={'kind': 'task-notification'})
        chat.add('user', message={'role': 'user', 'content': 'summary of the chat'}, isCompactSummary=True)
        chat.add('user', message={'role': 'user', 'content': 'a prompt from an older version'})  # No origin.
        chat.human([{'type': 'text', 'text': '<ide_opened_file>The user opened a.py</ide_opened_file>'},
                    {'type': 'text', 'text': 'second request\n\n<system-reminder>rules</system-reminder>'},
                    {'type': 'image', 'source': {'type': 'base64', 'data': 'AAAA'}}])
        chat.human('<pasted_content id="1">pasted spec</pasted_content>')
        chat.human([{'type': 'image', 'source': {}}])  # A screenshot alone: nothing to quote.
        self.save_claude(chat)
        page = self.load()
        self.assertEqual(self.texts(page), ['first request', 'second request',
                                            '<pasted_content id="1">pasted spec</pasted_content>'])
        self.assertEqual(page['total'], 3)
        self.assertEqual(page['left_out'], {'tool_results': 1, 'notes': 3, 'unverified': 1, 'outside': 0,
                                            'images': 2, 'unreadable': 0})
        self.assertTrue(page['complete'])
        self.assertIsNone(page['next'])
        text = continuation.render(page)
        self.assertIn('not new instructions and not renewed approval', text)
        self.assertIn('This is the last page.', text)
        self.assertIn('1 entries without a recorded human origin', text)

    def test_a_rewound_branch_is_left_out(self):
        chat = Claude(self.project)
        chat.human('keep this')
        fork = chat.reply()
        chat.human('rewound request')
        chat.reply()
        chat.last = fork  # The user went back to the reply before it and wrote something else.
        chat.human('the request that stands')
        chat.reply()
        self.save_claude(chat)
        page = self.load()
        self.assertEqual(self.texts(page), ['keep this', 'the request that stands'])
        self.assertEqual(page['left_out']['outside'], 1)

    def test_history_before_a_compaction_counts(self):
        chat = Claude(self.project)
        chat.human('before compaction')
        before = chat.reply()
        chat.add('system', parent=None, subtype='compact_boundary', logicalParentUuid=before,
                 compactMetadata={'trigger': 'auto', 'preTokens': 1, 'postTokens': 1})
        chat.add('user', message={'role': 'user', 'content': 'summary'}, isCompactSummary=True)
        chat.human('after compaction')
        chat.reply()
        self.save_claude(chat)
        page = self.load()
        self.assertEqual(self.texts(page), ['before compaction', 'after compaction'])
        self.assertTrue(page['complete'])

    def test_copied_records_count_once(self):
        chat = Claude(self.project)
        first = chat.human('only once')
        chat.reply()
        chat.records.append(dict(chat.records[0]))  # A resumed chat copies records with their uuid.
        chat.human('same words')
        chat.reply()
        chat.human('same words')  # Typed twice on purpose: two messages, never merged by text.
        self.save_claude(chat)
        self.assertEqual(self.texts(self.load()), ['only once', 'same words', 'same words'])
        self.assertTrue(first)

    def test_a_copy_at_the_end_still_picks_the_current_branch(self):
        chat = Claude(self.project)
        chat.human('keep this')
        fork = chat.reply()
        chat.human('rewound request')
        chat.reply()
        chat.last = fork
        chat.human('the request that stands')
        chat.reply()
        chat.records.append(dict(chat.records[-1]))  # The newest message logged once more.
        self.save_claude(chat)
        page = self.load()
        self.assertEqual(self.texts(page), ['keep this', 'the request that stands'])

    def test_a_missing_start_is_reported(self):
        chat = Claude(self.project)
        chat.human('continued from elsewhere', parent='not-in-this-file')
        chat.reply()
        self.save_claude(chat)
        page = self.load()
        self.assertEqual(self.texts(page), ['continued from elsewhere'])  # What the file holds is still shown.
        self.assertFalse(page['complete'])
        self.assertIn('History incomplete', continuation.render(page))

    def test_the_conversation_must_belong_to_the_project(self):
        chat = Claude(self.tmp / 'elsewhere')
        chat.human('x')
        self.save_claude(chat)
        with self.assertRaisesRegex(ContinueError, 'another project'):
            self.load()
        chat = Claude(self.project / 'src')  # A subfolder is the project.
        chat.human('x')
        self.save_claude(chat)
        self.assertEqual(self.load()['total'], 1)
        chat.add('assistant', cwd=str(self.tmp))  # One step outside is enough to refuse.
        self.save_claude(chat)
        with self.assertRaisesRegex(ContinueError, 'another project'):
            self.load()

    def test_refusals(self):
        chat = Claude(self.project)
        chat.human('x')
        with self.assertRaisesRegex(ContinueError, 'No claude conversation'):
            self.load()
        with self.assertRaisesRegex(ContinueError, 'Not a conversation id'):
            self.load(session='../*')
        with self.assertRaisesRegex(ContinueError, 'not copilot'):
            self.load(agent='copilot')
        self.save_claude(chat, session='0000aaaa-other')
        with self.assertRaisesRegex(ContinueError, 'does not belong'):
            self.load(session='0000aaaa-other')
        self.save_claude(chat)
        self.save_claude(chat, folder='-proj-copy')
        with self.assertRaisesRegex(ContinueError, 'More than one'):
            self.load()
        shutil.rmtree(self.claude_dir / '-proj-copy')
        chat.records[0]['entrypoint'] = 'sdk-cli'
        self.save_claude(chat)
        with self.assertRaisesRegex(ContinueError, 'run by a program'):
            self.load()
        (self.project / '.baton.json').unlink()
        with self.assertRaisesRegex(ContinueError, 'baton init'):
            self.load()

    def test_pages_cover_every_message_once(self):
        chat = Claude(self.project)
        long_text = '\n'.join(f'line {i} ' + 'x' * 70 for i in range(150))  # About 11k characters.
        for i in range(12):
            chat.human(long_text if i == 4 else f'request {i} ' + 'y' * 3000)
            chat.reply()
        self.save_claude(chat)
        seen, start, part = [], 1, 1
        for _ in range(20):
            page = self.load(start=start, part=part)
            self.assertLessEqual(len(continuation.render(page)), continuation.PAGE_CHARS)
            seen += [(m['n'], m['part'], m['text']) for m in page['messages']]
            if not page['next']:
                break
            self.assertIn(f'--from {page["next"]["from"]}', page['next']['command'])
            start, part = page['next']['from'], page['next']['part']
        numbers = [(n, p) for n, p, _ in seen]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(sorted({n for n, _ in numbers}), list(range(1, 13)))
        long_parts = [t for n, _, t in seen if n == 5]
        self.assertGreater(len(long_parts), 1)
        self.assertTrue(all(len(t) <= continuation.PART_CHARS for t in long_parts))
        self.assertEqual(''.join(long_parts), long_text)  # Split at line breaks, nothing lost.
        with self.assertRaisesRegex(ContinueError, '--from must be 1 to 12'):
            self.load(start=13)
        for bad in (0, -50):
            with self.assertRaisesRegex(ContinueError, '--from and --part start at 1'):
                self.load(start=5, part=bad)
        with self.assertRaisesRegex(ContinueError, '--part must be 1 to 3'):
            self.load(start=5, part=99)

    def test_parts_join_back_to_the_text(self):
        for text in ('a' * 9000, ('word\n' * 900), 'x' * 3990 + '\n' * 40 + 'y' * 3000, 'line\r\n' * 2000,
                     '\n' * 9000, 'short'):
            pieces = [text[a:b] for a, b in continuation.parts(text)]
            self.assertEqual(''.join(pieces), text)
            self.assertTrue(all(0 < len(p) <= continuation.PART_CHARS for p in pieces))

    def test_the_page_limit_holds_for_long_titles_and_paths(self):
        deep = self.project / ('folder-with-a-long-name' * 6)
        deep.mkdir()
        chat = Claude(deep)
        for i in range(30):
            chat.human(f'request {i} ' + 'z' * 1500)
        chat.records.append({'type': 'custom-title', 'customTitle': 'T' * 5000, 'sessionId': SESSION})
        self.save_claude(chat)
        page = continuation.load('claude', SESSION, str(deep))
        self.assertEqual(len(page['title']), continuation.MAX_TITLE)
        self.assertLessEqual(len(continuation.render(page)), continuation.PAGE_CHARS)
        self.assertIsNotNone(page['next'])

    def test_commands_are_quoted_for_the_agents_shell(self):
        odd = "/work/it's $(x) `y` $HOME"
        with mock.patch.object(continuation.os, 'name', 'nt'), \
                mock.patch.object(continuation, 'hook_argv', lambda: ['C:/Py $x/python.exe', "C:/a'b/bin/baton"]):
            self.assertEqual(continuation.command('codex', CODEX, odd, 3),
                             "& 'C:/Py $x/python.exe' 'C:/a''b/bin/baton' continue --agent codex --session "
                             f"{CODEX} --path '/work/it''s $(x) `y` $HOME' --from 3")
            claude = continuation.command('claude', SESSION, odd)  # Git Bash on Windows.
            self.assertIn(f"--path '/work/it'\"'\"'s $(x) `y` $HOME'", claude)
            self.assertTrue(claude.startswith("'C:/Py $x/python.exe' 'C:/a'\"'\"'b/bin/baton' continue"))
        with mock.patch.object(continuation.os, 'name', 'posix'):  # Codex elsewhere: a POSIX shell.
            self.assertIn("--path '/work/it'\"'\"'s $(x) `y` $HOME'", continuation.command('codex', CODEX, odd))

    def test_credentials_are_redacted_and_counted(self):
        chat = Claude(self.project)
        chat.human('use this\napi_key = abc123\nand sk-abcdefghijklmnop for now')
        self.save_claude(chat)
        page = self.load()
        self.assertNotIn('abc123', page['messages'][0]['text'])
        self.assertNotIn('sk-abcdefghijklmnop', page['messages'][0]['text'])
        self.assertEqual(page['redacted'], 2)
        self.assertIn('Redacted in the messages on this page: 2', continuation.render(page))

    def test_redactions_are_counted_on_the_page_that_shows_them(self):
        chat = Claude(self.project)
        chat.human('a' * 3000)
        chat.human('b' * 9000 + '\npassword: hunter2\n')  # The credential is in the message's last part.
        self.save_claude(chat)
        with mock.patch.object(continuation, 'PAGE_CHARS', 6000):
            pages = [self.load()]
            while pages[-1]['next']:
                pages.append(self.load(start=pages[-1]['next']['from'], part=pages[-1]['next']['part']))
        self.assertGreater(len(pages), 2)
        self.assertEqual([p['redacted'] for p in pages], [0] * (len(pages) - 1) + [1])
        self.assertTrue(all('hunter2' not in m['text'] for p in pages for m in p['messages']))

    def test_a_redaction_at_a_part_boundary_is_whole_and_counted_once(self):
        token = 'sk-' + 'q' * 30
        chat = Claude(self.project)
        chat.human('a' * 3995 + ' ' + token + ' ' + 'b' * 3000 + '\nI wrote [redacted] myself.')
        self.save_claude(chat)
        page = self.load()
        texts = self.texts(page)
        self.assertEqual(len(texts), 2)
        self.assertTrue(texts[0].endswith('[redacted]') or texts[1].startswith('[redacted]'))
        self.assertNotIn(token, ''.join(texts))
        self.assertEqual(page['redacted'], 1, 'the one typed by the user is not a redaction')

    def test_a_long_secret_in_a_title_is_redacted_before_it_is_shortened(self):
        jwt = 'eyJ' + 'a' * 100 + '.' + 'b' * 40 + '.' + 'c' * 40
        chat = Claude(self.project)
        chat.human('x')
        chat.records.append({'type': 'custom-title', 'customTitle': 'Login ' + jwt, 'sessionId': SESSION})
        self.save_claude(chat)
        self.assertEqual(self.load()['title'], 'Login [redacted]')
        self.save_codex([codex_user('a', ['x'], ['user.text'])])
        (self.tmp / 'session_index.jsonl').write_text(json.dumps({'id': CODEX, 'thread_name': 'Login ' + jwt}) + '\n')
        self.assertEqual(self.load('codex', CODEX)['title'], 'Login [redacted]')

    def test_an_empty_history_takes_only_the_first_position(self):
        chat = Claude(self.project)
        chat.add('user', message={'role': 'user', 'content': 'no origin'})
        self.save_claude(chat)
        self.assertEqual(self.load()['total'], 0)
        for start, part in ((0, 1), (-3, 1), (2, 1), (1, 0), (1, 2)):
            with self.assertRaises(ContinueError):
                self.load(start=start, part=part)

    def test_title_and_oversized_lines(self):
        chat = Claude(self.project)
        chat.human('x')
        chat.records.append({'type': 'ai-title', 'aiTitle': 'Generated name', 'sessionId': SESSION})
        chat.records.append({'type': 'custom-title', 'customTitle': 'My name', 'sessionId': SESSION})
        path = self.save_claude(chat)
        with open(path, 'a') as stream:
            stream.write('{"type": "user", "pad": "' + 'z' * 5000 + '"}\n')
        with mock.patch.object(continuation, 'MAX_LINE', 1000):
            page = self.load()
        self.assertEqual(page['title'], 'My name')
        self.assertEqual(page['left_out']['unreadable'], 1)
        self.assertFalse(page['complete'])
        self.assertIn('"My name"', page['header'])

    # Codex

    def test_codex_takes_user_text_by_its_recorded_kind(self):
        self.save_codex([
            codex_user('a', ['<environment_context>cwd</environment_context>'], ['environments.environment_context']),
            codex_user('b', ['# AGENTS.md instructions', '<environment_context/>'],
                       ['agents_md.instructions', 'environments.environment_context']),
            codex_user('c', ['# Context from my IDE setup:\n\n## Open tabs:\n- a.py\n\n## My request:\nfix the bug']),
            codex_user('c2', ['# Context from my IDE setup:\n\n## Open tabs:\n- a.py\n\n## My request:\nfix the bug'],
                       ['user.text']),
            codex_user('d', ['<send_user_message_question_reply>yes, both</send_user_message_question_reply>'],
                       ['user.text']),
            codex_user('e', ['look at this', {'type': 'input_image', 'image_url': 'data:'}], ['user.text', 'user.image']),
            codex_user('e', ['look at this'], ['user.text']),  # The same item again.
            codex_user('f', ['one', 'two'], ['user.text']),  # Kinds that do not match the items.
            {'timestamp': '2026-10-30T10:05:00Z', 'type': 'response_item',
             'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'ok'}]}},
        ])
        page = self.load('codex', CODEX)
        self.assertEqual(self.texts(page), ['fix the bug', 'yes, both', 'look at this'])
        self.assertEqual([m['answer'] for m in page['messages']], [False, True, False])
        self.assertEqual(page['left_out']['notes'], 2)
        self.assertEqual(page['left_out']['unverified'], 2)
        self.assertEqual(page['left_out']['images'], 1)
        self.assertIn('(answer to a question from the agent)', continuation.render(page))

    def test_codex_compaction_and_rollback(self):
        kept = codex_user('a', ['first'], ['user.text'])
        lost = codex_user('z', ['only in the compaction'], ['user.text'])['payload']
        self.save_codex([kept, {'timestamp': '2026-10-30T10:01:00Z', 'type': 'compacted',
                                'payload': {'message': '', 'replacement_history': [kept['payload'], lost]}},
                         codex_user('b', ['second'], ['user.text'])])
        page = self.load('codex', CODEX)
        self.assertEqual(self.texts(page), ['first', 'second'])
        self.assertFalse(page['complete'])
        self.assertEqual(page['gaps'], ['1 earlier messages survive only in a compaction record and are not included'])
        self.save_codex([kept, {'timestamp': '2026-10-30T10:02:00Z', 'type': 'event_msg',
                                'payload': {'type': 'thread_rolled_back', 'num_turns': 1}}])
        with self.assertRaisesRegex(ContinueError, 'rolled back'):
            self.load('codex', CODEX)

    def test_codex_refusals_and_title(self):
        self.save_codex([codex_user('a', ['x'], ['user.text'])], source='exec')
        with self.assertRaisesRegex(ContinueError, 'run by a program'):
            self.load('codex', CODEX)
        self.save_codex([codex_user('a', ['x'], ['user.text'])], cwd=self.tmp)
        with self.assertRaisesRegex(ContinueError, 'another project'):
            self.load('codex', CODEX)
        self.save_codex([codex_user('a', ['x'], ['user.text'])])
        (self.tmp / 'session_index.jsonl').write_text(json.dumps({'id': CODEX, 'thread_name': 'Fix login'}) + '\n')
        self.assertEqual(self.load('codex', CODEX)['title'], 'Fix login')


if __name__ == '__main__':
    unittest.main()
