// Test only, loaded by tests/live/run.js into its own VS Code profile. Takes commands from BATON_LIVE_IO/inbox
// (one JSON file each) and answers in BATON_LIVE_IO/outbox. A command file is removed before it runs and its answer
// is written before a reload, so a reload never repeats or loses a step. ready.json counts the window's starts.
// Quit (`*-quit.json`) runs apart from the queue, so a chat that never ends cannot stop the cleanup.
const fs = require('fs');
const path = require('path');
const vscode = require('vscode');

const IO = process.env.BATON_LIVE_IO;

function writeAtomic(file, value) {
  fs.writeFileSync(`${file}.tmp`, JSON.stringify(value, null, 2));
  fs.renameSync(`${file}.tmp`, file);
}

// What a command returned, as plain JSON (VS Code may return objects with cycles or URIs).
function plain(value) {
  try {
    return JSON.parse(JSON.stringify(value === undefined ? null : value));
  } catch {
    return String(value);
  }
}

async function info() {
  const baton = vscode.extensions.getExtension('wwijatkowski.ai-baton');
  const chat = vscode.extensions.getExtension('github.copilot-chat');
  let models = null;
  try {
    models = (await vscode.lm.selectChatModels({ vendor: 'copilot' })).map((m) => m.id);
  } catch (error) {
    models = { error: String(error && error.message || error) };
  }
  let build = null;
  if (baton) {
    try {
      build = fs.readFileSync(path.join(baton.extensionPath, 'cli', 'BUILD'), 'utf8').trim();
    } catch {
      // Left null: the runner reports it.
    }
  }
  return {
    vscode: vscode.version,
    baton: baton && { version: baton.packageJSON.version, build, active: baton.isActive },
    copilotChat: chat ? chat.packageJSON.version
      : vscode.extensions.all.filter((e) => /copilot/i.test(e.id)).map((e) => `${e.id}@${e.packageJSON.version}`).join(', ') || null,
    models,
    workspace: (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath),
  };
}

async function execute(command) {
  switch (command.op) {
    case 'info':
      return info();
    case 'chat':
      // Sends to the chat that is open (a new one only after newChat), and resolves when the reply is done.
      return plain(await vscode.commands.executeCommand('workbench.action.chat.open',
        { mode: 'agent', query: command.query, isPartialQuery: false, blockOnResponse: true }));
    case 'commands':
      return (await vscode.commands.getCommands(true)).filter((id) => new RegExp(command.match, 'i').test(id)).sort();
    case 'config':
      // A user setting of the test profile; undefined (no value in JSON) removes it.
      return plain(await vscode.workspace.getConfiguration().update(command.key, command.value, vscode.ConfigurationTarget.Global));
    case 'command':
      return plain(await vscode.commands.executeCommand(command.id, ...(command.args || [])));
    default:
      throw new Error(`unknown op ${command.op}`);
  }
}

let busy = false;

async function poll() {
  if (busy) return;
  busy = true;
  try {
    const inbox = path.join(IO, 'inbox');
    for (const name of fs.readdirSync(inbox).filter((n) => n.endsWith('.json') && !n.endsWith('-quit.json')).sort()) {
      const file = path.join(inbox, name);
      let command;
      try {
        command = JSON.parse(fs.readFileSync(file, 'utf8'));
      } catch {
        continue;  // Still being written.
      }
      fs.rmSync(file, { force: true });
      const answer = path.join(IO, 'outbox', name);
      if (command.op === 'reload') {
        writeAtomic(answer, { ok: true, result: null });
        await vscode.commands.executeCommand('workbench.action.reloadWindow');
        return;
      }
      try {
        writeAtomic(answer, { ok: true, result: await execute(command) });
      } catch (error) {
        writeAtomic(answer, { ok: false, error: String(error && error.stack || error) });
      }
    }
  } finally {
    busy = false;
  }
}

function quitRequested() {
  const inbox = path.join(IO, 'inbox');
  const name = fs.readdirSync(inbox).find((n) => n.endsWith('-quit.json'));
  if (!name) return;
  fs.rmSync(path.join(inbox, name), { force: true });
  writeAtomic(path.join(IO, 'outbox', name), { ok: true, result: null });
  vscode.commands.executeCommand('workbench.action.quit');
}

function activate(context) {
  if (!IO) return;
  fs.mkdirSync(path.join(IO, 'inbox'), { recursive: true });
  fs.mkdirSync(path.join(IO, 'outbox'), { recursive: true });
  const readyFile = path.join(IO, 'ready.json');
  let generation = 0;
  try {
    generation = JSON.parse(fs.readFileSync(readyFile, 'utf8')).generation || 0;
  } catch {
    // First start.
  }
  writeAtomic(readyFile, { generation: generation + 1, time: new Date().toISOString() });
  const timer = setInterval(() => poll().catch(() => {}), 500);
  const control = setInterval(() => {
    try {
      quitRequested();
    } catch {
      // Tried again on the next tick.
    }
  }, 500);
  context.subscriptions.push({ dispose: () => clearInterval(timer) }, { dispose: () => clearInterval(control) });
}

module.exports = { activate, deactivate() {} };
