// The installer ends the backend before it replaces a file: an update over
// a live python.exe left resources\python half replaced (0.6.0 to 0.6.1).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const nsh = fs.readFileSync(path.join(root, 'installer', 'installer.nsh'), 'utf8');
const ps1 = fs.readFileSync(path.join(root, 'installer', 'stop_backend.ps1'), 'utf8');

test('electron-builder includes the hook script', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.equal(pkg.build.nsis.include, 'installer/installer.nsh');
});

test('installer and uninstaller stop the backend before touching files', () => {
  assert.match(nsh, /!macro customInit\b/);
  assert.match(nsh, /!macro customUnInit\b/);
  assert.match(nsh, /File \/oname=\$PLUGINSDIR\\stop_backend\.ps1 "\$\{PROJECT_DIR\}\\installer\\stop_backend\.ps1"/);
  assert.match(nsh, /powershell\.exe .*-File "\$PLUGINSDIR\\stop_backend\.ps1" "\$INSTDIR"/);
});

test('every process from the install folder and the GigaMail backend on the port are ended, nothing else', () => {
  // the app, the backend, the watcher, the MCP server run by ChatGPT/Codex
  // or Claude Desktop, and their launchers: anything under $INSTDIR
  assert.match(ps1, /ExecutablePath\.StartsWith\(\$root/);
  assert.doesNotMatch(ps1, /Name = 'python\.exe'/);
  // an MCP client restarts its server at once: python.exe and the
  // launcher are renamed away until the new files are in place
  assert.match(ps1, /Rename-Item -LiteralPath \$path -NewName .*\.updating/);
  assert.match(ps1, /Scripts\\gigamail-server\.exe/);
  // a backend from another folder (an older install, the sources) holds
  // the port: only a listener started as gigamail.http_api is ended
  assert.match(ps1, /Get-NetTCPConnection -LocalPort \$port -State Listen/);
  assert.match(ps1, /CommandLine -like '\*gigamail\.http_api\*'/);
  assert.match(ps1, /Stop-Process -Id \$id -Force/);
  assert.doesNotMatch(ps1, /taskkill|\/IM python/i);
});
