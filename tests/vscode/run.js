// Runs suite.js inside a real VS Code (downloaded by @vscode/test-electron) with the extension from this checkout, a
// throwaway home folder (so the bundled CLI installs there) and a project that already has a Claude checkpoint.
// Needs the CLI bundled first (sh scripts/bundle-cli.sh) and `npm install --prefix tests/vscode @vscode/test-electron@3.1.0` (Node 22+).
// Run: node tests/vscode/run.js  (on Linux without a display: xvfb-run -a node tests/vscode/run.js)
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { runTests } = require('@vscode/test-electron');

const ROOT = path.join(__dirname, '..', '..');
const EXTENSION = path.join(ROOT, 'vscode-extension');
const PYTHON = process.platform === 'win32' ? 'python' : 'python3';

async function main() {
  if (!fs.existsSync(path.join(EXTENSION, 'cli', 'VERSION'))) throw new Error('Bundle the CLI first: sh scripts/bundle-cli.sh');
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'baton-vscode-'));
  const home = path.join(scratch, 'home');
  const project = path.join(scratch, 'démo project');  // A space and a non-ASCII letter, as real folders have.
  fs.mkdirSync(home);
  fs.mkdirSync(project);
  const env = { ...process.env, HOME: home, USERPROFILE: home };
  // Started from a VS Code terminal, Electron would otherwise run as plain Node.
  delete process.env.ELECTRON_RUN_AS_NODE;
  const baton = (args, input) => cp.execFileSync(PYTHON, [path.join(ROOT, 'bin', 'baton'), ...args], { env, input, encoding: 'utf8' });
  baton(['init', project, '--agents=']);  // No project hooks: the user-level ones the suite installs must do the work.
  // A finished Claude turn, as its Stop hook reports it: the panel must show this checkpoint.
  baton(['hook', 'claude'], JSON.stringify({
    cwd: project, hook_event_name: 'Stop', session_id: 'vscode-test', last_assistant_message: 'Set up the démo for the test.',
  }));
  try {
    await runTests({
      extensionDevelopmentPath: EXTENSION,
      extensionTestsPath: path.join(__dirname, 'suite.js'),
      extensionTestsEnv: { HOME: home, USERPROFILE: home, BATON_TEST_PROJECT: project },
      launchArgs: [project, '--disable-extensions', '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
        '--user-data-dir', path.join(scratch, 'user-data'), '--extensions-dir', path.join(scratch, 'extensions'),
        // macOS: never touch the keychain ("Keychain Not Found" would wait for a click forever in CI).
        ...(process.platform === 'darwin' ? ['--use-mock-keychain'] : [])],
    });
  } finally {
    fs.rmSync(scratch, { recursive: true, force: true, maxRetries: 5 });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
