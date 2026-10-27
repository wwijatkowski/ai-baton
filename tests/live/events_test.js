// The live test's own events.jsonl parser (run by tests/test_core.py; no VS Code, no Copilot).
const assert = require('assert');
const { parseEvents, turn } = require('./events');

const line = (e) => `${JSON.stringify(e)}\n`;
const user = (content) => line({ type: 'user.message', data: { content } });
const hook = (id, kind, context) => line({ type: 'hook.start', data: { hookInvocationId: id, hookType: kind, input: { source: 'resume' } } }) +
  line({ type: 'hook.end', data: { hookInvocationId: id, hookType: kind, success: true, output: { additionalContext: context } } });
const final = (content, messageId) => line({ type: 'assistant.message', data: { phase: 'final_answer', content, messageId } });
const tool = line({ type: 'tool.execution_start', data: { toolCallId: 'c1', toolName: 'read_file', arguments: { path: 'a' } } }) +
  line({ type: 'tool.execution_complete', data: { toolCallId: 'c1', success: true, result: { content: 'TEXT' } } });
const end = line({ type: 'assistant.turn_end', data: {} });

const text = user('q1') + hook('h1', 'sessionStart', 'OLD') + final('A', 'm1') + end +
  user('q2') + hook('h2', 'sessionStart', 'NEW') + tool + final('B', 'm2') + end;

// Each turn has its own final answer, tools and hook runs.
const t1 = turn(parseEvents(text), 'q1');
assert.deepStrictEqual([t1.final.messageId, t1.tools, t1.sessionStarts.map((s) => s.context)], ['m1', [], ['OLD']]);
const t2 = turn(parseEvents(text), 'q2');
assert.deepStrictEqual([t2.final.messageId, t2.tools, t2.sessionStarts.map((s) => s.context), t2.ended], ['m2', ['read_file'], ['NEW'], true]);
assert.deepStrictEqual(t2.calls, [{ name: 'read_file', args: { path: 'a' }, success: true, result: 'TEXT' }]);
assert.deepStrictEqual(t1.calls, []);

// An unfinished last record is skipped; a damaged complete one is an error (it could hide the tool call).
assert.strictEqual(turn(parseEvents(text + '{"type": "assistant.mes'), 'q2').final.messageId, 'm2');
const damaged = text.replace(tool, '{"type": "tool.execution_start", "da\n');
assert.throws(() => parseEvents(damaged), /damaged record on line 9/);

console.log('events.js parser tests passed');
