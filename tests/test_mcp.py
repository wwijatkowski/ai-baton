"""`baton mcp` driven like a real MCP client: one long-lived process, a message per line, each answer read while
stdin stays open (a missing flush would hang here, not pass), then EOF."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baton import hook, init_project, mcp_install, status  # noqa: E402
from baton.project import read_json  # noqa: E402

MODERN = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
          'io.modelcontextprotocol/clientInfo': {'name': 'modern-client', 'version': '1'},
          'io.modelcontextprotocol/clientCapabilities': {}}


class Client:
    def __init__(self, *args, env=None):
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'bin' / 'baton'), 'mcp', *args],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env={**os.environ, **(env or {})})
        self.lines = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()
        self.next_id = 0

    def read(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message):
        raw = message if isinstance(message, bytes) else json.dumps(message, ensure_ascii=False).encode('utf-8')
        self.proc.stdin.write(raw + b'\n')
        self.proc.stdin.flush()

    def answer(self, timeout=20):
        line = self.lines.get(timeout=timeout)
        assert line is not None, 'the server closed stdout'
        assert line.endswith(b'\n') and not line.endswith(b'\r\n'), line
        return json.loads(line.decode('utf-8'))

    def request(self, method, params=None):
        self.next_id += 1
        self.send({'jsonrpc': '2.0', 'id': self.next_id, 'method': method, **({'params': params} if params else {})})
        reply = self.answer()
        assert reply['id'] == self.next_id, reply
        return reply

    def call(self, tool, **arguments):
        result = self.request('tools/call', {'name': tool, 'arguments': arguments})['result']
        return result['content'][0]['text'], result['isError']

    def initialize(self):
        return self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                           'clientInfo': {'name': 'test-client', 'version': '1'}})

    def close(self):
        self.proc.stdin.close()
        code = self.proc.wait(20)
        self.stderr = self.proc.stderr.read()
        self.proc.stdout.close()
        self.proc.stderr.close()
        return code


class McpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / 'démo'
        self.project.mkdir()
        init_project.init(self.project)
        self.client = Client('--agent', 'copilot')

    def tearDown(self):
        if self.client.proc.poll() is None:
            self.client.close()
        self.tmp.cleanup()

    def test_legacy_handshake_and_message_handling(self):
        c = self.client
        c.send(b'not json')
        self.assertEqual(c.answer()['error']['code'], -32700)
        c.send({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
                'params': {'protocolVersion': '2025-06-18', 'clientInfo': {'name': 'test-client'}}})
        init = c.answer()
        self.assertEqual(init['id'], 0, 'id 0 is a request id like any other')
        self.assertEqual(init['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(init['result']['capabilities'], {'tools': {}})
        self.assertIn('baton_context', init['result']['instructions'])
        # An unknown legacy version gets the newest legacy one; so does 2025-03-26, which would need batches.
        for asked in ('1999-01-01', '2025-03-26'):
            self.assertEqual(c.request('initialize', {'protocolVersion': asked})['result']['protocolVersion'],
                             '2025-11-25')
        c.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})  # No reply; the next answer is ping's.
        self.assertEqual(c.request('ping')['result'], {})
        self.assertEqual([t['name'] for t in c.request('tools/list')['result']['tools']],
                         ['baton_context', 'baton_checkpoint', 'baton_recall'])
        self.assertEqual(c.request('nope/nothing')['error']['code'], -32601)
        self.assertEqual(c.request('tools/call', {'name': 'rm_rf'})['error']['code'], -32602)
        c.send([{'jsonrpc': '2.0', 'id': 9, 'method': 'ping'}])
        self.assertEqual(c.answer()['error']['code'], -32600)
        c.send({'id': 10, 'method': 'ping'})
        self.assertEqual(c.answer()['error']['code'], -32600)
        # Malformed messages never end the server: each gets an error, and the next request is answered.
        for name in ([], {}, None):
            self.assertEqual(c.request('tools/call', {'name': name})['error']['code'], -32602)
        c.send(b'[' * 100000 + b']' * 100000)
        self.assertIn(c.answer()['error']['code'], (-32700, -32600))
        self.assertEqual(c.request('tools/call', {'name': 'baton_recall', 'arguments': []})['error']['code'], -32602)
        self.assertEqual(c.request('ping')['result'], {})
        self.assertEqual(c.close(), 0, 'EOF ends the server cleanly')
        self.assertEqual(c.stderr, b'', 'nothing on stderr either')

    def test_modern_requests_and_discovery(self):
        c = self.client
        discover = c.request('server/discover', {'_meta': MODERN})['result']
        self.assertIn('2026-07-28', discover['supportedVersions'])
        self.assertIn('2025-06-18', discover['supportedVersions'])
        self.assertEqual(discover['_meta']['io.modelcontextprotocol/serverInfo']['name'], 'ai-baton')
        tools = c.request('tools/list', {'_meta': MODERN})['result']
        self.assertEqual(tools['resultType'], 'complete')
        for method in ('tools/list', 'server/discover'):
            old = c.request(method, {'_meta': {**MODERN, 'io.modelcontextprotocol/protocolVersion': '2030-01-01'}})
            self.assertEqual(old['error']['code'], -32022)
            self.assertEqual(old['error']['data']['requested'], '2030-01-01')
        # Every modern request carries its client's identity and capabilities.
        missing = {k: v for k, v in MODERN.items() if k != 'io.modelcontextprotocol/clientCapabilities'}
        self.assertEqual(c.request('tools/list', {'_meta': missing})['error']['code'], -32602)
        # The client's name from _meta is recorded with the checkpoint.
        text, failed = c.call('baton_context', project_path=str(self.project))
        sid = text.rsplit('session_id: ', 1)[1].split()[0]
        result = c.request('tools/call', {'_meta': MODERN, 'name': 'baton_checkpoint', 'arguments': {
            'project_path': str(self.project), 'session_id': sid, 'summary': 'Checked discovery.'}})['result']
        self.assertFalse(result['isError'], result)
        self.assertEqual(read_json(self.project / '.agent-memory/copilot.json')['client'], 'modern-client')
        # A legacy-style call afterwards (no _meta) does not inherit the modern request's name.
        c.call('baton_checkpoint', project_path=str(self.project), session_id=sid, summary='Again.')
        self.assertIsNone(read_json(self.project / '.agent-memory/copilot.json')['client'])

    def test_conversations_share_memory_with_hooks_and_each_other(self):
        c = self.client
        c.initialize()
        text, failed = c.call('baton_context', project_path=str(self.project))
        self.assertFalse(failed, text)
        self.assertIn('No checkpoint from another agent', text)
        first = text.rsplit('session_id: ', 1)[1].split()[0]
        second = c.call('baton_context', project_path=str(self.project))[0].rsplit('session_id: ', 1)[1].split()[0]
        self.assertNotEqual(first, second)

        # Interleaved chats: the first one checkpoints after the second started; each keeps its own identity.
        (self.project / 'notes.md').write_text('zażółć\n', encoding='utf-8')
        text, failed = c.call('baton_checkpoint', project_path=str(self.project), session_id=first,
                              summary='Wrote notes.md — zażółć gęślą jaźń. Next: tests.')
        self.assertFalse(failed, text)
        self.assertIn('Checkpoint saved for copilot', text)
        saved = read_json(self.project / '.agent-memory/copilot.json')
        self.assertEqual((saved['session_id'], saved['client']), (first, 'test-client'))
        self.assertIn('zażółć gęślą jaźń', saved['summary'])

        # The second chat, asking again, gets the first one's work once; the first never gets its own back.
        refreshed = c.call('baton_context', project_path=str(self.project), session_id=second)[0]
        self.assertIn('[copilot, your other conversation]', refreshed)
        self.assertIn('Nothing new', c.call('baton_context', project_path=str(self.project), session_id=second)[0])
        self.assertNotIn('Wrote notes', c.call('baton_context', project_path=str(self.project), session_id=first)[0])
        # A new chat starts with it.
        self.assertIn('Wrote notes', c.call('baton_context', project_path=str(self.project))[0])

        # An agent outside the registry still reaches the hooks of the others, and Recent work.
        claude = hook.run('claude', {'cwd': str(self.project), 'hook_event_name': 'SessionStart', 'session_id': 'k1'})
        self.assertIn('[copilot]', claude['hookSpecificOutput']['additionalContext'])
        hook.run('claude', {'cwd': str(self.project), 'hook_event_name': 'Stop', 'session_id': 'k1',
                            'last_assistant_message': 'Claude reviewed the notes.'})
        self.assertIn('Claude reviewed the notes', c.call('baton_context', project_path=str(self.project))[0])

        hits = c.call('baton_recall', project_path=str(self.project), words=['gęślą'])[0]
        self.assertIn('[copilot]', hits)
        self.assertIn('No matching', c.call('baton_recall', project_path=str(self.project), words=['absent'])[0])

    def test_bad_arguments_are_tool_errors(self):
        c = self.client
        other = Path(self.tmp.name) / 'plain'
        other.mkdir()
        cases = [
            ('baton_context', {'project_path': 'démo'}, 'absolute'),
            ('baton_context', {'project_path': str(other)}, 'not in a project set up with AI Baton'),
            ('baton_context', {'project_path': str(self.project / 'missing')}, 'existing absolute folder'),
            ('baton_context', {}, 'project_path is required'),
            ('baton_checkpoint', {'project_path': str(self.project), 'session_id': 'x', 'summary': '  '}, 'summary is required'),
            ('baton_checkpoint', {'project_path': str(self.project), 'summary': 'Did it.'}, 'session_id must be'),
            ('baton_checkpoint', {'project_path': str(self.project), 'session_id': '../../x', 'summary': 'a'}, 'session_id must be'),
            ('baton_recall', {'project_path': str(self.project), 'limit': 0}, 'limit must be'),
            ('baton_recall', {'project_path': str(self.project), 'agent': '../codex'}, 'agent must be'),
        ]
        for tool, arguments, message in cases:
            text, failed = c.call(tool, **arguments)
            self.assertTrue(failed, (tool, arguments, text))
            self.assertIn(message, text)
        self.assertFalse((self.project / '.agent-memory/copilot.json').exists(), 'no failed call saved anything')

    def test_review_runs_write_nothing(self):
        self.client.close()
        mem = self.project / '.agent-memory'

        def state():
            return sorted((str(f.relative_to(mem)), f.stat().st_mtime_ns) for f in mem.rglob('*')) if mem.exists() else []
        before = state()
        self.client = Client('--agent', 'copilot', env={'BATON_REVIEW': '1'})
        for tool, arguments in (('baton_context', {}), ('baton_checkpoint', {'session_id': 'copilot-1', 'summary': 'x'})):
            text, failed = self.client.call(tool, project_path=str(self.project), **arguments)
            self.assertTrue(failed, text)
            self.assertIn('baton review', text)
        self.assertFalse(self.client.call('baton_recall', project_path=str(self.project))[1])
        self.assertEqual(state(), before)

    def test_restarted_server_and_two_projects(self):
        c = self.client
        other = Path(self.tmp.name) / 'other'
        other.mkdir()
        init_project.init(other)
        sid = c.call('baton_context', project_path=str(self.project))[0].rsplit('session_id: ', 1)[1].split()[0]
        c.call('baton_checkpoint', project_path=str(self.project), session_id=sid, summary='First part.')
        elsewhere = c.call('baton_context', project_path=str(other))[0].rsplit('session_id: ', 1)[1].split()[0]
        c.call('baton_checkpoint', project_path=str(other), session_id=elsewhere, summary='Other project work.')
        self.assertNotIn('Other project', c.call('baton_context', project_path=str(self.project))[0])
        c.close()
        # The client reconnects to a new server process and keeps its conversation: it continues, and a handoff
        # update since the agent's last checkpoint is still noticed.
        handoff = self.project / 'docs/AGENT_HANDOFF.md'
        handoff.write_text(handoff.read_text(encoding='utf-8') + '\nMore.\n', encoding='utf-8')
        self.client = Client('--agent', 'copilot')
        text, failed = self.client.call('baton_checkpoint', project_path=str(self.project), session_id=sid,
                                        summary='Second part, after a restart.')
        self.assertFalse(failed, text)
        saved = read_json(self.project / '.agent-memory/copilot.json')
        self.assertEqual(saved['session_id'], sid)
        self.assertTrue(saved['handoff_updated'])

    def test_pinned_project_and_agent_ids(self):
        self.client.close()
        other = Path(self.tmp.name) / 'other'
        other.mkdir()
        init_project.init(other)
        self.client = Client('--agent', 'copilot', '--project', str(self.project))
        self.assertFalse(self.client.call('baton_context', project_path=str(self.project / 'docs'))[1])
        text, failed = self.client.call('baton_context', project_path=str(other))
        self.assertTrue(failed)
        self.assertIn('serves', text)
        for bad in ('seen', 'Copilot', '../x'):
            run = subprocess.run([sys.executable, str(ROOT / 'bin' / 'baton'), 'mcp', '--agent', bad],
                                 capture_output=True, text=True, input='')
            self.assertNotEqual(run.returncode, 0, bad)
            self.assertIn('invalid agent id', run.stderr)


class InstallMcpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user_dir = Path(self.tmp.name) / 'Code' / 'User'
        self.patch = mock.patch.object(mcp_install, 'vscode_user_dir', lambda: self.user_dir)
        self.patch.start()
        self.file = self.user_dir / 'mcp.json'
        self.project = Path(self.tmp.name) / 'p'
        self.project.mkdir()
        init_project.init(self.project)
        marker = self.project / '.baton.json'
        config = read_json(marker)
        config['extraAgents'] = [{'id': 'copilot', 'label': 'Copilot', 'extension': 'GitHub.copilot-chat',
                                  'openCommand': 'workbench.action.chat.open'}]
        marker.write_text(json.dumps(config))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_install_keeps_other_servers_and_uninstall_removes_only_ours(self):
        self.assertEqual(mcp_install.state('copilot', self.project), 'available')
        self.assertEqual(status.project_status(self.project)['agents'][-1]['mcp'], 'available')
        self.assertIsNone(status.project_status(self.project)['agents'][0]['mcp'], 'agents with hooks need no MCP')
        self.user_dir.mkdir(parents=True)
        self.file.write_text(json.dumps({'servers': {'playwright': {'type': 'stdio', 'command': 'npx'}},
                                         'inputs': [{'id': 'x'}]}))
        mcp_install.install('copilot', self.project)
        mcp_install.install('copilot', self.project)  # Again: still one entry.
        config = read_json(self.file)
        self.assertEqual(sorted(config['servers']), ['ai-baton', 'playwright'])
        self.assertEqual(config['inputs'], [{'id': 'x'}])
        entry = config['servers']['ai-baton']
        self.assertEqual((entry['type'], entry['args'][1:]), ('stdio', ['mcp', '--agent', 'copilot']))
        self.assertTrue(Path(entry['command']).is_absolute() and Path(entry['args'][0]).is_absolute())
        self.assertEqual(status.project_status(self.project)['agents'][-1]['mcp'], 'installed')
        # The written command really starts our server.
        run = subprocess.run([entry['command'], *entry['args']], capture_output=True, timeout=30,
                             input=b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        self.assertEqual(json.loads(run.stdout)['result'], {})

        self.assertEqual(len(mcp_install.uninstall(None, self.project)), 1)
        self.assertEqual(sorted(read_json(self.file)['servers']), ['playwright'])
        self.assertEqual(mcp_install.uninstall(None, self.project), [])

    def test_refuses_what_it_cannot_safely_change(self):
        self.user_dir.mkdir(parents=True)
        self.file.write_text('{\n  // my servers\n  "servers": {}\n}\n')
        with self.assertRaises(mcp_install.McpInstallError):
            mcp_install.install('copilot', self.project)
        self.assertIn('// my servers', self.file.read_text(), 'a file with comments is left as it was')
        self.file.write_text(json.dumps({'servers': {'ai-baton': {'command': 'something-else'}}}))
        with self.assertRaises(mcp_install.McpInstallError):
            mcp_install.install('copilot', self.project)
        self.assertEqual(mcp_install.uninstall(['copilot'], self.project), [], 'not ours: never removed')
        with self.assertRaises(mcp_install.McpInstallError) as raised:
            mcp_install.install('cody', self.project)
        self.assertIn('"--agent", "cody"', str(raised.exception), 'unsupported agents get the entry to add by hand')


class ContextBudgetTest(unittest.TestCase):
    def test_many_agents_stay_within_budget_and_the_rest_come_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_project.init(project)
            mem = project / '.agent-memory'
            mem.mkdir(exist_ok=True)
            for i in range(20):
                (mem / f'agent-{i:02d}.json').write_text(json.dumps({
                    'agent': f'agent-{i:02d}', 'saved_at': f'2026-10-27T10:{i:02d}:00+00:00',
                    'summary': f'agent {i:02d} ' + 'word ' * 300}))
            # Not checkpoints, or damaged ones: another agent's name inside, wrong types, a named pipe.
            (mem / 'shadowy.json').write_text(json.dumps({
                'agent': 'shadowy', 'saved_at': '2026-10-27T08:00:00+00:00', 'summary': 'shadowy survived',
                'changes': {'kind': 'shadow', 'changed': [5, None, 'M a.py'], 'changed_count': 'many'}}))
            if hasattr(os, 'mkfifo'):
                os.mkfifo(mem / 'piped.json')
            (mem / 'impostor.json').write_text(json.dumps({'agent': 'codex', 'saved_at': '2026-10-27T11:00:00+00:00'}))
            (mem / 'broken.json').write_text(json.dumps({'agent': 'broken', 'saved_at': 5}))
            (mem / 'odd.json').write_text(json.dumps({'agent': 'odd', 'saved_at': '2026-10-27T09:00:00+00:00',
                                                      'summary': ['x'], 'changes': {'changed': 'x'}}))
            with mock.patch.object(hook, 'MAX_OMITTED_AGENTS', 3):
                first = hook.build_context(mem, project, 'claude', 'SessionStart', 's1')
            notice = first.index('Below are local')
            self.assertLess(len(first) - notice, hook.HOT_BUDGET + 600)
            self.assertIn('agent 19', first, 'the newest come first')
            self.assertIn('agent-00, agent-01, agent-02 and 4 more.', first, 'the list of left-out agents is bounded')
            self.assertNotIn('impostor', first)
            self.assertNotIn('[codex]', first)
            self.assertIn('left out to keep this short', first)
            # What was left out was not marked as delivered: the next prompt brings it.
            later = hook.build_context(mem, project, 'claude', 'UserPromptSubmit', 's1')
            self.assertIn('agent 00', later)
            self.assertNotIn('agent 19', later)
            self.assertIn('shadowy survived', hook.build_context(mem, project, 'claude', 'SessionStart', 's2') +
                          hook.build_context(mem, project, 'claude', 'UserPromptSubmit', 's2') +
                          hook.build_context(mem, project, 'claude', 'UserPromptSubmit', 's2'))

    def test_one_huge_checkpoint_stays_within_budget(self):
        names = [f'M {"deep/" * 100}file{i}.py' for i in range(10)]
        shown, omitted = hook.fit_budget([{'agent': 'codex', 'saved_at': 'x', 'summary': 'word ' * 5000,
                                           'changes': {'kind': 'git', 'commit': 'abc', 'changed': names}}], 'claude')
        self.assertEqual(omitted, [])
        self.assertLessEqual(len(shown[0]), hook.HOT_BUDGET)
        shown, _ = hook.fit_budget([{'agent': 'codex', 'saved_at': 'x', 'summary': 'short',
                                     'changes': {'kind': 'git', 'commit': 'abc', 'changed': names}}], 'claude')
        self.assertLess(len(shown[0]), 10 * (hook.MAX_FILE_NAME + 2) + 200)


if __name__ == '__main__':
    unittest.main()
