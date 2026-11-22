// The installer ends the backend before it replaces a file: an update over
// a live python.exe left resources\python half replaced (0.6.0 to 0.6.1).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const nsh = fs.readFileSync(path.join(root, 'installer', 'installer.nsh'), 'utf8');
const ps1 = fs.readFileSync(path.join(root, 'installer', 'stop_backend.ps1'), 'utf8');
const debInstall = fs.readFileSync(path.join(root, 'linux', 'after-install.sh'), 'utf8');
const debRemove = fs.readFileSync(path.join(root, 'linux', 'after-remove.sh'), 'utf8');
const pathPs1 = fs.readFileSync(path.join(root, 'installer', 'user_path.ps1'), 'utf8');

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

// MCP clients start `gigamail-server` by name (the Codex and Claude Code
// plugins, `codex mcp add gigamail -- gigamail-server`): the installer puts
// the folder with the two launchers on PATH, so a desktop user does not
// have to open the console for that name to resolve.
test('the installer puts resources\\bin on PATH and the uninstaller takes it off', () => {
  assert.match(nsh, /!macro customInstall\b[\s\S]*?_gigamailUserPath add/);
  assert.match(nsh, /!macro customUnInstall\b[\s\S]*?_gigamailUserPath remove/);
  assert.match(nsh, /File \/oname=\$PLUGINSDIR\\user_path\.ps1 "\$\{PROJECT_DIR\}\\installer\\user_path\.ps1"/);
  assert.match(nsh, /-File "\$PLUGINSDIR\\user_path\.ps1" \$\{ACTION\} "\$INSTDIR\\resources\\bin" \$installMode/);
});

test('the Windows build ships the PATH launchers as resources\\bin, outside app.asar', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.deepEqual(pkg.build.win.extraResources, [{ from: 'win-bin', to: 'bin' }]);
  assert.ok(pkg.build.files.includes('!win-bin/**'));
  const prepare = fs.readFileSync(path.join(root, 'prepare-python.ps1'), 'utf8');
  assert.match(prepare, /relocate_scripts\.py"\) \$OUT \(Join-Path \$PSScriptRoot "win-bin"\)/);
});

test('Path is edited in the registry unexpanded, keeping its kind and every other entry', () => {
  // SetEnvironmentVariable('Path', ...) would write %USERPROFILE%-style
  // entries back expanded: it is used only for the change broadcast
  assert.doesNotMatch(pathPs1, /SetEnvironmentVariable\('Path'/i);
  assert.match(pathPs1, /DoNotExpandEnvironmentNames/);
  assert.match(pathPs1, /GetValueKind\('Path'\)/);
  assert.match(pathPs1, /SetValue\('Path', \(\$others -join ';'\), \$kind\)/);
  // adding twice changes nothing; the comparison ignores case and a trailing backslash
  assert.match(pathPs1, /TrimEnd\('\\'\) -ine \$want/);
  assert.match(pathPs1, /if \(\$present\) \{ return \$false \}/);
  // PowerShell 5 reads a script without a BOM as ANSI: ASCII only
  assert.ok([...pathPs1].every((c) => c.charCodeAt(0) < 128));
});

test('an update also renames the PATH launchers, so a client restart cannot hold them', () => {
  assert.match(ps1, /resources\\bin\\gigamail-server\.exe/);
  assert.match(ps1, /resources\\bin\\gigamail\.exe/);
});

// The plugin from the OpenAI Plugins Directory brings the skill only: the
// installers write the server entry, so it works before the console has
// started with Codex or the plugin on the computer.
test('a per-user Windows install connects Codex as the console does at its start', () => {
  assert.match(nsh, /\$\{if\} \$installMode != "all"\s+nsExec::ExecToStack '"\$INSTDIR\\resources\\python\\python\.exe" -m gigamail\.core\.codex_config at-install'/);
});

test('the .deb writes the system-wide Codex entry and removes only its own', () => {
  assert.match(debInstall, /-m gigamail\.core\.codex_config system-connect '\/opt\/\$\{sanitizedProductName\}\/resources\/bin\/gigamail-server'/);
  // never fails the installation
  assert.match(debInstall, /system-connect [^\n]*\\\n\s+\|\| echo /);
  assert.match(debRemove, /grep -qF 'command = "\/opt\/\$\{sanitizedProductName\}\/resources\/bin\/gigamail-server"' "\$codex_cfg"/);
  assert.match(debRemove, /rmdir \/etc\/codex 2>\/dev\/null \|\| true/);
});
