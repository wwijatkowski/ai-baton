// Drives extension.js through its commands and panel messages against a fake VS Code API and a fake CLI (no agents,
// no Python, no network). Each test loads a fresh copy of the extension. Run: node tests/extension_flows.js
const assert = require('assert');
const cp = require('child_process');
const Module = require('module');
const path = require('path');

const EXTENSION = path.join(__dirname, '..', 'vscode-extension', 'extension.js');
const REGISTRY = require(path.join(__dirname, '..', 'baton', 'agents.json'));
const ROOT = path.join(path.sep, 'work', 'demo');
const CLI_HOME = path.join(path.sep, 'opt', 'baton');
const iso = (minutesAgo) => new Date(Date.now() - minutesAgo * 60000).toISOString();
const realExecFile = cp.execFile;
const realPlatform = Object.getOwnPropertyDescriptor(process, 'platform');

function sampleStatus(over = {}) {
  return {
    initialized: true, root: ROOT, path: ROOT, name: 'demo', last_agent: 'claude', recent: [], hidden_agents: [],
    agents: REGISTRY.map((a) => ({ ...a, checkpoint: { saved_at: iso(5) }, activity: { state: 'idle', at: iso(5) } })),
    docs: { handoff: { path: path.join(ROOT, 'docs', 'AGENT_HANDOFF.md') }, decisions: { path: path.join(ROOT, 'docs', 'knowledge', 'DECISIONS.md') } },
    ...over,
  };
}

const SESSIONS = [
  { agent: 'claude', session_id: 'claude-s1', client: 'claude-vscode', saved_at: iso(3), turns: 4, summary: 'Added the **retry** button.' },
  { agent: 'codex', session_id: 'codex-s1', client: 'codex_vscode', saved_at: iso(60), turns: 1, summary: 'Looked at the tests.' },
];

// One test's world: what the fake CLI answers, what the user clicks, and everything the extension did.
class Harness {
  constructor() {
    this.cli = {
      status: () => sampleStatus(),
      recent: () => ({ sessions: SESSIONS }),
      review: () => ({ review: '1. Fix the thing.', reviewed: 'the uncommitted changes' }),
    };
    this.cliCalls = [];
    this.execCalls = [];
    this.pythons = { python3: '3.11' };  // Interpreter command -> version it reports (missing: not installed).
    this.responders = [];
    this.dialogs = [];
    this.errors = [];
    this.executed = [];
    this.failing = new Set();
    this.clipboard = '';
    this.opened = [];
    this.documents = [];
    this.posted = [];
    this.commands = {};
    this.installed = new Set(REGISTRY.map((a) => a.extension));
    this.config = { home: CLI_HOME, python: 'python3', refreshSeconds: 3600, usageDays: 14, memoryTools: '' };
    this.configListeners = [];
    this.pending = 0;
    this.hung = [];
    this.memento = {};  // The extension's globalState.
    this.mcpProviders = {};
    this.allExtensions = [];
  }

  // A user setting changed (by this window or another one): every window gets the change event.
  setConfig(key, value) {
    this.config[key] = value === undefined ? '' : value;
    const change = { affectsConfiguration: (section) => section === 'aiBaton' || section === `aiBaton.${key}` };
    this.configListeners.forEach((fn) => fn(change));
  }

  // The user's answer to the next dialog of `kind` whose text matches `match` (used once).
  on(kind, match, answer) {
    this.responders.push({ kind, match, answer });
  }

  ask(kind, text, ...rest) {
    this.dialogs.push({ kind, text });
    const index = this.responders.findIndex((r) => r.kind === kind && r.match.test(text));
    if (index === -1) return undefined;  // Dismissed.
    const [responder] = this.responders.splice(index, 1);
    return typeof responder.answer === 'function' ? responder.answer(...rest) : responder.answer;
  }

  cliArgs(sub) {
    return this.cliCalls.filter((c) => c[0] === sub);
  }

  lastState() {
    const states = this.posted.filter((m) => m.type === 'state');
    return states.length ? states[states.length - 1].state : null;
  }

