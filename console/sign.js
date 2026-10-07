// sign.js — electron-builder signing hook (win.signtoolOptions.sign).
//
// electron-builder calls it for every Windows executable it would sign:
// GigaMail.exe, the uninstaller, the installer, and every .exe copied with
// extraResources (the embedded Python and its launchers).
//
// It signs only when GIGAMAIL_SIGN_SHA1 is set, which scripts/sign-release.ps1
// does on the maintainer's PC, where the Certum certificate lives in
// SimplySign. Everywhere else (CI, a contributor's build) it does nothing and
// the build stays unsigned, exactly as before the hook existed.
//
// Files under resources/ are never signed: that is the embedded Python, whose
// python.exe already carries the PSF signature and whose pip launcher stubs
// (t64.exe, w64.exe...) get script data appended to them, which a signature
// would not survive.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const DEFAULT_TIMESTAMP = 'http://time.certum.pl';

function isBundledResource(file) {
  return path.resolve(file).split(path.sep).map(p => p.toLowerCase()).includes('resources');
}

function signtoolArgs(file, env) {
  return [
    'sign',
    '/sha1', env.GIGAMAIL_SIGN_SHA1,
    '/fd', 'sha256',
    '/tr', env.GIGAMAIL_SIGN_TIMESTAMP || DEFAULT_TIMESTAMP,
    '/td', 'sha256',
    '/d', 'GigaMail',
    '/du', 'https://github.com/adecubed/gigamail',
    file,
  ];
}

// Returns what it did, for the tests: 'disabled', 'skipped' or 'signed'.
function sign(configuration, _packager, env = process.env, run = execFileSync) {
  const file = configuration.path;
  if (!env.GIGAMAIL_SIGN_SHA1) return 'disabled';
  if (isBundledResource(file)) return 'skipped';
  const signtool = env.GIGAMAIL_SIGNTOOL || 'signtool.exe';
  // A failure throws: a release half signed must not be packaged.
  run(signtool, signtoolArgs(file, env), { stdio: 'inherit' });
  run(signtool, ['verify', '/pa', file], { stdio: 'inherit' });
  if (env.GIGAMAIL_SIGN_LOG) fs.appendFileSync(env.GIGAMAIL_SIGN_LOG, path.basename(file) + '\n');
  return 'signed';
}

module.exports = sign;
module.exports.default = sign;
module.exports.signtoolArgs = signtoolArgs;
module.exports.isBundledResource = isBundledResource;
