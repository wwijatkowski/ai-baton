// Renders the webviews (panel.js, recent.js) against sample state in a tiny fake DOM and fails on
// leaked values such as "false" or "[object HTMLElement]". Run: node tests/webview_smoke.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const MEDIA = path.join(__dirname, '..', 'vscode-extension', 'media');
const LEAKS = /\bfalse\b|\bundefined\b|\[object|\bNaN\b|Invalid Date/;

class Text {
  constructor(text) { this.text = text; this.nodeType = 3; }
  get textContent() { return this.text; }
}

// Mirrors the DOM where it matters: append/replaceChildren turn anything that is not a node into text.
class El {
  constructor(tag) {
    Object.assign(this, { nodeType: 1, tag, children: [], attrs: {}, style: {}, className: '', listeners: {}, offsetWidth: 0, value: '' });
  }
  append(...items) { for (const x of items) this.children.push(x instanceof El || x instanceof Text ? x : new Text(String(x))); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'value') this.value = String(value); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  get textContent() { return this.children.map((c) => c.textContent).join(''); }
  set textContent(value) { this.children = [new Text(String(value))]; }
  toString() { return '[object HTMLElement]'; }
  querySelector() { return this.all().find((e) => e.tag === 'input') || null; }
  focus() {}
  setSelectionRange() {}
  all() { return [this, ...this.children.filter((c) => c instanceof El).flatMap((c) => c.all())]; }
  click() { for (const fn of this.listeners.click || []) fn({ target: this }); }
}

function load(script) {
  const nodes = { app: new El('div'), tip: new El('div') };
  const handlers = [];
  const posted = [];
  const context = {
    document: {
      body: new El('body'),
      getElementById: (id) => nodes[id],
      createElement: (tag) => new El(tag),
      createElementNS: (ns, tag) => new El(tag),
    },
    window: { addEventListener: (type, fn) => type === 'message' && handlers.push(fn), innerWidth: 800 },
    acquireVsCodeApi: () => ({ postMessage: (m) => posted.push(m) }),
    getComputedStyle: () => ({ getPropertyValue: () => '#888888' }),
    console,
  };
  vm.runInNewContext(fs.readFileSync(path.join(MEDIA, script), 'utf8'), context, { filename: script });
  return { app: nodes.app, posted, send: (data) => handlers.forEach((fn) => fn({ data })) };
}

const now = new Date();
const iso = (minutesAgo) => new Date(now - minutesAgo * 60000).toISOString();
const sessions = [
  { agent: 'claude', session_id: 'abc-1', started: iso(90), saved_at: iso(2), turns: 5, commit: 'abc1234', branch: 'main', handoff_updated: true, summary: '**Built** the `thing`. ### 1. Next step' },
  { agent: 'codex', started: iso(3000), saved_at: iso(3000), turns: 1, commit: null, branch: null, handoff_updated: false, summary: '' },
];
const tokens = { input: 10, cache_write: 5, output: 20, cache_read: 100 };
const day = now.toLocaleDateString('sv-SE');
const state = {
  scope: 'project',
  loading: false,
  error: null,
  status: {
    initialized: true, root: '/p', name: 'p', last_agent: 'claude',
    agents: [
      { id: 'claude', label: 'Claude', hooks: 'claude', newCommand: 'x', usageView: 'v', sessionUri: 'u', review: 'claude', installed: true, activity: { state: 'working', at: iso(1) },
        checkpoint: { saved_at: iso(2), branch: 'main', commit: 'abc1234', summary: 'Built the thing.' } },
      { id: 'cline', label: 'Cline', source: 'user', activity: null, checkpoint: null },
      { id: 'copilot', label: 'Copilot', source: 'user', activity: null, checkpoint: null },
    ],
    hidden_agents: [{ id: 'codex', label: 'Codex' }],
    docs: Object.fromEntries(['handoff', 'status', 'decisions', 'agents'].map((k) => [k, { path: `/p/${k}.md`, updated: k === 'agents' ? null : iso(5) }])),
    recent: sessions,
    recent_total: 12,
  },
  models: {
    claude: { model: '', effort: '', defaultLabel: 'last used: Opus', defaultEffort: '', efforts: ['low', 'high'],
      options: [{ value: 'opus', label: 'Opus', description: 'd' }] },
  },
  usage: {
    days: 14,
    agents: { claude: { today: tokens, week: tokens, by_day: [{ day, ...tokens }] }, codex: { today: tokens, week: tokens, by_day: [] } },
    limits: {
      claude: { claude: { at: iso(18 * 60), primary: { used_percent: 15, resets_at: null, expired: true }, secondary: { used_percent: 3, resets_at: now / 1000 + 9999, expired: false } } },
      codex: { codex: { at: iso(10), plan_type: 'plus', primary: { used_percent: 1, resets_at: now / 1000 + 999, expired: false } } },
    },
  },
};
state.projectUsage = state.usage;
state.hooks = { claude: { state: 'untrusted', detail: 'not approved yet' }, cline: { state: 'ok' } };

const failures = [];
function check(name, app) {
  const text = app.textContent;
  const leak = text.match(LEAKS);
  if (leak) failures.push(`${name}: leaked "${leak[0]}" in: …${text.slice(Math.max(0, leak.index - 60), leak.index + 40)}…`);
  if (!text.trim()) failures.push(`${name}: rendered nothing`);
}
const button = (app, label) => app.all().find((e) => e.tag === 'button' && e.textContent.includes(label));

const panel = load('panel.js');
panel.send({ type: 'state', state, root: '/p' });
check('panel', panel.app);
if (/\bcodex\b/.test(panel.app.textContent)) failures.push('panel: hidden agent shown by id ("codex") instead of its label');
button(panel.app, 'Recent work').click();
check('panel, recent work open', panel.app);
button(panel.app, 'Built the thing').click();
check('panel, entry expanded', panel.app);
if (!button(panel.app, 'Show all 12')) failures.push('panel: no "Show all 12" button');
if (!button(panel.app, 'Open session')) failures.push('panel: no "Open session" button');
if (!button(panel.app, 'Ask for review')) failures.push('panel: no "Ask for review" button');
if (panel.app.all().filter((e) => e.tag === 'button' && e.textContent === 'Ask for review').length < 2) {
  failures.push('panel: no "Ask for review" on the expanded Recent work entry');
}
if (!button(panel.app, 'Approve in Claude')) failures.push('panel: no hook approval button');
panel.send({ type: 'state', state: { ...state, mcp: { agents: ['copilot'], connected: null, available: false } }, root: '/p' });
if (!button(panel.app, 'Connect memory')) failures.push('panel: no "Connect memory" for Copilot');
panel.send({ type: 'state', state: { ...state, mcp: { agents: ['copilot'], connected: 'copilot', available: true } }, root: '/p' });
if (!button(panel.app, 'Disconnect') || button(panel.app, 'Connect memory')) failures.push('panel: connected Copilot not shown as connected');
panel.send({ type: 'state', state: { ...state, mcp: { agents: ['copilot'], connected: 'copilot', available: false } }, root: '/p' });
if (!panel.app.textContent.includes('unavailable until AI Baton works again')) failures.push('panel: unavailable memory tools not explained');
// A review running now: its own badge, never mistaken for work.
panel.send({ type: 'state', state: { ...state, status: { ...state.status, agents: state.status.agents.map((a) => (a.id === 'claude'
  ? { ...a, activity: null, reviewing: { model: 'sonnet', effort: 'high', started: iso(1) } } : a)) } }, root: '/p' });
check('panel, reviewing', panel.app);
const reviewing = panel.app.all().find((e) => e.className === 'badge reviewing');
if (!reviewing || !/Reviewing \(read-only\), started .* · sonnet · high/.test(reviewing.attrs.title || '')) failures.push(`panel: no reviewing badge with its model (${reviewing && reviewing.attrs.title})`);
if (panel.app.all().some((e) => e.className === 'badge last')) failures.push('panel: "last" shown next to "reviewing"');
// Copilot with its own hooks: hooks and memory tools in all four combinations.
const withCopilotHooks = (hookState, connected) => ({ ...state,
  status: { ...state.status, agents: state.status.agents.map((a) => (a.id === 'copilot' ? { ...a, hooks: 'copilot' } : a)) },
  hooks: { ...state.hooks, copilot: { state: hookState } }, mcp: { agents: ['copilot'], connected, available: true } });
const copilotCard = () => panel.app.all().find((e) => e.className === 'card' && e.textContent.includes('Copilot'));
panel.send({ type: 'state', state: withCopilotHooks('missing', null), root: '/p' });
check('panel, Copilot without hooks or tools', panel.app);
if (!button(copilotCard(), 'Install hooks') || !button(copilotCard(), 'Connect memory')) failures.push('panel: Copilot without hooks lacks Install hooks / Connect memory');
if (copilotCard().textContent.includes('No memory hooks, so')) failures.push('panel: Copilot warned twice about missing hooks');
panel.send({ type: 'state', state: withCopilotHooks('missing', 'copilot'), root: '/p' });
if (!button(copilotCard(), 'Install hooks') || !button(copilotCard(), 'Disconnect') || button(copilotCard(), 'Connect memory')) failures.push('panel: Copilot with tools only');
panel.send({ type: 'state', state: withCopilotHooks('ok', 'copilot'), root: '/p' });
if (!copilotCard().textContent.includes('Memory hooks and tools on') || button(copilotCard(), 'Install hooks')) failures.push('panel: Copilot with hooks and tools');
if (!copilotCard().textContent.includes('not in Local ones')) failures.push('panel: Copilot with hooks and tools does not say Local chats run no hooks');
panel.send({ type: 'state', state: withCopilotHooks('ok', null), root: '/p' });
check('panel, Copilot with hooks only', panel.app);
if (button(copilotCard(), 'Install hooks') || copilotCard().textContent.includes('does not share memory')) failures.push('panel: Copilot with hooks only shows a warning');
if (!button(copilotCard(), 'Connect memory tools')) failures.push('panel: Copilot with hooks only cannot add the memory tools');
if (!copilotCard().textContent.includes('Copilot CLI chats (Local chats get none)')) failures.push('panel: Copilot with hooks only does not say Local chats run no hooks');
panel.send({ type: 'state', state, root: '/p' });
panel.send({ type: 'state', state: { ...state, hooks: { claude: { state: 'missing' } } }, root: '/p' });
check('panel, hooks missing', panel.app);
if (!button(panel.app, 'Install hooks')) failures.push('panel: no "Install hooks" button');
panel.send({ type: 'state', state: { ...state, hooks: null }, root: '/p' });
check('panel, no hook info', panel.app);
panel.send({ type: 'state', state: { ...state, status: { initialized: false, path: '/q', agents: [], hidden_agents: [] }, usage: null, projectUsage: null }, root: '/q' });
check('panel, new folder', panel.app);
// Claude saves no reset time for a 5-hour window that has not started: this once froze the whole panel.
const unstarted = { ...state.usage, limits: { claude: { claude: { at: iso(5), primary: { used_percent: 0, resets_at: null, expired: false } } } } };
panel.send({ type: 'state', state: { ...state, usage: unstarted, projectUsage: unstarted }, root: '/p' });
check('panel, window not started', panel.app);
if (!panel.app.textContent.includes('No reset time yet')) failures.push('panel: a window without a reset time is not shown');
// A section that throws shows its own error; the rest of the panel still renders and responds.
const errors = [];
const consoleError = console.error;
console.error = (e) => errors.push(e);
panel.send({ type: 'state', state: { ...state, usage: { ...state.usage, agents: null }, projectUsage: null }, root: '/p' });
if (!errors.length) failures.push('panel: the broken usage data did not throw, so section isolation went untested');
if (!panel.app.textContent.includes('Could not show this section')) failures.push('panel: a failing section shows no error');
const fold = button(panel.app, 'Recent work');
if (!fold) failures.push('panel: a failing section hid the rest of the panel');
else {
  const open = fold.textContent.startsWith('▾');
  fold.click();
  if (button(panel.app, 'Recent work').textContent.startsWith('▾') === open) failures.push('panel: Recent work stopped responding after a failing section');
}
panel.send({ type: 'state', state, root: '/p' });
check('panel, recovered after a failing section', panel.app);
if (panel.app.textContent.includes('Could not show this section')) failures.push('panel: did not recover once the data was valid');

const recent = load('recent.js');
check('recent, loading', recent.app);
const agents = [{ id: 'claude', label: 'Claude', shown: true, sessions: true }, { id: 'codex', label: 'Codex', shown: false }];
recent.send({ type: 'recent', data: { name: 'p', sessions, agents, canReview: true } });
check('recent', recent.app);
button(recent.app, '5 replies').click();
if (!button(recent.app, 'Open session')) failures.push('recent: no "Open session" button');
if (!button(recent.app, 'Ask for review')) failures.push('recent: no "Ask for review" button');
button(recent.app, 'Claude').click();
check('recent, filtered', recent.app);
button(recent.app, 'All').click();
const search = recent.app.all().find((e) => e.tag === 'input');
search.value = 'nothing like this';
search.listeners.input.forEach((fn) => fn({ target: search }));
if (!recent.app.textContent.includes('No sessions match')) failures.push('recent: search did not filter');
search.value = 'built';
search.listeners.input.forEach((fn) => fn({ target: search }));
if (!recent.app.textContent.includes('Built the thing')) failures.push('recent: search lost a match');
if (/\*\*|`|###/.test(recent.app.textContent)) failures.push('recent: raw Markdown in summaries');
recent.send({ type: 'recent', data: { name: 'p', sessions: [], agents } });
check('recent, empty', recent.app);
recent.send({ type: 'recent', data: { error: 'Not set up.' } });
check('recent, error', recent.app);

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log('webviews render cleanly');