  fakeExecFile() {
    return (command, args, options, callback) => {
      if (typeof options === 'function') callback = options;
      this.execCalls.push([command, ...args]);
      const child = { pid: 4242, kill: () => this.endHung(child) };
      const reply = (error, stdout) => {
        this.pending++;
        setImmediate(() => {
          this.pending--;
          callback(error, stdout || '', error ? error.message : '');
        });
      };
      if (command === 'taskkill') {
        const target = this.hung.find((h) => String(h.child.pid) === args[args.indexOf('/PID') + 1]);
        if (target) this.endHung(target.child);
        reply(null, '');
        return child;
      }
      if (args.includes('-c')) {  // The Python version probe.
        const version = this.pythons[[command, ...args.slice(0, args.indexOf('-c'))].join(' ')];
        reply(version ? null : new Error(`spawn ${command} ENOENT`), version ? `${version}\n` : '');
        return child;
      }
      const at = args.findIndex((a) => a.endsWith(path.join('bin', 'baton')));
      const [sub, ...rest] = args.slice(at + 1);
      this.cliCalls.push([sub, ...rest]);
      let result;
      try {
        result = this.cli[sub] ? this.cli[sub](rest) : {};
      } catch (error) {
        reply(error);
        return child;
      }
      if (result === Harness.HANG) {
        this.pending++;
        this.hung.push({ child, callback });
      } else {
        reply(null, typeof result === 'string' ? result : JSON.stringify(result));
      }
      return child;
    };
  }

  endHung(child) {
    const index = this.hung.findIndex((h) => h.child === child);
    if (index === -1) return;
    const [{ callback }] = this.hung.splice(index, 1);
    this.pending--;
    this.killed = (this.killed || 0) + 1;
    setImmediate(() => callback(new Error('killed'), '', ''));
  }

  vscode() {
    const h = this;
    const event = () => () => ({ dispose() {} });
    const uri = (fsPath) => ({ fsPath, path: fsPath, toString: () => `file://${fsPath}` });
    return {
      Uri: { file: uri, parse: (text) => ({ text, toString: () => text }), joinPath: (base, ...parts) => uri(path.join(base.fsPath, ...parts)) },
      RelativePattern: class { constructor(base, pattern) { Object.assign(this, { base, pattern }); } },
      StatusBarAlignment: { Left: 1 },
      ProgressLocation: { Notification: 15 },
      ViewColumn: { Beside: -2 },
      QuickPickItemKind: { Separator: -1 },
      ConfigurationTarget: { Global: 1 },
      EventEmitter: class {
        constructor() { this.listeners = []; this.event = (fn) => { this.listeners.push(fn); return { dispose() {} }; }; }
        fire() { h.mcpFired = (h.mcpFired || 0) + 1; this.listeners.forEach((fn) => fn()); }
        dispose() {}
      },
      // Positional, like VS Code 1.143's implementation.
      McpStdioServerDefinition: h.noMcpApi ? undefined
        : class { constructor(label, command, args, env, version) { Object.assign(this, { label, command, args, env, version }); } },
      lm: h.noMcpApi ? undefined : {
        registerMcpServerDefinitionProvider: (id, provider) => { h.mcpProviders[id] = provider; return { dispose() {} }; },
      },
      window: {
        activeTextEditor: undefined,
        tabGroups: { all: [] },
        createOutputChannel: () => ({ appendLine() {}, show() {}, dispose() {} }),
        createStatusBarItem: () => ({ show() {}, hide() {}, dispose() {} }),
        registerWebviewViewProvider: (id, provider) => { h.provider = provider; return { dispose() {} }; },
        showInformationMessage: async (text, ...rest) => h.ask('info', text, ...rest),
        showWarningMessage: async (text, ...rest) => h.ask('warning', text, ...rest),
        showErrorMessage: async (text, ...rest) => { h.errors.push(text); return h.ask('error', text, ...rest); },
        showQuickPick: async (items, options) => h.ask('pick', `${options.title || ''} ${options.placeHolder || ''}`, items, options),
        showInputBox: async (options) => h.ask('input', `${options.title || ''} ${options.prompt}`, options),
        withProgress: async (options, task) => {
          const listeners = [];
          h.cancelProgress = () => listeners.forEach((fn) => fn());
          return task({ report() {} }, { onCancellationRequested: (fn) => { listeners.push(fn); return { dispose() {} }; } });
        },
        setStatusBarMessage: () => ({ dispose() {} }),
        showTextDocument: async (doc) => { h.shown = doc; },
        createWebviewPanel: () => { throw new Error('not used in these tests'); },
        onDidChangeActiveTextEditor: event(),
      },
      commands: {
        registerCommand: (id, fn) => { h.commands[id] = fn; return { dispose() {} }; },
        executeCommand: async (id, ...args) => {
          if (h.commands[id]) return h.commands[id](...args);
          h.executed.push([id, ...args]);
          if (h.failing.has(id)) throw new Error(`command '${id}' not found`);
        },
      },
      workspace: {
        workspaceFolders: [{ uri: uri(ROOT) }],
        getWorkspaceFolder: () => undefined,
        getConfiguration: () => ({ get: (key) => h.config[key], update: async (key, value) => h.setConfig(key, value) }),
        onDidChangeWorkspaceFolders: event(),
        onDidChangeConfiguration: (fn) => { h.configListeners.push(fn); return { dispose() {} }; },
        createFileSystemWatcher: () => ({ onDidChange() {}, onDidCreate() {}, dispose() {} }),
        openTextDocument: async (options) => { h.documents.push(options); return { uri: uri('/untitled-review'), ...options }; },
      },
      extensions: {
        all: h.allExtensions,
        getExtension: (id) => (h.installed.has(id) ? { id } : undefined),
        onDidChange: event(),
      },
      env: {
        uriScheme: 'vscode',
        clipboard: { writeText: async (text) => { h.clipboard = text; } },
        openExternal: async (target) => { h.opened.push(target.toString()); return true; },
      },
    };
  }

