// Live test with the real Copilot in a real VS Code: does the hook context reach the model, are replies saved, what
// happens over several turns, after a reload and in a new chat. Opt-in and local: it sends real Copilot messages (at
// most MAX_MESSAGES per round) and needs a GitHub sign-in once. Never part of CI.
//
// Everything lives in ~/.cache/ai-baton/live/: a VS Code profile (user-data, extensions) that keeps the sign-in, and
// a separate HOME for the whole VS Code process (so COPILOT_HOME, ~/.ai-baton and the hooks are the test's own; your
// VS Code, ~/.copilot and chats are untouched; on macOS the login keychain is shared, see linkKeychains). The AI Baton .vsix is built from this checkout and installed there.
// A small driver extension (tests/live/driver) sends chat messages and reloads the window on request.
//
//   node tests/live/run.js setup            open the test window once and sign in to GitHub (Copilot), then close it
//   node tests/live/run.js round [--keep] [--no-build]   run a round (4 messages); --keep leaves the test project
//   node tests/live/run.js clean            delete the whole test profile, sign-in included (not keychain items)
//   node tests/live/run.js probe [regex]    list matching VS Code commands (no Copilot messages)
//
// VS Code: BATON_LIVE_CODE (the `code` CLI), else the macOS app or `code` on PATH.
const cp = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const ev = require('./events');

const ROOT = path.join(__dirname, '..', '..');
const LIVE = path.join(os.homedir(), '.cache', 'ai-baton', 'live');
const USER_DATA = path.join(LIVE, 'user-data');
const EXTENSIONS = path.join(LIVE, 'extensions');
const HOME = path.join(LIVE, 'home');
const COPILOT_HOME = path.join(HOME, '.copilot');
const DRIVER = path.join(__dirname, 'driver');
const PYTHON = process.platform === 'win32' ? 'python' : 'python3';
const MAX_MESSAGES = 8;
const CHAT_TIMEOUT = 300000;
// A new Copilot CLI chat in the chat view: the runtime (copilot-agent) that runs Copilot's hooks. The plain
// workbench.action.chat.newChat opens a "Local" chat, which runs none.
const NEW_CHAT = 'workbench.action.chat.openNewChatSessionInPlace.copilotcli';

function codeCli() {
  if (process.env.BATON_LIVE_CODE) return process.env.BATON_LIVE_CODE;
  const mac = '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code';
  return fs.existsSync(mac) ? mac : 'code';
}

// The environment of the test VS Code: none of the calling editor's or agent's variables (VSCODE_IPC_HOOK_CLI
// would send the window to your own VS Code), and the test's own HOME and COPILOT_HOME.
function testEnv(extra = {}) {
  const env = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (!/^(VSCODE_|ELECTRON_|CLAUDE|COPILOT_|CODEX_|BATON_)/.test(key)) env[key] = value;
  }
  return { ...env, HOME, USERPROFILE: HOME, COPILOT_HOME, ...extra };
}

const profileArgs = () => ['--user-data-dir', USER_DATA, '--extensions-dir', EXTENSIONS];

