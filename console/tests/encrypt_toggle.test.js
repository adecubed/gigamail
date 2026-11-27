// The "Encrypt" button (encrypt_toggle.js) and the read-view badge
// (mail_render.js encryptionLabel).
const test = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const { attach, statusText, statusUrl } = require('../encrypt_toggle');
const { encryptionLabel, encryptionBadgeHtml } = require('../mail_render');

const T = (k, it) => it;

function setup(answer) {
  const dom = new JSDOM('<button id="b"></button><span id="s"></span>');
  const doc = dom.window.document;
  const calls = [];
  const recipients = { to: 'anna.bianchi@example.com', cc: '' };
  const toggle = attach({
    button: doc.getElementById('b'), status: doc.getElementById('s'),
    api: 'http://127.0.0.1:8002', getAccountId: () => 3,
    getRecipients: () => recipients, T,
    fetchFn: async (url) => { calls.push(url); return { ok: true, json: async () => answer.value }; },
  });
  return { toggle, doc, calls, recipients };
}

test('turns on only when every recipient has a key', async () => {
  const answer = { value: { available: true, can_encrypt: true, missing: [] } };
  const { toggle, doc, calls } = setup(answer);
  assert.equal(await toggle.set(true), true);
  assert.equal(doc.getElementById('b').getAttribute('aria-pressed'), 'true');
  assert.match(calls[0], /\/encryption\/status\?to=anna\.bianchi%40example\.com&cc=&account_id=3$/);

  answer.value = { available: true, can_encrypt: false, missing: ['luca.verdi@example.com'], reason: 'keys' };
  await toggle.set(false);
  assert.equal(await toggle.set(true), false);
  assert.match(doc.getElementById('s').textContent, /luca\.verdi@example\.com/);
});

test('a recipient added later does not switch it off by itself', async () => {
  const answer = { value: { available: true, can_encrypt: true, missing: [] } };
  const { toggle, doc } = setup(answer);
  await toggle.set(true);
  answer.value = { available: true, can_encrypt: false, missing: ['luca.verdi@example.com'], reason: 'keys' };
  await toggle.recheck();
  // Still on: the send fails with the reason rather than leaving in clear.
  assert.equal(toggle.isOn(), true);
  assert.match(doc.getElementById('s').textContent, /Nessuna chiave per luca\.verdi@example\.com/);
});

test('a backend that does not answer leaves it off', async () => {
  const dom = new JSDOM('<button id="b"></button>');
  const toggle = attach({
    button: dom.window.document.getElementById('b'), api: 'x',
    getRecipients: () => ({ to: 'a@example.com', cc: '' }), T,
    fetchFn: async () => { throw new Error('offline'); },
  });
  assert.equal(await toggle.set(true), false);
});

test('status texts', () => {
  assert.match(statusText({ reason: 'account', can_encrypt: false }, T), /IMAP\/SMTP/);
  assert.match(statusText(null, T), /non disponibile/);
  assert.match(statusText({ available: true, can_encrypt: false, missing: [] }, T), /destinatario/);
  assert.equal(statusUrl('http://h', null, 'a@example.com', ''), 'http://h/encryption/status?to=a%40example.com&cc=');
});

function setupDetails(answer) {
  const dom = new JSDOM('<button id="b"></button><span id="s"></span><div id="d"></div>');
  const doc = dom.window.document;
  const toggle = attach({
    button: doc.getElementById('b'), status: doc.getElementById('s'), details: doc.getElementById('d'),
    api: 'http://127.0.0.1:8002', getRecipients: () => ({ to: 'anna.bianchi@example.com', cc: '' }), T,
    fetchFn: async () => ({ ok: true, json: async () => answer.value }),
  });
  return { toggle, doc };
}

const KEY_CHANGED = { available: true, can_encrypt: false, reason: 'key_changed', missing: [],
  pending: [{ address: 'anna.bianchi@example.com' }] };
const CAN = { available: true, can_encrypt: true, missing: [], own_fingerprint: 'aaaa1111',
  peers: [{ address: 'anna.bianchi@example.com', fingerprint: 'b77e0d15' }] };

test('a pending key stops encryption and offers the decision', async () => {
  const answer = { value: KEY_CHANGED };
  const { toggle, doc } = setupDetails(answer);
  assert.equal(await toggle.set(true), false);
  assert.match(doc.getElementById('s').textContent, /chiave nuova da accettare/);
  const link = doc.querySelector('#d [data-key-change]');
  assert.ok(link);
  assert.equal(link.getAttribute('data-key-change'), 'anna.bianchi@example.com');
  assert.equal(doc.getElementById('d').hidden, false);
});