  // Activates a fresh copy of the extension and opens its panel.
  async start() {
    const vscode = this.vscode();
    const load = Module._load;
    Module._load = function (request, ...rest) {
      return request === 'vscode' ? vscode : load.call(this, request, ...rest);
    };
    cp.execFile = this.fakeExecFile();
    try {
      delete require.cache[require.resolve(EXTENSION)];
      this.extension = require(EXTENSION);
    } finally {
      Module._load = load;
    }
    const memento = this.memento;
    this.context = { extensionPath: path.dirname(EXTENSION), extensionUri: vscode.Uri.file(path.dirname(EXTENSION)), subscriptions: [],
      globalState: { get: (key) => memento[key], update: async (key, value) => { memento[key] = value; } } };
    await this.extension.activate(this.context);
    if (this.provider) {
      this.provider.resolveWebviewView({
        visible: true,
        onDidChangeVisibility: () => ({ dispose() {} }),
        webview: {
          options: {}, cspSource: 'csp', asWebviewUri: (u) => u,
          onDidReceiveMessage: (fn) => { this.panel = fn; },
          postMessage: (message) => this.posted.push(message),
        },
      });
      this.panel({ cmd: 'ready' });  // What panel.js sends once it has loaded.
    }
    await this.settle();
  }

  // Waits until every fake CLI call has answered and the extension has handled it.
  async settle() {
    for (let quiet = 0; quiet < 5;) {
      await new Promise((resolve) => setImmediate(resolve));
      quiet = this.pending - this.hung.length > 0 ? 0 : quiet + 1;
    }
  }

  stop() {
    for (const item of this.context ? this.context.subscriptions : []) item.dispose();
  }
}
Harness.HANG = Symbol('hang');

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

// ---------- activation and the panel ----------

test('activation refreshes the status and the panel shows it', async (h) => {
  await h.start();
  assert.ok(h.commands['aiBaton.askForReview'], 'commands are registered');
  assert.deepStrictEqual(h.cliArgs('status')[0], ['status', '--json', ROOT]);
  const state = h.lastState();
  assert.strictEqual(state.error, null);
  assert.deepStrictEqual(state.status.agents.map((a) => a.id), ['claude', 'codex']);
  assert.ok(state.status.agents.every((a) => a.installed));
});

test('a CLI that prints something other than JSON is reported in the panel', async (h) => {
  h.cli.status = () => 'Traceback (most recent call last): oops';
  await h.start();
  assert.match(h.lastState().error, /^Could not run baton:/);
});

test('without Python nothing runs and the panel says how to fix it', async (h) => {
  h.pythons = {};
  await h.start();
  assert.strictEqual(h.cliCalls.length, 0);
  assert.match(h.lastState().error, /needs Python 3\.9 or newer/);
  assert.match(h.errors[0], /aiBaton\.python/);
});

test('too old a Python is named with its version', async (h) => {
  h.pythons = { python3: '3.8' };
  await h.start();
  assert.match(h.lastState().error, /"python3" is 3\.8/);
});

