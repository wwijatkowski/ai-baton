// Reads Copilot's events.jsonl for the live test. Written apart from baton/hook.py's copilot_reply on purpose: the
// test must not share the code it checks. Only what the assertions need: one turn's final answer, its tool calls
// (with their arguments and results) and its hook runs.
const fs = require('fs');
const path = require('path');

// Only a last line without its newline may be unreadable (still being written); a damaged complete line could hide
// a tool call or a reply, so it is an error.
function parseEvents(text) {
  const lines = text.split('\n');
  const unfinished = lines.pop();
  const events = [];
  lines.forEach((line, i) => {
    if (!line.trim()) return;
    try {
      events.push(JSON.parse(line));
    } catch {
      throw new Error(`events.jsonl: damaged record on line ${i + 1}`);
    }
  });
  if (unfinished.trim()) {
    try {
      events.push(JSON.parse(unfinished));
    } catch {
      // Still being written.
    }
  }
  return events;
}

const readEvents = (file) => parseEvents(fs.readFileSync(file, 'utf8'));

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

function hookRuns(events, hookType) {
  const starts = events.filter((e) => e.type === 'hook.start' && e.data && e.data.hookType === hookType);
  return starts.map((e) => {
    const end = events.find((x) => x.type === 'hook.end' && x.data && x.data.hookInvocationId === e.data.hookInvocationId);
    const output = end && end.data.output;
    return { source: e.data.input && e.data.input.source, success: end ? end.data.success : null,
      context: output && typeof output.additionalContext === 'string' ? output.additionalContext : '' };
  });
}

// The turn that starts at the user message with this text, up to the next user message. Its hooks are the ones
// started inside it (Copilot runs SessionStart right after the user message).
function turn(events, query) {
  const start = events.findIndex((e) => e.type === 'user.message' && e.data && e.data.content === query);
  if (start < 0) return null;
  let end = events.findIndex((e, i) => i > start && e.type === 'user.message');
  if (end < 0) end = events.length;
  const inside = events.slice(start + 1, end);
  const finals = inside.filter((e) => e.type === 'assistant.message' && e.data && e.data.phase === 'final_answer');
  return {
    final: finals.length ? finals[finals.length - 1].data : null,
    tools: inside.filter((e) => e.type === 'tool.execution_start').map((e) => e.data && e.data.toolName),
    calls: inside.filter((e) => e.type === 'tool.execution_start' && e.data).map((e) => {
      const done = inside.find((x) => x.type === 'tool.execution_complete' && x.data && x.data.toolCallId === e.data.toolCallId);
      const result = done && done.data.result;
      return { name: e.data.toolName, args: e.data.arguments || {}, success: done ? done.data.success : null,
        result: result && typeof result.content === 'string' ? result.content : '' };
    }),
    ended: inside.some((e) => e.type === 'assistant.turn_end'),
    sessionStarts: hookRuns(inside, 'sessionStart'),
    errors: inside.filter((e) => /error/i.test(e.type)).map((e) => ({ type: e.type, data: e.data })),
  };
}

function sessionId(events) {
  const start = events.find((e) => e.type === 'session.start');
  return start && start.data ? start.data.sessionId : null;
}

module.exports = { parseEvents, readEvents, findSession, turn, hookRuns, sessionId };