function writeSettings() {
  const file = path.join(USER_DATA, 'User', 'settings.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  let settings = {};
  try {
    settings = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    // New profile (or one with comments: rewritten with the keys below).
  }
  Object.assign(settings, {
    'workbench.startupEditor': 'none',
    'update.mode': 'none',
    'telemetry.telemetryLevel': 'off',
    'security.workspace.trust.enabled': false,
    'extensions.autoUpdate': false,
    'extensions.autoCheckUpdates': false,
  });
  fs.writeFileSync(file, JSON.stringify(settings, null, 2));
}

// macOS finds the login keychain through HOME; without it VS Code cannot keep the sign-in ("Keychain Not Found").
// So the test HOME links your real ~/Library/Keychains: the test VS Code shares your login keychain (and VS Code's
// encryption key in it); the GitHub token is kept, encrypted with that key, in the test profile. `clean` deletes the
// profile, not keychain items. Credentials are not separated from your account; that would take another macOS user.
function linkKeychains() {
  if (process.platform !== 'darwin') return;
  const link = path.join(HOME, 'Library', 'Keychains');
  if (fs.existsSync(link)) return;
  fs.mkdirSync(path.dirname(link), { recursive: true });
  fs.symlinkSync(path.join(os.homedir(), 'Library', 'Keychains'), link);
}

// The app itself, not the `code` script: the window must be this process's own. A test VS Code that is already
// running would take the new window with its own (older) environment, so it is refused.
function electron() {
  const cli = codeCli();
  const mac = cli.match(/^(.*\.app)\/Contents\/Resources\/app\/bin\/code$/);
  return mac ? path.join(mac[1], 'Contents', 'MacOS', path.basename(mac[1], '.app') === 'Visual Studio Code' ? 'Code' : 'Electron') : cli;
}

function running() {
  try {
    return cp.execFileSync('pgrep', ['-f', '--', `--user-data-dir[= ]${USER_DATA}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

function launch(io, folder) {
  const pids = running();
  if (pids) throw new Error(`the test VS Code is still running (pid ${pids.split('\n').join(', ')}): close it first`);
  fs.mkdirSync(HOME, { recursive: true });
  linkKeychains();
  writeSettings();
  const args = [...profileArgs(), '--extensionDevelopmentPath', DRIVER, '--new-window', '--skip-welcome',
    '--skip-release-notes', '--disable-workspace-trust',
    // VS Code's own test flag: a reload or quit with a Copilot CLI chat open would otherwise ask "A session is in
    // progress" and wait for a click.
    ...(io ? ['--enable-smoke-test-driver'] : []), ...(folder ? [folder] : [])];
  const child = cp.spawn(electron(), args, { env: testEnv(io ? { BATON_LIVE_IO: io } : {}), stdio: 'ignore' });
  child.exited = new Promise((resolve) => child.on('exit', resolve));
  return child;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// One runner at a time, and none while the test VS Code runs: checked before anything is installed or deleted.
function exclusive() {
  fs.mkdirSync(LIVE, { recursive: true });
  const lock = path.join(LIVE, 'runner.lock');
  for (;;) {
    try {
      fs.writeFileSync(lock, String(process.pid), { flag: 'wx' });
      break;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const pid = Number(fs.readFileSync(lock, 'utf8'));
      let alive = false;
      try {
        process.kill(pid, 0);
        alive = true;
      } catch {
        // Left by a runner that died.
      }
      if (alive) throw new Error(`another live test runs (pid ${pid})`);
      fs.rmSync(lock, { force: true });
    }
  }
  process.on('exit', () => fs.rmSync(lock, { force: true }));
  const pids = running();
  if (pids) throw new Error(`the test VS Code is still running (pid ${pids.split('\n').join(', ')}): close it first`);
}

// Ends the test VS Code: quit through the driver, then SIGTERM, then SIGKILL, each bounded. True once nothing of it
// is left running.
async function stop(window, driver) {
  if (driver) await driver.send({ op: 'quit' }, 10000).catch(() => {});
  for (const signal of [null, 'SIGTERM', 'SIGKILL']) {
    if (signal && window.exitCode === null && window.signalCode === null) window.kill(signal);
    await Promise.race([window.exited, sleep(signal ? 5000 : 15000)]);
    if (!running()) return true;
    if (signal === 'SIGKILL') cp.spawnSync('pkill', ['-9', '-f', '--', `--user-data-dir[= ]${USER_DATA}`]);
  }
  await sleep(2000);
  return !running();
}

async function waitFor(read, ms, what) {
  const deadline = Date.now() + ms;
  for (;;) {
    const value = read();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timed out: ${what}`);
    await sleep(500);
  }
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

class Driver {
  constructor(io) {
    this.io = io;
    this.count = 0;
    this.messages = 0;
  }

  generation() {
    return (readJson(path.join(this.io, 'ready.json')) || {}).generation || 0;
  }

  async ready(after, ms = 120000) {
    await waitFor(() => this.generation() > after, ms, 'the driver extension did not start (window not open?)');
  }

  async send(command, ms = 60000) {
    if (command.op === 'chat' && ++this.messages > MAX_MESSAGES) throw new Error(`more than ${MAX_MESSAGES} Copilot messages`);
    const name = `${String(++this.count).padStart(4, '0')}-${command.op}.json`;
    const file = path.join(this.io, 'inbox', name);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(`${file}.tmp`, JSON.stringify(command));
    fs.renameSync(`${file}.tmp`, file);
    const answer = await waitFor(() => readJson(path.join(this.io, 'outbox', name)), ms, `no answer to ${command.op}`);
    if (!answer.ok) throw new Error(`${command.op} failed in VS Code: ${answer.error}`);
    return answer.result;
  }
}

function buildVsix(noBuild) {
  const version = JSON.parse(fs.readFileSync(path.join(ROOT, 'vscode-extension', 'package.json'), 'utf8')).version;
  const vsix = path.join(ROOT, `ai-baton-${version}.vsix`);
  if (!noBuild || !fs.existsSync(vsix)) cp.execFileSync('sh', [path.join(ROOT, 'scripts', 'package.sh')], { stdio: 'inherit' });
  const build = cp.execFileSync('unzip', ['-p', vsix, 'extension/cli/BUILD'], { encoding: 'utf8' }).trim();
  return { vsix, version, build };
}

function installVsix(vsix) {
  cp.execFileSync(codeCli(), [...profileArgs(), '--install-extension', vsix, '--force'], { env: testEnv(), stdio: 'inherit' });
}

const randomName = () => {
  const words = ['AMBER', 'COBALT', 'CRIMSON', 'JADE', 'SILVER', 'ONYX', 'SAFFRON', 'TEAL'];
  const animals = ['LYNX', 'HERON', 'MARTEN', 'IBEX', 'OSPREY', 'TAPIR', 'VIPER', 'WREN'];
  const pick = (list) => list[crypto.randomInt(list.length)];
  return `${pick(words)}-${pick(animals)}-${crypto.randomInt(1000, 10000)}`;
};

async function round(options) {
  exclusive();
  const { vsix, version, build } = buildVsix(options.noBuild);
  installVsix(vsix);
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const dir = path.join(LIVE, 'rounds', stamp);
  const io = path.join(dir, 'io');
  const project = path.join(dir, 'live project');  // A space, as real folders have.
  fs.mkdirSync(project, { recursive: true });
  const results = [];
  const check = (kind, name, ok, detail = '') => {
    results.push({ kind, name, ok, detail });
    console.log(`${kind === 'INFO' ? 'INFO' : ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `: ${detail}` : ''}`);
  };
  const launcher = path.join(HOME, '.ai-baton', 'bin', 'baton');
  const baton = (args, input) => cp.execFileSync(PYTHON, [launcher, ...args], { env: testEnv(), input, encoding: 'utf8' });
  const mem = path.join(project, '.agent-memory');
  const copilotSaved = () => readJson(path.join(mem, 'copilot.json')) || {};
  const copilotHistory = () => {
    if (!fs.existsSync(path.join(mem, 'history.jsonl'))) return [];
    return fs.readFileSync(path.join(mem, 'history.jsonl'), 'utf8').split('\n')
      .map(readJsonLine).filter((entry) => entry && entry.agent === 'copilot');
  };
  const replies = [];  // {label, id, messageId} of every reply, for the duplicate check at the end.
  let seeds = 0;
  const seed = (codename) => baton(['hook', 'codex'], JSON.stringify({
    cwd: project, hook_event_name: 'Stop', session_id: `seed-${++seeds}`, transcript_path: '',
    last_assistant_message: `Codex renamed the project's codename to ${codename}.`,
  }));
  const sessionState = path.join(COPILOT_HOME, 'session-state');
  const driver = new Driver(io);
  const window = launch(io, project);

  // One message; returns what its turn shows in events.jsonl, checked against what the Stop hook saved.
  const ask = async (label, text) => {
    const query = `[${label}-${crypto.randomBytes(3).toString('hex')}] ${text}`;
    const returned = await driver.send({ op: 'chat', query }, CHAT_TIMEOUT);
    const session = await waitFor(() => {
      const found = ev.findSession(sessionState, query);
      return found && ev.turn(found.events, query).ended && found;
    }, 60000, `${label}: the message never reached Copilot's events.jsonl (chat.open contract changed?)`);
    const t = ev.turn(session.events, query);
    if (!t.final) throw new Error(`${label}: no final answer (sign-in, quota or model error?): ${JSON.stringify(t.errors).slice(0, 800)}`);
    const reply = t.final.content.trim();
    const id = ev.sessionId(session.events);
    check('ASSERT', `${label}: no tools used`, t.tools.length === 0, t.tools.join(', '));
    const record = await waitFor(() => {
      const current = copilotSaved();
      return current.message_id === t.final.messageId && current;
    }, 20000, `${label}: the Stop hook did not save this reply`).catch((error) => ({ error: error.message }));
    // These replies are one short codename: the saved text must be exactly the reply.
    check('ASSERT', `${label}: reply saved by the Stop hook`, !record.error && record.session_id === id && reply !== '' &&
      String(record.last_reply || '').trim() === reply, record.error || `session ${id}, saved "${String(record.last_reply).slice(0, 80)}"`);
    const entries = copilotHistory().filter((e) => e.message_id === t.final.messageId);
    check('ASSERT', `${label}: one history entry for this reply`, entries.length === 1 && entries[0].session_id === id,
      `${entries.length} entries`);
    replies.push({ label, id, messageId: t.final.messageId });
    return { query, reply, id, sessionStarts: t.sessionStarts, returned };
  };
  const knows = (reply, codename) => reply.toUpperCase().includes(codename);

  try {
    await driver.ready(0);
    const info = await driver.send({ op: 'info' });
    console.log(`VS Code ${info.vscode}, Copilot Chat ${info.copilotChat}, AI Baton ${info.baton && info.baton.version}`);
    if (!Array.isArray(info.models) || !info.models.length) {
      throw new Error(`no Copilot models (${JSON.stringify(info.models)}): sign in once with node tests/live/run.js setup`);
    }
    check('ASSERT', 'the window runs the .vsix just built', info.baton && info.baton.version === version && info.baton.build === build,
      JSON.stringify(info.baton));
    const installed = await waitFor(() => {
      try {
        return fs.readFileSync(path.join(HOME, '.ai-baton', 'current-version'), 'utf8').trim();
      } catch {
        return null;
      }
    }, 60000, 'the extension did not install its CLI');
    check('ASSERT', 'the bundled CLI is installed in the test HOME', installed === `${version}-${build}`, installed);
    baton(['init', project, '--agents=']);
    // As Add agent on the panel registers it; install-hooks only installs for a registered Copilot.
    baton(['add-agent', JSON.stringify({ id: 'copilot', label: 'Copilot', extension: 'github.copilot-chat',
      openCommand: 'workbench.action.chat.open', newCommand: 'workbench.action.chat.newChat' })]);
    baton(['install-hooks', '--agents=copilot']);
    check('ASSERT', 'Copilot hooks installed in the test COPILOT_HOME', fs.existsSync(path.join(COPILOT_HOME, 'hooks', 'ai-baton.json')));

    // 1. A new chat: the codename exists only in Codex's checkpoint, so only the SessionStart context can carry it.
    const first = randomName();
    seed(first);
    await driver.send({ op: 'command', id: NEW_CHAT, args: ['sidebar'] });
    const t1 = await ask('t1', "What is this project's current codename, according to your AI Baton context? " +
      'Answer with the codename only. Do not read files or use any tools.');
    check('ASSERT', 't1: the hook context reached the model', knows(t1.reply, first), `expected ${first}, got "${t1.reply.slice(0, 200)}"`);
    check('ASSERT', 't1: SessionStart ran in this turn and succeeded', t1.sessionStarts.length >= 1 && t1.sessionStarts.every((s) => s.success),
      JSON.stringify(t1.sessionStarts.map((s) => [s.source, s.success])));
    check('ASSERT', "t1: SessionStart's context carried the codename", t1.sessionStarts.some((s) => s.context.includes(first)));

    // 2. Same chat, a newer checkpoint: does Copilot run SessionStart again on a later turn?
    const second = randomName();
    seed(second);
    const followUp = "Has another agent changed the project's codename since this conversation started? " +
      'Answer with the current codename only. Do not read files or use any tools.';
    const t2 = await ask('t2', followUp);
    check('ASSERT', 't2: same conversation', t2.id === t1.id, `${t1.id} / ${t2.id}`);
    // Copilot runs SessionStart (source resume) on every turn: a later turn gets newer checkpoints.
    check('ASSERT', "t2: this turn's SessionStart carried the newer codename",
      t2.sessionStarts.some((s) => s.success && s.context.includes(second)), JSON.stringify(t2.sessionStarts.map((s) => [s.source, s.success])));
    check('ASSERT', 't2: knows the newer codename', knows(t2.reply, second), `expected ${second}, got "${t2.reply.slice(0, 200)}"`);

    // 3. Reload the window, then the open chat again.
    const third = randomName();
    seed(third);
    // t2's Stop hook is done once Copilot has closed the session.
    await waitFor(() => {
      const found = ev.findSession(sessionState, t2.query);
      const events = found ? found.events : [];
      return events.length && events[events.length - 1].type === 'session.shutdown';
    }, 30000, 'the Copilot session did not shut down after t2');
    await sleep(2000);
    const before = driver.generation();
    await driver.send({ op: 'reload' });
    await driver.ready(before);
    await sleep(5000);  // Let the chat view restore its conversation.
    // Not t2's question again: asked the same, the model tends to repeat its last answer from the conversation.
    const t3 = await ask('t3', 'The codename may have changed again. Going by your newest AI Baton context only, what is ' +
      'the codename now? Answer with the codename only. Do not read files or use any tools.');
    check('ASSERT', 't3: after the reload, the same conversation', t3.id === t1.id, `${t1.id} / ${t3.id}`);
    check('ASSERT', "t3: this turn's SessionStart carried the codename set before the reload",
      t3.sessionStarts.some((s) => s.success && s.context.includes(third)), JSON.stringify(t3.sessionStarts.map((s) => [s.source, s.success])));
    // The model's answer, not the hooks: the delivery above is the assertion (seen once: context right, answer stale).
    check('INFO', 't3: knows the codename set before the reload', knows(t3.reply, third), `expected ${third}, got "${t3.reply.slice(0, 200)}"`);

    // 4. A new chat must get the newest context.
    const fourth = randomName();
    seed(fourth);
    await driver.send({ op: 'command', id: NEW_CHAT, args: ['sidebar'] });
    const t4 = await ask('t4', "What is this project's current codename, according to your AI Baton context? " +
      'Answer with the codename only. Do not read files or use any tools.');
    check('ASSERT', 't4: a new conversation', t4.id !== t1.id && t4.id !== t3.id, t4.id);
    check('ASSERT', 't4: the new chat got the newest context', knows(t4.reply, fourth), `expected ${fourth}, got "${t4.reply.slice(0, 200)}"`);
    // A Stop that came late could add a duplicate after a turn was checked.
    await sleep(3000);
    const all = copilotHistory();
    check('ASSERT', 'history: exactly one entry per reply, no others', all.length === replies.length &&
      replies.every((r) => all.filter((e) => e.message_id === r.messageId && e.session_id === r.id).length === 1),
      `${all.length} entries, ${replies.length} replies`);
  } catch (error) {
    check('ASSERT', 'round finished', false, error.message);
  } finally {
    try {
      baton(['uninstall-hooks', '--agents=copilot']);
    } catch {
      // The CLI may never have been installed.
    }
    const stopped = await stop(window, driver);
    check('ASSERT', 'the test VS Code ended', stopped);
    const failed = results.filter((r) => r.kind === 'ASSERT' && !r.ok);
    const report = path.join(dir, 'report.json');
    fs.writeFileSync(report, JSON.stringify({ version, build, messages: driver.messages, results }, null, 2));
    if (!options.keep && stopped) fs.rmSync(project, { recursive: true, force: true, maxRetries: 5 });
    else if (!stopped) console.log(`The test VS Code is still running; the project stays: ${project}`);
    console.log(`\n${failed.length ? `${failed.length} FAILED` : 'All assertions passed'}; ${driver.messages} Copilot messages; report: ${report}`);
    process.exitCode = failed.length ? 1 : 0;
  }
}

function readJsonLine(line) {
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}

// Lists the window's commands that match a pattern (no Copilot messages): for finding chat commands after an update.
async function probe(match) {
  exclusive();
  const io = path.join(LIVE, 'probe');
  fs.rmSync(io, { recursive: true, force: true });
  const driver = new Driver(io);
  const window = launch(io, null);
  try {
    await driver.ready(0);
    console.log(JSON.stringify(await driver.send({ op: 'info' }), null, 2));
    console.log((await driver.send({ op: 'commands', match })).join('\n'));
  } finally {
    await stop(window, driver);
  }
}

async function setup() {
  console.log('Opening the test VS Code. Sign in to GitHub for Copilot (Accounts menu, or the Chat view), check that a chat\n' +
    'answers, then close the window. The sign-in stays in ~/.cache/ai-baton/live for the next rounds.');
  exclusive();
  const window = launch(null, null);
  await window.exited;
  if (running()) console.log('VS Code is still running in the background; close it (Quit) before a round.');
}

async function main() {
  const [command, ...rest] = process.argv.slice(2);
  if (command === 'setup') return setup();
  if (command === 'round') return round({ keep: rest.includes('--keep'), noBuild: rest.includes('--no-build') });
  if (command === 'probe') return probe(rest[0] || 'chat|copilot');
  if (command === 'clean') {
    exclusive();
    // The lock itself is inside: removed last, by the exit handler.
    for (const name of fs.readdirSync(LIVE)) if (name !== 'runner.lock') fs.rmSync(path.join(LIVE, name), { recursive: true, force: true });
    return;
  }
  console.log('Usage: node tests/live/run.js setup | round [--keep] [--no-build] | clean');
  process.exitCode = 2;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
