// The MCP config the onboarding asks the user to copy (mcp_snippets.js):
// it must start the server with the backend's own Python, since
// gigamail-server is on no desktop user's PATH.
const test = require('node:test');
const assert = require('node:assert/strict');

const S = require('../mcp_snippets');
const AG = {
  python: 'C:\\Users\\V\\AppData\\Local\\Programs\\GigaMail\\resources\\python\\python.exe',
  root: 'C:\\Users\\V\\AppData\\Roaming\\ADE',
};

test('Codex: the command line keeps Windows paths as they are', () => {
  const first = S.codexSnippet(AG).split('\n')[0];
  assert.equal(first, `codex mcp add gigamail --env GIGAMAIL_ROOT="${AG.root}" -- "${AG.python}" -m gigamail.server`);
});

test('Codex: the TOML escapes backslashes and carries the args', () => {
  const toml = S.codexSnippet(AG);
  assert.match(toml, /command = "C:\\\\Users\\\\V\\\\AppData\\\\Local/);
  assert.match(toml, /args = \["-m", "gigamail\.server"\]/);
  assert.match(toml, /GIGAMAIL_ROOT = "C:\\\\Users\\\\V\\\\AppData\\\\Roaming\\\\ADE"/);
});

test('Claude: JSON with the bundled Python, -m and the data folder', () => {
  const cfg = JSON.parse(S.mcpSnippet(AG)).mcpServers.gigamail;
  assert.deepEqual(cfg, { command: AG.python, args: ['-m', 'gigamail.server'], env: { GIGAMAIL_ROOT: AG.root } });
});

test('an older backend without the Python path falls back to the pip names', () => {
  assert.deepEqual(JSON.parse(S.mcpSnippet(null)).mcpServers.gigamail, { command: 'gigamail-server' });
  assert.match(S.codexSnippet({}).split('\n')[0], /-- "gigamail-server"$/);
});

test('CLI commands: PowerShell call operator on Windows, plain on macOS', () => {
  assert.equal(S.cliCommand(AG, 'telegram setup'), `& "${AG.python}" -m gigamail.cli telegram setup`);
  const mac = { python: '/Applications/GigaMail.app/Contents/Resources/python/bin/python3' };
  assert.equal(S.cliCommand(mac, 'telegram setup'), `"${mac.python}" -m gigamail.cli telegram setup`);
  assert.equal(S.cliCommand(null, 'telegram setup'), 'gigamail telegram setup');
});
