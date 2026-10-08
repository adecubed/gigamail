// Where the console keeps its data and finds its Python, per platform.
//
// The backend (gigamail.core.data_paths) resolves the data root as
// GIGAMAIL_ROOT / ADE_ROOT, else %APPDATA%\ADE on Windows, else ~/.ade.
// The main process used to hard-code %APPDATA%/ADE with a fallback to the
// home folder: on macOS that put the session token in ~/ADE while the
// backend looked in ~/.ade, and the window never found its backend. One
// rule here, shared by both, and the same override the tests already use.
const path = require('path');
const os = require('os');

/** Data root: approvals, session token, mail databases live under it. */
function dataRoot(env = process.env, platform = process.platform, home = os.homedir()) {
  const override = (env.GIGAMAIL_ROOT || env.ADE_ROOT || '').trim();
  if (override) return override;
  if (platform === 'win32' && env.APPDATA) return path.join(env.APPDATA, 'ADE');
  return path.join(home, '.ade');
}

/** The interpreter that runs the backend.
 *  Packaged: the Python shipped in resources/python (embeddable on Windows,
 *  python-build-standalone on macOS, see prepare-python.*). Development:
 *  the repo's .venv next to console/. */
function pythonPath({ packaged, resourcesPath, devRoot, platform = process.platform }) {
  if (platform === 'win32') {
    return packaged
      ? path.join(resourcesPath, 'python', 'python.exe')
      : path.join(devRoot, '.venv', 'Scripts', 'python.exe');
  }
  return packaged
    ? path.join(resourcesPath, 'python', 'bin', 'python3')
    : path.join(devRoot, '.venv', 'bin', 'python');
}

/** electron-updater needs a signed app on macOS and refuses an unsigned
 *  one with an error at every start. Releases are signed with the Apple
 *  Developer ID and notarized in CI (release.yml, job installer-mac), so
 *  macOS checks for updates like Windows does; Linux has no package yet. */
function autoUpdateSupported(platform = process.platform) {
  return platform === 'win32' || platform === 'darwin';
}

module.exports = { dataRoot, pythonPath, autoUpdateSupported };
