// electron-builder afterPack hook.
//
// macOS without an Apple Developer ID: electron-builder leaves the bundle
// unsigned, and Apple Silicon refuses to run unsigned native code
// ("Killed: 9"). An ad-hoc signature (identity "-") is enough to run; it
// does not satisfy Gatekeeper, so the first launch of a downloaded app
// still needs right-click > Open. When a real identity is configured
// (CSC_LINK / CSC_NAME), electron-builder signs and this hook does nothing.
const { execFileSync } = require('child_process');
const path = require('path');

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  if (process.env.CSC_LINK || process.env.CSC_NAME || process.env.CSC_KEY_PASSWORD) return;
  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = path.join(context.appOutDir, appName);
  // --deep for the frameworks and helpers; the Python in Resources was
  // signed by prepare-python.sh, file by file.
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' });
  console.log(`  • ad-hoc signed ${appName} (no Developer ID configured)`);
};
