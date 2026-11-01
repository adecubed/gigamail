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
// the link moves, the path in the configs does not. Older versions are
// removed once `current` points at the new one.
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

/** Copy resources/{python,gigamail} for `version` unless already complete,
 *  point `current` at it, drop the other versions. Returns the folder to
 *  use in place of the resources path (…/runtime/current). Throws when the
 *  copy cannot be made: the caller decides what to do. */
function ensure({ resourcesPath, version, env = process.env, home = os.homedir(), fsMod = fs }) {
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

  // Other versions, and temp folders left by a copy that was cut short.
  for (const name of fsMod.readdirSync(root)) {
    if (name === version || name === 'current') continue;
    if (isVersionDir(name) || name.startsWith('.tmp-')) {
      try { fsMod.rmSync(path.join(root, name), { recursive: true, force: true }); } catch (_) { /* in use: next start */ }
    }
  }
  return link;
}

module.exports = { runtimeRoot, ensure, isVersionDir };
