// sign.js: the electron-builder hook signs only on the maintainer's PC, and
// never the embedded Python under resources/.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const sign = require('../sign');

const SHA1 = 'ABCDEF0123456789ABCDEF0123456789ABCDEF01';
const APP = path.join(os.tmpdir(), 'win-unpacked');

function recorder() {
  const calls = [];
  const run = (cmd, args) => { calls.push([cmd, ...args]); };
  return { calls, run };
}

test('without a certificate the build stays unsigned', () => {
  const { calls, run } = recorder();
  assert.equal(sign({ path: path.join(APP, 'GigaMail.exe') }, null, {}, run), 'disabled');
  assert.deepEqual(calls, []);
});

test('GigaMail.exe is signed with the certificate and a timestamp, then verified', () => {
  const { calls, run } = recorder();
  const exe = path.join(APP, 'GigaMail.exe');
  const env = { GIGAMAIL_SIGN_SHA1: SHA1, GIGAMAIL_SIGNTOOL: 'C:\\sdk\\signtool.exe' };
  assert.equal(sign({ path: exe }, null, env, run), 'signed');
  assert.equal(calls.length, 2);
  const [cmd, ...args] = calls[0];
  assert.equal(cmd, 'C:\\sdk\\signtool.exe');
  assert.deepEqual(args.slice(0, 3), ['sign', '/sha1', SHA1]);
  assert.ok(args.includes('/tr') && args[args.indexOf('/tr') + 1] === 'http://time.certum.pl');
  assert.equal(args[args.indexOf('/fd') + 1], 'sha256');
  assert.equal(args.at(-1), exe);
  assert.deepEqual(calls[1], ['C:\\sdk\\signtool.exe', 'verify', '/pa', exe]);
});

test('the embedded Python under resources is left alone', () => {
  const { calls, run } = recorder();
  const env = { GIGAMAIL_SIGN_SHA1: SHA1 };
  for (const f of ['resources/python/python.exe',
                   'resources/python/Lib/site-packages/pip/_vendor/distlib/t64.exe',
                   'Resources/python/Scripts/pip.exe']) {
    assert.equal(sign({ path: path.join(APP, f) }, null, env, run), 'skipped');
  }
  assert.deepEqual(calls, []);
});

test('a failed signature stops the build', () => {
  const env = { GIGAMAIL_SIGN_SHA1: SHA1 };
  const run = () => { throw new Error('SignTool Error: No certificates were found'); };
  assert.throws(() => sign({ path: path.join(APP, 'GigaMail.exe') }, null, env, run), /No certificates/);
});

test('each signed file is written to the log the release script checks', () => {
  const log = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'sign-')), 'signed.txt');
  const env = { GIGAMAIL_SIGN_SHA1: SHA1, GIGAMAIL_SIGN_LOG: log };
  sign({ path: path.join(os.tmpdir(), 'nsis', '__uninstaller-nsis-gigamail.exe') }, null, env, () => {});
  sign({ path: path.join(os.tmpdir(), 'out', 'GigaMail Setup 0.5.0.exe') }, null, env, () => {});
  assert.deepEqual(fs.readFileSync(log, 'utf-8').trim().split('\n'),
                   ['__uninstaller-nsis-gigamail.exe', 'GigaMail Setup 0.5.0.exe']);
});