test('after the key is accepted, the recheck turns encryption on and says so', async () => {
  const answer = { value: KEY_CHANGED };
  const { toggle, doc } = setupDetails(answer);
  await toggle.set(true);
  answer.value = CAN;
  await toggle.recheck();
  assert.equal(toggle.isOn(), true);
  assert.match(doc.getElementById('s').textContent, /partirà cifrata/);
  assert.equal(doc.querySelector('#d [data-key-change]'), null);
  assert.deepEqual([...doc.querySelectorAll('#d div')].map((e) => e.textContent),
    ['La tua chiave  AAAA 1111', 'anna.bianchi@example.com  B77E 0D15']);
});

test('a recheck does not turn on a toggle refused for a missing key', async () => {
  const answer = { value: { available: true, can_encrypt: false, missing: ['luca.verdi@example.com'], reason: 'keys' } };
  const { toggle } = setupDetails(answer);
  await toggle.set(true);
  answer.value = CAN;
  await toggle.recheck();
  assert.equal(toggle.isOn(), false);
});

test('a pending key keeps the wish to encrypt, so the send cannot leave in clear', async () => {
  const answer = { value: KEY_CHANGED };
  const { toggle } = setupDetails(answer);
  await toggle.set(true);
  assert.equal(toggle.isOn(), false);
  assert.equal(toggle.wantsEncryption(), true);
});

test('a click while waiting for a key gives up encryption and clears the status', async () => {
  const answer = { value: KEY_CHANGED };
  const { toggle, doc } = setupDetails(answer);
  await toggle.set(true);
  doc.getElementById('b').click();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(toggle.wantsEncryption(), false);
  assert.equal(toggle.isOn(), false);
  assert.equal(doc.getElementById('s').textContent, '');
});

test('a refusal for a missing key is no wish to encrypt', async () => {
  const answer = { value: { available: true, can_encrypt: false, missing: ['luca.verdi@example.com'], reason: 'keys' } };
  const { toggle } = setupDetails(answer);
  await toggle.set(true);
  assert.equal(toggle.wantsEncryption(), false);
});

test('with encryption on, the send asks for encryption', async () => {
  const answer = { value: CAN };
  const { toggle } = setupDetails(answer);
  await toggle.set(true);
  assert.equal(toggle.wantsEncryption(), true);
});

test('fingerprints are shown only while encryption is on', async () => {
  const answer = { value: CAN };
  const { toggle, doc } = setupDetails(answer);
  await toggle.set(true);
  assert.equal(doc.querySelectorAll('#d div').length, 2);
  await toggle.set(false);
  assert.equal(doc.getElementById('d').textContent, '');
  assert.equal(doc.getElementById('d').hidden, true);
});

test('an address with markup goes into the details as text', async () => {
  const answer = { value: { ...KEY_CHANGED, pending: [{ address: '"><img src=x>@example.com' }] } };
  const { toggle, doc } = setupDetails(answer);
  await toggle.set(true);
  assert.equal(doc.querySelector('#d img'), null);
  assert.equal(doc.querySelector('#d [data-key-change]').getAttribute('data-key-change'), '"><img src=x>@example.com');
});

test('the badge says "signed by" only for a signature that matches the sender', () => {
  assert.equal(encryptionLabel(null, T), null);
  assert.equal(encryptionLabel({ encrypted: false }, T), null);
  assert.equal(encryptionLabel({ encrypted: true, decrypted: false }, T).tone, 'bad');
  const ok = encryptionLabel({ encrypted: true, decrypted: true, signature_valid: true,
    signer: 'anna.bianchi@example.com', signer_matches_from: true }, T);
  assert.equal(ok.tone, 'ok');
  assert.match(ok.text, /firmata da anna\.bianchi@example\.com/);
  const other = encryptionLabel({ encrypted: true, decrypted: true, signature_valid: true,
    signer: 'luca.verdi@example.com', signer_matches_from: false }, T);
  assert.equal(other.tone, 'warn');
  assert.equal(encryptionLabel({ encrypted: true, decrypted: true }, T).tone, 'warn');
});

test('the badge escapes the signer address', () => {
  const esc = (s) => String(s).replace(/</g, '&lt;');
  const html = encryptionBadgeHtml({ encrypted: true, decrypted: true, signature_valid: true,
    signer: '<img>@example.com', signer_matches_from: true }, T, esc);
  assert.ok(!html.includes('<img>'));
  assert.equal(encryptionBadgeHtml(null, T, esc), '');
});
