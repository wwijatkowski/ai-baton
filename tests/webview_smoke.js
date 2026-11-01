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
// Context size per conversation on the agent's card: named as in the agent's chat list, a warning past the threshold
// (which can be dismissed), and the same names in Recent work.
const context = (c) => ({ agent: 'claude', session: 's1-aaaaaaaa-bbbb', title: 'Fix the login', model: 'opus', tokens: 600000, window: 1000000, at: iso(3), compactions: 0, compacted: false, ...c });
const withContexts = (list, contextWarning = 50, titles = {}) => ({ ...state, contextWarning, projectUsage: { ...state.usage, contexts: list, titles } });
const claudeCard = () => panel.app.all().find((e) => e.className === 'card' && e.textContent.includes('Claude'));
const chat = (name) => claudeCard().all().find((e) => e.className === 'chat' && e.textContent.includes(name));
const contextWarning = () => panel.app.all().find((e) => e.className === 'warning small' && e.textContent.includes('re-reads'));
panel.send({ type: 'state', state: withContexts([context(), context({ session: 's2-cccccccc-dddd', title: null, tokens: 100000 }), context({ agent: 'codex', session: 'c' })],
  50, { 'abc-1': 'Fix the login' }), root: '/p' });
check('panel, large context', panel.app);
const login = chat('Fix the login');
if (!login || !login.textContent.includes('Context 600k of 1.0M') || !login.textContent.includes('60%') || !contextWarning() || !contextWarning().textContent.includes('/clear')) {
  failures.push('panel: no named chat with its size and a warning saying what to do');
}
if (!chat('Chat s2-ccccc') || !chat('Chat s2-ccccc').textContent.includes('Context 100k of 1.0M')) failures.push('panel: a chat without a title is not shown by its short id');
if (panel.app.all().filter((e) => e.className === 'warning small' && e.textContent.includes('re-reads')).length !== 1) {
  failures.push('panel: a context warning shown for a small context or a hidden agent');
}
panel.posted.length = 0;
const openLogin = button(login, 'Open');
if (openLogin.attrs['aria-label'] !== 'Open conversation: Fix the login' || !String(login.attrs.title).startsWith('Fix the login\n')) {
  failures.push('panel: a chat\'s Open button or tooltip does not name the chat');
}
openLogin.click();
if (!panel.posted.some((m) => m.cmd === 'session' && m.agent === 'claude' && m.session === 's1-aaaaaaaa-bbbb')) failures.push('panel: Open on a chat does not open that conversation');
const fresh = button(login, 'Continue fresh');
if (!fresh || fresh.attrs['aria-label'] !== 'Continue fresh from: Fix the login' || !contextWarning().textContent.includes('or use Continue fresh')) {
  failures.push('panel: a chat has no Continue fresh button, or the warning does not mention it');
}
fresh.click();
if (!panel.posted.some((m) => m.cmd === 'continue' && m.agent === 'claude' && m.session === 's1-aaaaaaaa-bbbb')) failures.push('panel: Continue fresh does not send that conversation');
button(contextWarning(), 'Dismiss').click();
if (contextWarning() || !chat('Fix the login')) failures.push('panel: Dismiss did not hide only the warning');
if (!button(panel.app, 'Recent work').textContent.startsWith('▾')) button(panel.app, 'Recent work').click();
if (!panel.app.all().some((e) => e.className === 'entry' && e.all().some((c) => c.className === 'chat-title' && c.textContent === 'Fix the login'))) {
  failures.push('panel: Recent work does not name the chat of an entry');
}
panel.send({ type: 'state', state: withContexts([context({ session: 's3' })], 0), root: '/p' });
if (contextWarning()) failures.push('panel: context warning shown although turned off');
panel.send({ type: 'state', state: withContexts([context({ session: 's4', window: null, tokens: 300000 })]), root: '/p' });
if (contextWarning() || !chat('Fix the login').textContent.includes('Context 300k') || chat('Fix the login').all().some((e) => e.className === 'track')) {
  failures.push('panel: unknown window not shown as a plain number');
}
panel.send({ type: 'state', state: withContexts([context({ session: 's5', compacted: true, compactions: 2 })]), root: '/p' });
if (contextWarning() || !claudeCard().textContent.includes('just compacted') || !claudeCard().textContent.includes('compacted 2×')) {
  failures.push('panel: a just compacted conversation is not shown as such');
}
panel.send({ type: 'state', state: withContexts([1, 2, 3, 4, 5].map((n) => context({ session: `n${n}`, title: `T${n}`, tokens: 1000 }))), root: '/p' });
if (!claudeCard().textContent.includes('+2 more conversations') || chat('T4')) failures.push('panel: more than three conversations not summarized');
panel.send({ type: 'state', state: withContexts([1, 2, 3, 4].map((n) => context({ session: `big${n}`, title: `B${n}`, tokens: n === 4 ? 900000 : 1000 }))), root: '/p' });
if (!contextWarning() || !chat('B4')) failures.push('panel: a large older conversation hidden behind "+N more"');
const chatOrder = () => claudeCard().all().filter((e) => e.className === 'chat-title').map((e) => e.textContent).join(' ');
if (chatOrder() !== 'B1 B2 B4') failures.push(`panel: conversations not newest first with a warned one kept (got ${chatOrder()})`);
panel.send({ type: 'state', state: withContexts([context({ session: 'new', title: 'Fresh', tokens: 70000 }), context({ session: 'old', title: 'Old' })]), root: '/p' });
if (chatOrder() !== 'Fresh Old') failures.push('panel: a warned older conversation listed above a newer one');
// A section that throws shows its own error; the rest of the panel still renders and responds.
const errors = [];
const consoleError = console.error;
console.error = (e) => errors.push(e);
try {
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
} finally {
  console.error = consoleError;
}
panel.send({ type: 'state', state, root: '/p' });
check('panel, recovered after a failing section', panel.app);
if (panel.app.textContent.includes('Could not show this section')) failures.push('panel: did not recover once the data was valid');

const recent = load('recent.js');
check('recent, loading', recent.app);
const agents = [{ id: 'claude', label: 'Claude', shown: true, sessions: true }, { id: 'codex', label: 'Codex', shown: false }];
recent.send({ type: 'recent', data: { name: 'p', sessions: sessions.map((e, i) => ({ ...e, title: i ? null : 'Fix the login' })), agents, canReview: true } });
check('recent', recent.app);
if (!recent.app.all().some((e) => e.className === 'chat-title' && e.textContent === 'Fix the login')) failures.push('recent: an entry does not show its chat title');
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
search.value = 'fix the LOGIN';
search.listeners.input.forEach((fn) => fn({ target: search }));
if (!recent.app.textContent.includes('Built the thing')) failures.push('recent: search does not find a chat by its title');
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
