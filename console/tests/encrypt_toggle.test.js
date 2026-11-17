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
