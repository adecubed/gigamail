// The ChatGPT/Codex status line (codex_connect.js), from GET /agent/codex.
const test = require('node:test');
const assert = require('node:assert/strict');

const C = require('../codex_connect');

test('connected, not connected, someone else, unreadable', () => {
  assert.equal(C.label({ connected: true }).cls, 'ok');
  assert.equal(C.label({ connected: false, entry: null }).cls, 'warn');
  const other = C.label({ connected: false, entry: { command: 'gigamail-server' } });
  assert.equal(other.cls, 'warn');
  assert.match(other.text, /gigamail-server/);
  assert.equal(C.label({ error: 'TOMLDecodeError: x' }).cls, 'err');
});
