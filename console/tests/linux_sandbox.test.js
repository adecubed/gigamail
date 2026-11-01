const test = require('node:test');
const assert = require('node:assert/strict');
const { disabled, message, userNamespacesWork, TEXTS } = require('../linux_sandbox');

test('sandbox off: the flag AppRun adds, or the environment variable', () => {
  assert.equal(disabled(['/tmp/.mount_x/gigamail-console', '--no-sandbox'], {}), true);
  assert.equal(disabled(['/opt/GigaMail/gigamail-console'], { ELECTRON_DISABLE_SANDBOX: '1' }), true);
});

test('sandbox on: no flag, or the variable set to a false value', () => {
  assert.equal(disabled(['/opt/GigaMail/gigamail-console', '--remote-debugging-port=9555'], {}), false);
  assert.equal(disabled(['x'], { ELECTRON_DISABLE_SANDBOX: '0' }), false);
  assert.equal(disabled(['x'], { ELECTRON_DISABLE_SANDBOX: '' }), false);
  // only the namespace sandbox's setuid fallback: still sandboxed
  assert.equal(disabled(['x', '--disable-setuid-sandbox'], {}), false);
});

test('the refusal explains the system when namespaces do not work', () => {
  const m = message({ LANG: 'it_IT.UTF-8' }, false);
  assert.equal(m.title, TEXTS.it.title);
  assert.match(m.body, /GigaMail-amd64\.deb/);
  assert.match(message({ LANG: 'en_US.UTF-8' }, false).body, /AppArmor/);
});

test('the refusal names the flag when namespaces work', () => {
  assert.match(message({ LANG: 'C' }, true).body, /--no-sandbox/);
});

test('the namespace probe is the one AppRun uses', () => {
  const calls = [];
  assert.equal(userNamespacesWork((cmd, args) => { calls.push([cmd, ...args]); }), true);
  assert.deepEqual(calls, [['unshare', '-Ur', 'true']]);
  assert.equal(userNamespacesWork(() => { throw new Error('EPERM'); }), false);
});