test('on Windows the py launcher or python is used when python3 is missing', async (h) => {
  Object.defineProperty(process, 'platform', { value: 'win32' });
  h.pythons = { python: '3.12' };  // `py -3` and `python3` are not installed.
  await h.start();
  assert.strictEqual(h.lastState().error, null);
  const status = h.execCalls.find((c) => c.includes('status'));
  assert.strictEqual(status[0], 'python');
});

test('on Windows Python 3.11 is the minimum (older ones cannot start in a hook)', async (h) => {
  Object.defineProperty(process, 'platform', { value: 'win32' });
  h.pythons = { 'py -3': '3.10' };
  await h.start();
  assert.match(h.lastState().error, /needs Python 3\.11 or newer; "python3" is 3\.10/);
});

// ---------- agents ----------

test('New chat passes left-out arguments as undefined, never null', async (h) => {
  await h.start();
  await h.panel({ cmd: 'new', agent: 'claude' });
  const [id, ...args] = h.executed.find((c) => c[0] === 'claude-vscode.editor.open');
  assert.strictEqual(id, 'claude-vscode.editor.open');
  assert.strictEqual(args.length, 6);
  assert.ok(args.slice(0, 5).every((a) => a === undefined));
  assert.deepStrictEqual(args[5], { programmatic: 'pin-to-panel' });
});

test('an agent command that fails is shown as an error, not a dead button', async (h) => {
  h.failing.add('chatgpt.openSidebar');
  await h.start();
  await h.panel({ cmd: 'open', agent: 'codex' });
  assert.match(h.errors[0], /^Could not open Codex: command 'chatgpt.openSidebar' not found/);
});

test('switching while another agent works asks first', async (h) => {
  h.cli.status = () => {
    const status = sampleStatus();
    status.agents[1].activity = { state: 'working', at: iso(1) };
    return status;
  };
  await h.start();
  await h.panel({ cmd: 'open', agent: 'claude' });
  assert.ok(h.dialogs.some((d) => d.kind === 'warning' && /Codex is still working/.test(d.text)));
  assert.ok(!h.executed.some((c) => c[0] === 'claude-vscode.sidebar.open'), 'dismissed: stays put');
});

const COPILOT = { id: 'copilot', label: 'Copilot', extension: 'GitHub.copilot-chat', openCommand: 'workbench.action.chat.open',
  source: 'user', checkpoint: null, activity: null };
const withCopilot = (h) => {
  h.installed.add('GitHub.copilot-chat');
  h.cli.status = () => sampleStatus({ agents: [...sampleStatus().agents, COPILOT] });
};

test('Copilot hooks: installed from its card after a consent naming the terminal; then no context request is copied', async (h) => {
  h.installed.add('GitHub.copilot-chat');
  const copilot = { ...COPILOT, hooks: 'copilot' };
  h.cli.status = () => sampleStatus({ agents: [...sampleStatus().agents, copilot] });
  let hooks = 'missing';
  h.cli['hook-status'] = () => ({ copilot: { state: hooks } });
  h.cli['install-hooks'] = () => { hooks = 'ok'; return '~ ai-baton.json'; };
  await h.start();
  await h.panel({ cmd: 'open', agent: 'copilot' });
  assert.match(h.clipboard, /AGENTS\.md/, 'hooks not installed yet: the context request is copied');
  h.clipboard = '';
  h.on('info', /^Install AI Baton memory hooks for Copilot once/, 'Install');
  await h.panel({ cmd: 'installHooks', agent: 'copilot' });
  await h.settle();
  assert.ok(h.dialogs.some((d) => /also run for Copilot in a terminal/.test(d.text)));
  assert.deepStrictEqual(h.cliArgs('install-hooks'), [['install-hooks', '--agents=copilot']]);
  assert.ok(h.dialogs.some((d) => /^Copilot hooks installed/.test(d.text)));
  await h.panel({ cmd: 'open', agent: 'copilot' });
  assert.strictEqual(h.clipboard, '', 'its hooks deliver the context');
});

