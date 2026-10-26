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
panel.send({ type: 'state', state: { ...state, hooks: { claude: { state: 'missing' } } }, root: '/p' });
check('panel, hooks missing', panel.app);
if (!button(panel.app, 'Install hooks')) failures.push('panel: no "Install hooks" button');
panel.send({ type: 'state', state: { ...state, hooks: null }, root: '/p' });
check('panel, no hook info', panel.app);
panel.send({ type: 'state', state: { ...state, status: { initialized: false, path: '/q', agents: [], hidden_agents: [] }, usage: null, projectUsage: null }, root: '/q' });
check('panel, new folder', panel.app);

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
