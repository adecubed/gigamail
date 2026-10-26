// Unit tests for backend_reuse.js: when the console replaces a backend
// left running by a previous start, and how it finds the process.
const test = require('node:test');
const assert = require('node:assert/strict');
const { restartReason, pidFromNetstat, pidFromLsof } = require('../backend_reuse');

const OURS = { status: 'ok', service: 'gigamail-console', version: '0.4.1', pid: 4242, stale: false };

test('a current backend is reused', () => {
  assert.equal(restartReason(OURS, '0.4.1'), '');
});

test('a backend that does not say whether its code is current is replaced', () => {
  // what every backend up to 0.4.0 answers
  const old = { status: 'ok', service: 'gigamail-console', version: '0.4.0' };
  assert.ok(restartReason(old, '0.4.1'));
  assert.ok(restartReason(old, '0.4.0'), 'even at the same version number');
});

test('a backend whose code changed on disk is replaced', () => {
  assert.ok(restartReason({ ...OURS, stale: true }, '0.4.1'));
});

test('a backend of another version is replaced', () => {
  assert.match(restartReason({ ...OURS, version: '0.4.0' }, '0.4.1'), /0\.4\.0.*0\.4\.1/);
});

test('sources run without package metadata have no version to compare', () => {
  assert.equal(restartReason({ ...OURS, version: '0.0.0+unknown' }, '0.4.1'), '');
  assert.equal(restartReason({ ...OURS, version: '' }, '0.4.1'), '');
});

test('something that is not our backend is never ours to stop', () => {
  assert.equal(restartReason({ service: 'other' }, '0.4.1'), '');
  assert.equal(restartReason(null, '0.4.1'), '');
});

test('a backend running code from another folder is replaced', () => {
  // the installed app left its backend on; the console runs from the sources
  const installed = { ...OURS, src: 'C:\\Users\\simon\\AppData\\Local\\Programs\\GigaMail\\resources\\gigamail\\src' };
  assert.match(restartReason(installed, '0.4.1', 'C:\\Users\\simon\\gigamail-ui\\src', 'win32'), /expects/);
  // same folder, different case and slashes on Windows: reused
  const mine = { ...OURS, src: 'c:/users/simon/gigamail-ui/src/' };
  assert.equal(restartReason(mine, '0.4.1', 'C:\\Users\\simon\\gigamail-ui\\src', 'win32'), '');
  // a backend that does not report its folder cannot be trusted to be ours
  assert.ok(restartReason(OURS, '0.4.1', '/home/u/gigamail/src', 'linux'));
  // no folder to compare: the old rules only
  assert.equal(restartReason(OURS, '0.4.1'), '');
});

test('pidFromNetstat: the process listening on the port, not its clients', () => {
  const out = [
    '',
    'Active Connections',
    '',
    '  Proto  Local Address          Foreign Address        State           PID',
    '  TCP    127.0.0.1:8002         127.0.0.1:49322        TIME_WAIT       0',
    '  TCP    127.0.0.1:18002        0.0.0.0:0              LISTENING       111',
    '  TCP    127.0.0.1:8002         0.0.0.0:0              LISTENING       26744',
    '  TCP    127.0.0.1:49322        127.0.0.1:8002         ESTABLISHED     999',
  ].join('\r\n');
  assert.equal(pidFromNetstat(out, 8002), 26744);
  assert.equal(pidFromNetstat(out, 8003), 0);
  assert.equal(pidFromNetstat('', 8002), 0);
});

test('pidFromLsof: the first pid, or none', () => {
  assert.equal(pidFromLsof('5120\n'), 5120);
  assert.equal(pidFromLsof(''), 0);
});