test('Connect memory offers AI Baton\'s MCP server to Copilot; Disconnect withdraws it', async (h) => {
  withCopilot(h);
  await h.start();
  const provider = h.mcpProviders['aiBaton.memory'];
  assert.ok(provider, 'registered under the id package.json contributes');
  assert.deepStrictEqual(await provider.provideMcpServerDefinitions(), [], 'off until connected');
  assert.deepStrictEqual(h.lastState().mcp, { agents: ['copilot'], connected: null, available: false }, 'only Copilot can connect');
  await h.panel({ cmd: 'open', agent: 'copilot' });
  assert.match(h.clipboard, /AGENTS\.md/, 'not connected yet: the context request is copied');

  h.clipboard = '';
  const fired = h.mcpFired;
  await h.panel({ cmd: 'connectMemory', agent: 'copilot' });
  await h.settle();
  assert.strictEqual(h.config.memoryTools, 'copilot', 'a user setting, which every window sees');
  assert.ok(h.mcpFired > fired, 'VS Code is told');
  const [server] = await provider.provideMcpServerDefinitions();
  assert.strictEqual(server.label, 'AI Baton');
  assert.strictEqual(server.command, 'python3');
  assert.deepStrictEqual(server.args, [path.join(CLI_HOME, 'bin', 'baton'), 'mcp', '--agent', 'copilot']);
  assert.match(server.version, /^\d+\.\d+\.\d+$/);
  assert.strictEqual(await provider.resolveMcpServerDefinition(server), server);
  assert.deepStrictEqual(h.lastState().mcp, { agents: ['copilot'], connected: 'copilot', available: true });
  assert.ok(h.dialogs.some((d) => d.kind === 'info' && /It decides when to call them/.test(d.text)));
  await h.panel({ cmd: 'open', agent: 'copilot' });
  assert.strictEqual(h.clipboard, '', 'connected: nothing to paste');

  // Disconnect in another window: this one hears the setting change, and a definition VS Code still holds won't start.
  const before = h.mcpFired;
  h.setConfig('memoryTools', '');
  assert.ok(h.mcpFired > before);
  assert.deepStrictEqual(await provider.provideMcpServerDefinitions(), []);
  assert.strictEqual(await provider.resolveMcpServerDefinition(server), undefined);
  assert.strictEqual(h.lastState().mcp.connected, null);
});

test('removing the connected agent also disconnects its memory tools', async (h) => {
  withCopilot(h);
  h.config.memoryTools = 'copilot';
  h.on('warning', /Remove Copilot from AI Baton/, 'Remove');
  await h.start();
  assert.strictEqual((await h.mcpProviders['aiBaton.memory'].provideMcpServerDefinitions()).length, 1);
  await h.panel({ cmd: 'removeAgent', agent: 'copilot' });
  await h.settle();
  assert.deepStrictEqual(h.cliArgs('remove-agent')[0], ['remove-agent', 'copilot']);
  assert.strictEqual(h.config.memoryTools, '');
  assert.deepStrictEqual(await h.mcpProviders['aiBaton.memory'].provideMcpServerDefinitions(), []);
});

test('when AI Baton stops working, the memory tools are withdrawn and the context request is back', async (h) => {
  withCopilot(h);
  h.config.memoryTools = 'copilot';
  await h.start();
  const provider = h.mcpProviders['aiBaton.memory'];
  const [server] = await provider.provideMcpServerDefinitions();
  h.pythons = {};  // The Python setting now points at nothing.
  const before = h.mcpFired;
  h.setConfig('python', 'python9');
  await h.settle();
  assert.ok(h.mcpFired > before, 'VS Code is told when the server can no longer run');
  assert.deepStrictEqual(await provider.provideMcpServerDefinitions(), []);
  assert.strictEqual(await provider.resolveMcpServerDefinition(server), undefined);
  assert.deepStrictEqual(h.lastState().mcp, { agents: ['copilot'], connected: 'copilot', available: false });
  await h.panel({ cmd: 'open', agent: 'copilot' });
  assert.match(h.clipboard, /AGENTS\.md/, 'tools unavailable: the context request is copied again');
});

test('Add agent offers the built-in Copilot Chat, but no other built-in extension', async (h) => {
  const ext = (id, pkg) => ({ id, packageJSON: { categories: ['AI', 'Chat'], ...pkg } });
  h.allExtensions.push(ext('GitHub.copilot-chat', { isBuiltin: true, displayName: 'GitHub Copilot Chat' }),
    ext('vscode.some-ai-thing', { isBuiltin: true, displayName: 'Built-in AI thing',
      contributes: { viewsContainers: { panel: [{ id: 'thing' }] } } }));
  let offered;
  h.on('pick', /Add which installed agent/, (items) => { offered = items.map((i) => i.label); return items[0]; });
  await h.start();
  await h.commands['aiBaton.addAgent']();
  assert.deepStrictEqual(offered.filter((l) => !l.includes('Find AI agents')), ['$(hubot) Copilot']);
  assert.deepStrictEqual(JSON.parse(h.cliArgs('add-agent')[0][1]), { id: 'copilot', label: 'Copilot',
    extension: 'GitHub.copilot-chat', openCommand: 'workbench.action.chat.open', newCommand: 'workbench.action.chat.newChat' });
});

