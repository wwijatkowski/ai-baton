// Reads Copilot's events.jsonl for the live test. Written apart from baton/hook.py's copilot_reply on purpose: the
// test must not share the code it checks. Only what the assertions need: one turn's final answer, its tool calls,
// and the hook runs of the whole conversation.
const fs = require('fs');
const path = require('path');

function readEvents(file) {
  const events = [];
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      // A line still being written.
    }
  }
  return events;
}

// The conversation whose events hold a user message with exactly this text (each query carries a random sentinel).
function findSession(sessionState, query) {
  if (!fs.existsSync(sessionState)) return null;
  for (const id of fs.readdirSync(sessionState)) {
    const file = path.join(sessionState, id, 'events.jsonl');
    if (!fs.existsSync(file)) continue;
    const events = readEvents(file);
    if (events.some((e) => e.type === 'user.message' && e.data && e.data.content === query)) return { id, file, events };
  }
  return null;
}

// The turn that starts at the user message with this text, up to the next user message.
function turn(events, query) {
  const start = events.findIndex((e) => e.type === 'user.message' && e.data && e.data.content === query);
  if (start < 0) return null;
  let end = events.findIndex((e, i) => i > start && e.type === 'user.message');
  if (end < 0) end = events.length;
  const inside = events.slice(start + 1, end);
  const finals = inside.filter((e) => e.type === 'assistant.message' && e.data && e.data.phase === 'final_answer');
  return {
    final: finals.length ? finals[finals.length - 1].data : null,
    tools: inside.filter((e) => e.type === 'tool.execution_start').map((e) => e.data.toolName),
    ended: inside.some((e) => e.type === 'assistant.turn_end'),
    errors: inside.filter((e) => /error/i.test(e.type)).map((e) => ({ type: e.type, data: e.data })),
  };
}

function hookRuns(events, hookType) {
  const starts = events.filter((e) => e.type === 'hook.start' && e.data && e.data.hookType === hookType);
  return starts.map((e) => {
    const end = events.find((x) => x.type === 'hook.end' && x.data && x.data.hookInvocationId === e.data.hookInvocationId);
    const output = end && end.data.output;
    return { source: e.data.input && e.data.input.source, success: end ? end.data.success : null,
      context: output && typeof output.additionalContext === 'string' ? output.additionalContext : '' };
  });
}

function sessionId(events) {
  const start = events.find((e) => e.type === 'session.start');
  return start && start.data ? start.data.sessionId : null;
}

module.exports = { readEvents, findSession, turn, hookRuns, sessionId };
