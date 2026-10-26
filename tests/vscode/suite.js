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

  // Install the hooks through the installed launcher, then run exactly the commands written to the agents' settings
  // (Claude: exec form on Windows; Codex: a command line for the system's shell), as the agents would.
  cp.execFileSync(python, [path.join(home, 'bin', 'baton'), 'install-hooks', '--agents=claude,codex'], { encoding: 'utf8' });
  const stopHook = (file) => JSON.parse(fs.readFileSync(path.join(os.homedir(), file), 'utf8')).hooks.Stop[0].hooks[0];
  for (const [agent, file] of [['claude', '.claude/settings.json'], ['codex', '.codex/hooks.json']]) {
    const hook = stopHook(file);
    const input = JSON.stringify({ cwd: project, hook_event_name: 'Stop', session_id: `installed-${agent}`,
      last_assistant_message: `Reply from ${agent} through the installed hook.` });
    const output = hook.args ? cp.execFileSync(hook.command, hook.args, { input, encoding: 'utf8' })
      : cp.execSync(hook.command, { input, encoding: 'utf8' });  // cmd.exe on Windows, /bin/sh elsewhere.
    assert.doesNotThrow(() => JSON.parse(output), `${agent}'s hook printed JSON: ${output}`);
  }
  await vscode.commands.executeCommand('aiBaton.refresh');
  for (const agent of ['claude', 'codex']) {
    const entry = await poll(() => (api.state().status.agents || []).find((a) => a.id === agent && a.checkpoint &&
      /through the installed hook/.test(a.checkpoint.summary)), 30000, () => JSON.stringify(api.state().status.agents));
    assert.ok(entry, `${agent}'s checkpoint from the installed hook reaches the panel`);
  }

  const commands = await vscode.commands.getCommands(true);
  for (const id of ['aiBaton.askForReview', 'aiBaton.initProject', 'aiBaton.switchAgent', 'aiBaton.showRecent']) {
    assert.ok(commands.includes(id), `${id} is registered`);
  }
  await vscode.commands.executeCommand('aiBaton.refresh');
  assert.strictEqual(api.state().error, null);
  console.log(`AI Baton integration test passed (${process.platform}, CLI ${version})`);
};