test('without VS Code\'s MCP provider API nothing is offered and activation still works', async (h) => {
  h.noMcpApi = true;
  await h.start();
  assert.strictEqual(h.lastState().mcp, null);
  assert.strictEqual(h.lastState().error, null);
});

// ---------- initialize ----------

test('Initialize installs missing user hooks once, then sets the project up', async (h) => {
  h.cli.status = () => sampleStatus({ initialized: false });
  h.cli['hook-status'] = (args) => (args.includes('--user') ? { claude: { state: 'missing' }, codex: { state: 'ok' } } : {});
  h.on('info', /^Set up demo for AI Baton/, 'Initialize');
  h.on('info', /^Install AI Baton memory hooks for Claude once/, 'Install');
  await h.start();
  await h.commands['aiBaton.initProject']();
  await h.settle();
  assert.deepStrictEqual(h.cliArgs('install-hooks'), [['install-hooks', '--agents=claude']]);
  assert.deepStrictEqual(h.cliArgs('init'), [['init', ROOT, '--agents=claude,codex']]);
  assert.ok(h.dialogs.some((d) => /^Project ready\. Start a new Claude conversation\./.test(d.text)));
});

test('Initialize does nothing when not confirmed', async (h) => {
  h.cli.status = () => sampleStatus({ initialized: false });
  await h.start();
  await h.commands['aiBaton.initProject']();
  assert.strictEqual(h.cliArgs('init').length, 0);
  assert.strictEqual(h.cliArgs('install-hooks').length, 0);
});

// ---------- ask for review ----------

const pickSession = (id) => (items) => items.find((i) => i.entry && i.entry.session_id === id);
const pickReviewer = (id) => (items) => items.find((i) => i.agent.id === id);

for (const step of [1, 2, 3]) {
  test(`Ask for review cancelled at step ${step} runs no review`, async (h) => {
    if (step > 1) h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
    if (step > 2) h.on('pick', /\(2\/3\)/, pickReviewer('codex'));
    await h.start();
    await h.commands['aiBaton.askForReview']();
    assert.strictEqual(h.cliArgs('review').length, 0);
    assert.strictEqual(h.errors.length, 0);
  });
}

