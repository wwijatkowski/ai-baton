// Runs inside VS Code's extension host (started by run.js). Fails by throwing.
const assert = require('assert');
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vscode = require('vscode');

async function poll(read, ms, describe) {
  const deadline = Date.now() + ms;
  for (;;) {
    const value = read();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timed out waiting for the extension: ${describe()}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

exports.run = async function run() {
  const extension = vscode.extensions.getExtension('wwijatkowski.ai-baton');
  assert.ok(extension, 'the extension is loaded');
  const api = await extension.activate();
  const state = await poll(() => {
    const current = api.state();
    return (current.status || current.error) && current;
  }, 90000, () => JSON.stringify(api.state()));
  assert.strictEqual(state.error, null, `the panel shows an error: ${state.error}`);

  // The bundled CLI was installed into the (throwaway) home folder, and the extension ran it for this project.
  const version = require(path.join(extension.extensionPath, 'package.json')).version;
  const home = path.join(os.homedir(), '.ai-baton');
  assert.strictEqual(fs.readFileSync(path.join(home, 'current-version'), 'utf8').trim(), version);
  const project = process.env.BATON_TEST_PROJECT;
  // .native expands Windows short names (RUNNER~1) the way Python does.
  assert.strictEqual(fs.realpathSync.native(state.status.root), fs.realpathSync.native(project));
  assert.ok(state.status.initialized, 'the project is set up');
  // Claude's extension is not installed here; its checkpoint still lists it (with the summary the hook saved).
  const claude = state.status.agents.find((a) => a.id === 'claude');
  assert.ok(claude && claude.checkpoint, `Claude's checkpoint reaches the panel: ${JSON.stringify(state.status.agents)}`);
  assert.match(claude.checkpoint.summary, /Set up the démo for the test\./);
  assert.strictEqual(claude.installed, false);

  // The installed launcher (what hooks run) works on this system too.
  const python = process.platform === 'win32' ? 'python' : 'python3';
  const out = cp.execFileSync(python, [path.join(home, 'bin', 'baton'), 'status', '--json', project], { encoding: 'utf8' });
  assert.strictEqual(JSON.parse(out).name, path.basename(project));

  const commands = await vscode.commands.getCommands(true);
  for (const id of ['aiBaton.askForReview', 'aiBaton.initProject', 'aiBaton.switchAgent', 'aiBaton.showRecent']) {
    assert.ok(commands.includes(id), `${id} is registered`);
  }
  await vscode.commands.executeCommand('aiBaton.refresh');
  assert.strictEqual(api.state().error, null);
  console.log(`AI Baton integration test passed (${process.platform}, CLI ${version})`);
};
