// The AppImage's Python, copied where it outlives the AppImage.
//
// An AppImage runs from a FUSE mount under /tmp/.mount_XXXX that changes at
// every start and disappears when the app quits. The backend outlives the
// window by design, and the agents' MCP configs (Codex, Antigravity, the
// agent bar's Claude) are written with the backend's sys.executable: from
// the mount, all of them pointed at a Python that was gone after the app
// closed or the PC restarted.
//
// So, inside an AppImage only, the Python and the backend's sources are
// copied once per version to
//   $XDG_DATA_HOME/gigamail/runtime/<version>/{python,gigamail/src}
// and a `current` link points at the version in use. The backend starts
// from runtime/current/python/bin/python3; Python keeps that path as
// sys.executable, so every config written from it survives updates too:
// the link moves, the path in the configs does not.
//
// A process stays on the version it started with: Python derives sys.prefix
// (stdlib, site-packages) from the resolved path of its executable, and the
// backend gets its sources' PYTHONPATH through the versioned folder, not
// through `current`. So an update never mixes two versions in one process.
// A version is removed only when no process uses it any more: deleting a
// folder succeeds on Linux while processes still run from it (Codex keeps
// its MCP server open for a whole session), and their next import failed.
// Which versions are in use is read from /proc (executable, working folder,
// mapped libraries) at every start, so a version kept by a live process at
// one update goes at a later start.
//
// The .deb installs in /opt/GigaMail, a path that stays: it uses its
// resources folder directly.
const fs = require('fs');
const path = require('path');
const os = require('os');

const DONE = '.complete';

/** $XDG_DATA_HOME/gigamail/runtime, else ~/.local/share/gigamail/runtime. */
function runtimeRoot(env = process.env, home = os.homedir()) {
  const xdg = String(env.XDG_DATA_HOME || '').trim();
  const base = xdg && path.isAbsolute(xdg) ? xdg : path.join(home, '.local', 'share');
  return path.join(base, 'gigamail', 'runtime');
}

/** Only names a version can have: never `current`, never a temp folder. */
function isVersionDir(name) {
  return /^\d+\.\d+\.\d+[0-9A-Za-z.+-]*$/.test(name);
}

/** Versions under `root` that a running process uses: its executable, its
 *  working folder or a library it has mapped lies inside one. /proc shows
 *  resolved paths, so both `root` and its resolved form are matched.
 *  Processes of other users are unreadable and skipped. */
function versionsInUse(root, { procDir = '/proc', fsMod = fs } = {}) {
  const prefixes = new Set([root]);
  try { prefixes.add(fsMod.realpathSync(root)); } catch (_) { /* not there yet */ }
  const used = new Set();
  const mark = (p) => {
    for (const r of prefixes) {
      if (!p.startsWith(r + path.sep)) continue;
      const v = p.slice(r.length + 1).split(path.sep)[0];
      if (isVersionDir(v)) used.add(v);
    }
  };
  let pids = [];
  try { pids = fsMod.readdirSync(procDir).filter((d) => /^\d+$/.test(d)); } catch (_) { return used; }
  for (const pid of pids) {
    for (const link of ['exe', 'cwd']) {
      try { mark(fsMod.readlinkSync(path.join(procDir, pid, link))); } catch (_) { /* gone or not ours */ }
    }
    try {
      for (const line of fsMod.readFileSync(path.join(procDir, pid, 'maps'), 'utf-8').split('\n')) {
        const i = line.indexOf(' /');
        if (i >= 0) mark(line.slice(i + 1).replace(/ \(deleted\)$/, ''));
      }
    } catch (_) { /* gone or not ours */ }
  }
  return used;
}

/** Copy resources/{python,gigamail} for `version` unless already complete,
 *  point `current` at it, remove the versions no process uses. Returns
 *  { python, src }: start the interpreter from `python`/python/bin/python3
 *  (…/runtime/current, the path the agents' configs keep) and put
 *  `src`/gigamail/src on PYTHONPATH (…/runtime/<version>, so the process
 *  keeps its own version's code after an update). Throws when the copy
 *  cannot be made: the caller decides what to do. */
function ensure({ resourcesPath, version, env = process.env, home = os.homedir(), fsMod = fs, procDir = '/proc' }) {
  if (!isVersionDir(version)) throw new Error(`not a version: ${version}`);
  const root = runtimeRoot(env, home);
  const dir = path.join(root, version);
  fsMod.mkdirSync(root, { recursive: true, mode: 0o700 });

  if (!fsMod.existsSync(path.join(dir, DONE))) {
    // Copy into a temp folder and rename: a copy cut short (disk full, the
    // app killed) is never taken for a complete one.
    const tmp = path.join(root, `.tmp-${version}-${process.pid}`);
    fsMod.rmSync(tmp, { recursive: true, force: true });
    fsMod.mkdirSync(tmp, { recursive: true });
    for (const part of ['python', 'gigamail']) {
      fsMod.cpSync(path.join(resourcesPath, part), path.join(tmp, part),
        { recursive: true, verbatimSymlinks: true, preserveTimestamps: true });
    }
    fsMod.writeFileSync(path.join(tmp, DONE), `${version}\n`);
    fsMod.rmSync(dir, { recursive: true, force: true });
    fsMod.renameSync(tmp, dir);
  }

  // `current` -> <version>, replaced atomically (rename over the old link).
  const link = path.join(root, 'current');
  let target = '';
  try { target = fsMod.readlinkSync(link); } catch (_) { target = ''; }
  if (target !== version) {
    const tmpLink = path.join(root, `.current-${process.pid}`);
    fsMod.rmSync(tmpLink, { force: true });
    fsMod.symlinkSync(version, tmpLink);
    fsMod.renameSync(tmpLink, link);
  }

  // Other versions nobody runs from, and temp folders left by a copy that
  // was cut short (this app is single-instance: no copy is in progress).
  const inUse = versionsInUse(root, { procDir, fsMod });
  for (const name of fsMod.readdirSync(root)) {
    if (name === version || name === 'current') continue;
    if ((isVersionDir(name) && !inUse.has(name)) || name.startsWith('.tmp-')) {
      try { fsMod.rmSync(path.join(root, name), { recursive: true, force: true }); } catch (_) { /* next start */ }
    }
  }
  return { python: link, src: dir };
}

module.exports = { runtimeRoot, ensure, isVersionDir, versionsInUse };
