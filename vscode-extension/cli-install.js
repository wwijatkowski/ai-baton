// Installs the CLI bundled in the extension (cli/) to a stable folder, by default ~/.ai-baton.
// Hooks in the agents' settings run ~/.ai-baton/bin/baton, a tiny launcher that never changes, so the hook command
// stays identical across updates (Codex asks for trust again whenever it changes). Each version lives in
// versions/<version>; the current-version file names one and is replaced with a rename, so a hook running during an update sees
// either the old or the new CLI, never a half-copied one. A file, not a symlink: Windows needs extra rights for those
// (macOS and Linux also keep the `current` symlink of earlier versions).
// A lock keeps two VS Code windows from installing at once.
// No VS Code dependency, so tests can run it with plain Node.
const fs = require('fs');
const path = require('path');

const VERSION_FILE = 'VERSION';
const CURRENT_FILE = 'current-version';  // Not 'CURRENT': macOS and Windows would take it for the old 'current'.
const LOCK_STALE_MS = 2 * 60 * 1000;
const LAUNCHER = `#!/usr/bin/env python3
# AI Baton launcher: runs the installed version in ../current. Hooks call this file; it never changes.
import os
import sys

os.environ['BATON_LAUNCHER'] = os.path.abspath(__file__)
home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Read current-version once: every import of this process then comes from one version, even if an update switches it.
try:
    with open(os.path.join(home, 'current-version'), encoding='utf-8') as pointer:
        version = os.path.join(home, 'versions', pointer.read().strip())
except OSError:
    version = os.path.realpath(os.path.join(home, 'current'))  # Installed before current-version existed.
sys.path.insert(0, version)
from baton.cli import main  # noqa: E402

main()
`;

function readVersion(dir) {
  try {
    return fs.readFileSync(path.join(dir, VERSION_FILE), 'utf8').trim();
  } catch {
    return null;
  }
}

// Replace `file` with `content` in one step (write a temp file, then rename over it). Windows refuses the rename for a
// moment while another process (a hook starting, an antivirus scan) has the file open, so that is retried briefly.
function writeAtomic(file, content, mode) {
  const tmp = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, content, { mode });
  for (let attempt = 0; ; attempt++) {
    try {
      return fs.renameSync(tmp, file);
    } catch (error) {
      if (!['EPERM', 'EACCES', 'EBUSY'].includes(error.code) || attempt >= 20) {
        fs.rmSync(tmp, { force: true });
        throw error;
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
    }
  }
}

function currentVersion(target) {
  try {
    return fs.readFileSync(path.join(target, CURRENT_FILE), 'utf8').trim();
  } catch {
    return null;
  }
}

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

// The lock file holds its owner's pid and a token. It is taken over only when its owner is gone (or the file is
// old and unreadable), and released only by its owner. Returns the token, or null while another window installs.
function takeLock(target, attempts = 3) {
  const lock = path.join(target, '.install.lock');
  const token = `${process.pid}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
  try {
    fs.writeFileSync(lock, token, { flag: 'wx' });
    return token;
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
  let held;
  try {
    held = { text: fs.readFileSync(lock, 'utf8'), age: Date.now() - fs.statSync(lock).mtimeMs };
  } catch (error) {
    if (error.code === 'ENOENT' && attempts > 1) return takeLock(target, attempts - 1);  // Released meanwhile.
    throw error;
  }
  const owner = Number(held.text.split(':')[0]);
  const gone = owner ? !alive(owner) : held.age > LOCK_STALE_MS;
  if (!gone || attempts <= 1) return null;
  fs.rmSync(lock, { force: true });
  return takeLock(target, attempts - 1);
}

function releaseLock(target, token) {
  const lock = path.join(target, '.install.lock');
  try {
    if (fs.readFileSync(lock, 'utf8') === token) fs.rmSync(lock, { force: true });
  } catch {
    // Already gone.
  }
}

// Installs `bundled` into `target` unless that version is already current.
// Returns { home, updated }, { home, updated: false, busy: true } while another window installs, or null without a bundle.
function installCli(bundled, target) {
  const version = readVersion(bundled);
  if (!version) return null;
  const launcher = path.join(target, 'bin', 'baton');
  // The version in use now: current-version, or the `current` symlink of installs from before it existed.
  const installed = currentVersion(target) || readVersion(path.join(target, 'current'));
  if (currentVersion(target) === version && readVersion(path.join(target, 'versions', version)) === version &&
      fs.existsSync(launcher)) {
    return { home: target, updated: false };
  }
  fs.mkdirSync(path.join(target, 'versions'), { recursive: true });
  fs.mkdirSync(path.join(target, 'bin'), { recursive: true });
  const token = takeLock(target);
  if (!token) return { home: target, updated: false, busy: true };
  try {
    const dest = path.join(target, 'versions', version);
    if (readVersion(dest) !== version) {
      // Copy beside, then rename into place: a version folder is either complete or absent.
      const staging = `${dest}.tmp-${process.pid}`;
      fs.rmSync(staging, { recursive: true, force: true });
      fs.cpSync(bundled, staging, { recursive: true });
      fs.rmSync(dest, { recursive: true, force: true });
      fs.renameSync(staging, dest);
    }
    writeAtomic(launcher, LAUNCHER, 0o755);
    writeAtomic(path.join(target, CURRENT_FILE), `${version}\n`, 0o644);
    if (process.platform !== 'win32') {
      // The `current` symlink older launchers read: kept up to date, so a hook that started one just before this
      // update, or an older extension in another window, still finds a complete version.
      const link = `${path.join(target, 'current')}.tmp-${process.pid}`;
      fs.rmSync(link, { force: true });
      fs.symlinkSync(path.join('versions', version), link);
      fs.renameSync(link, path.join(target, 'current'));
    }
    // Keep the new version and the one before it (a hook may still be running it); drop older ones. Best effort: the
    // new version is already in use, and a folder Windows keeps busy now goes at the next update.
    const keep = new Set([version, installed].filter(Boolean));
    for (const name of fs.readdirSync(path.join(target, 'versions'))) {
      if (keep.has(name) && !name.includes('.tmp-')) continue;
      try {
        fs.rmSync(path.join(target, 'versions', name), { recursive: true, force: true });
      } catch {
        // Retried at the next update.
      }
    }
    return { home: target, updated: true };
  } finally {
    releaseLock(target, token);
  }
}

module.exports = { installCli, readVersion };