test('Ask for review: whose work, a different reviewer by default, focus, then Send back', async (h) => {
  let reviewers;
  h.on('pick', /\(1\/3\)/, (items) => {
    assert.strictEqual(items[items.length - 1].label, '$(circle-slash) No particular conversation');
    return pickSession('claude-s1')(items);
  });
  h.on('pick', /\(2\/3\): who reviews Claude's work/, (items) => { reviewers = items; return items[0]; });
  h.on('input', /\(3\/3\)/, '  error handling  ');
  h.on('info', /Codex's review is ready\. Send it back to Claude's conversation/, 'Send to Claude');
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.deepStrictEqual(reviewers.map((r) => r.agent.id), ['codex', 'claude'], 'the author comes last');
  assert.match(reviewers[1].description, /self-review/);
  assert.deepStrictEqual(h.cliArgs('review')[0],
    ['review', '--json', '--agent', 'codex', '--path', ROOT, '--focus', 'error handling', '--session', 'claude-s1']);
  const doc = h.documents[0];
  assert.strictEqual(doc.language, 'markdown');
  assert.match(doc.content, /^# Review by Codex\n\n- Reviewed: the uncommitted changes\n- Work of: Claude, conversation from .*\n- Focus: error handling\n\n1\. Fix the thing\.\n$/);
  assert.match(h.clipboard, /^Codex reviewed the uncommitted changes\. Check each point/);
  assert.deepStrictEqual(h.opened, ['vscode://anthropic.claude-code/open?session=claude-s1']);
});

test('Ask for review with no particular conversation offers no Send', async (h) => {
  h.on('pick', /\(1\/3\)/, (items) => items[items.length - 1]);
  h.on('pick', /\(2\/3\): who reviews\?/, pickReviewer('claude'));
  h.on('input', /\(3\/3\)/, '');
  h.on('info', /review is ready/, (...buttons) => { h.buttons = buttons; return undefined; });
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.deepStrictEqual(h.cliArgs('review')[0], ['review', '--json', '--agent', 'claude', '--path', ROOT]);
  assert.deepStrictEqual(h.buttons, ['Copy review']);
});

test('Ask for review from Recent work skips the first step', async (h) => {
  h.on('pick', /\(2\/3\): who reviews Codex's work/, pickReviewer('claude'));
  h.on('input', /\(3\/3\)/, '');
  await h.start();
  await h.panel({ cmd: 'review', entry: SESSIONS[1] });
  await h.settle();
  assert.ok(!h.dialogs.some((d) => /\(1\/3\)/.test(d.text)));
  assert.deepStrictEqual(h.cliArgs('review')[0].slice(-2), ['--session', 'codex-s1']);
});

test('Ask for review without any conversation goes straight to the reviewer', async (h) => {
  h.cli.recent = () => ({ sessions: [] });
  h.on('pick', /\(2\/3\)/, (items, options) => { h.placeholder = options.placeHolder; return items[0]; });
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.ok(!h.dialogs.some((d) => /\(1\/3\)/.test(d.text)));
  assert.match(h.placeholder, /No conversation here yet/);
});

test('Ask for review with another model and effort, offered again next time', async (h) => {
  h.cli.models = () => ({ claude: { model: '', effort: 'high', efforts: ['low', 'medium', 'high'], defaultLabel: 'set by your plan',
    options: [{ value: 'opus', label: 'Opus' }, { value: 'sonnet', label: 'Sonnet' }] } });
  let reviewers;
  h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
  h.on('pick', /\(2\/3\)/, (items) => { reviewers = items; return items.find((i) => i.choose && i.agent.id === 'claude'); });
  h.on('pick', /Claude reviews with which model/, (items) => {
    assert.strictEqual(items[0].label, 'Default (default (set by your plan) · high)');
    return items.find((i) => i.value === 'sonnet');
  });
  h.on('pick', /Claude · Sonnet reviews with which effort/, (items) => {
    assert.deepStrictEqual(items.map((i) => i.label), ['Default (high)', 'low', 'medium', 'high']);
    return items[1];
  });
  h.on('input', /\(3\/3\)/, '');
  await h.start();
  await h.commands['aiBaton.askForReview']();
  // Codex has no model settings here: it is offered as configured only.
  assert.deepStrictEqual(reviewers.map((r) => [r.agent.id, !!r.choose]), [['codex', false], ['claude', false], ['claude', true]]);
  assert.deepStrictEqual(h.cliArgs('review')[0], ['review', '--json', '--agent', 'claude', '--path', ROOT,
    '--model', 'sonnet', '--effort', 'low', '--session', 'claude-s1']);
  assert.match(h.documents[0].content, /^# Review by Claude \(Sonnet · low\)\n/);

  h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
  h.on('pick', /\(2\/3\)/, (items) => items.find((i) => i.label === '$(history) Claude · Sonnet · low'));
  h.on('input', /\(3\/3\)/, '');
  await h.commands['aiBaton.askForReview']();
  assert.deepStrictEqual(h.cliArgs('review')[1].slice(6, 10), ['--model', 'sonnet', '--effort', 'low']);
});

test('Ask for review with a model id typed by hand', async (h) => {
  h.cli.models = () => ({ claude: { model: '', effort: '', efforts: ['low', 'high'], defaultLabel: 'set by your plan',
    options: [{ value: 'opus', label: 'Opus' }] } });
  let check;
  h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
  h.on('pick', /\(2\/3\)/, (items) => items.find((i) => i.choose && i.agent.id === 'claude'));
  h.on('pick', /Claude reviews with which model/, (items) => items[items.length - 1]);
  h.on('input', /Claude reviews with which model/, (options) => { check = options.validateInput; return ' claude-opus-4-1 '; });
  h.on('pick', /Claude · claude-opus-4-1 reviews with which effort/, (items) => items[0]);
  h.on('input', /\(3\/3\)/, '');
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.strictEqual(check('--help'), 'Letters, digits and . : [ ] - _ only (not starting with -), up to 80 characters.');
  assert.strictEqual(check('a b'), 'Letters, digits and . : [ ] - _ only (not starting with -), up to 80 characters.');
  assert.strictEqual(check('opus[1m]'), null);
  assert.deepStrictEqual(h.cliArgs('review')[0].slice(6, 8), ['--model', 'claude-opus-4-1']);
});

test('a review choice is remembered only once the review has run', async (h) => {
  h.cli.models = () => ({ codex: { model: 'mini', effort: '', efforts: ['low', 'high'], defaultLabel: '',
    options: [{ value: 'mini', label: 'Mini', efforts: ['low'] }, { value: 'big', label: 'Big', efforts: ['low', 'high'] }] } });
  h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
  h.on('pick', /\(2\/3\)/, (items) => items.find((i) => i.choose));
  h.on('pick', /Codex reviews with which model/, (items) => items[0]);
  // "Default" runs the configured model, so only its efforts are offered.
  h.on('pick', /Codex reviews with which effort/, (items) => { h.efforts = items.map((i) => i.value); return items[1]; });
  h.on('input', /\(3\/3\)/, undefined);
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.deepStrictEqual(h.efforts, ['', 'low']);
  assert.strictEqual(h.cliArgs('review').length, 0);
  assert.deepStrictEqual(h.memento, {}, 'cancelled before running: nothing remembered');
});

test('a failed review is shown as an error', async (h) => {
  h.cli.review = () => { throw new Error('Error: codex failed (exit 1): at capacity'); };
  h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
  h.on('pick', /\(2\/3\)/, pickReviewer('codex'));
  h.on('input', /\(3\/3\)/, '');
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.deepStrictEqual(h.errors, ['Review failed: codex failed (exit 1): at capacity']);
  assert.strictEqual(h.documents.length, 0);
});

for (const platform of ['linux', 'win32']) {
  test(`cancelling a running review stops the CLI quietly (${platform})`, async (h) => {
    Object.defineProperty(process, 'platform', { value: platform });
    h.pythons = { python3: '3.11', python: '3.11' };
    h.cli.review = () => Harness.HANG;
    h.on('pick', /\(1\/3\)/, pickSession('claude-s1'));
    h.on('pick', /\(2\/3\)/, pickReviewer('codex'));
    h.on('input', /\(3\/3\)/, '');
    await h.start();
    const running = h.commands['aiBaton.askForReview']();
    await h.settle();
    assert.strictEqual(h.hung.length, 1, 'the review is running');
    h.cancelProgress();
    await running;
    assert.strictEqual(h.killed, 1);
    // Windows: the whole process tree, so the reviewer the CLI started goes too.
    assert.strictEqual(h.execCalls.some((c) => c[0] === 'taskkill' && c.includes('/T')), platform === 'win32');
    assert.deepStrictEqual(h.errors, []);
    assert.strictEqual(h.documents.length, 0);
  });
}

test('a CLI call that runs too long is stopped and reported (tree kill on Windows)', async (h) => {
  Object.defineProperty(process, 'platform', { value: 'win32' });
  h.pythons = { python: '3.11' };
  h.cli.models = () => Harness.HANG;  // A hung CLI: refreshModels waits on it.
  const realSetTimeout = global.setTimeout;
  global.setTimeout = (fn, ms, ...rest) => realSetTimeout(fn, ms >= 300000 ? 0 : ms, ...rest);  // CLI time limit now.
  try {
    await h.start();
    await new Promise((resolve) => realSetTimeout(resolve, 50));  // Let the shortened timers fire.
    await h.settle();
  } finally {
    global.setTimeout = realSetTimeout;
  }
  assert.strictEqual(h.hung.length, 0);
  assert.ok(h.execCalls.some((c) => c[0] === 'taskkill' && c.includes('/T')));
});

test('Ask for review needs an initialized project and an installed reviewer', async (h) => {
  h.installed = new Set();
  h.cli.status = () => sampleStatus({ agents: sampleStatus().agents });  // Checkpoints keep them listed.
  await h.start();
  await h.commands['aiBaton.askForReview']();
  assert.ok(h.dialogs.some((d) => d.kind === 'warning' && /No installed agent can review yet/.test(d.text)));
});

(async () => {
  let failed = 0;
  for (const { name, fn } of tests) {
    const h = new Harness();
    // The same on every runner: Linux unless a test picks another system.
    Object.defineProperty(process, 'platform', { value: 'linux' });
    try {
      await fn(h);
      console.log(`ok   ${name}`);
    } catch (error) {
      failed++;
      console.error(`FAIL ${name}\n${error.stack}`);
    } finally {
      h.stop();
      cp.execFile = realExecFile;
      Object.defineProperty(process, 'platform', realPlatform);
    }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
