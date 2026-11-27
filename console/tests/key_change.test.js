// A correspondent's changed OpenPGP key waits for the user's decision:
// the badge and the line of a mail (mail_render.js), the compose status
// (encrypt_toggle.js) and the decision window (key_change_dialog.js).
const test = require('node:test');
const assert = require('node:assert/strict');
const { formatFingerprint, encryptionLabel, encryptionBadgeHtml, keyChangeHtml } = require('../mail_render');
const { statusText, fingerprintLines } = require('../encrypt_toggle');
const { model, open, pendingLine } = require('../key_change_dialog');

const T = (k, it) => it;
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const SIGNED = { encrypted: true, decrypted: true, signature_valid: true };

const INFO = {
  address: 'anna.bianchi@example.com',
  known: { fingerprint: '4f2a91c0', first_seen: 100, last_seen: 200 },
  held: { fingerprint: 'b77e0d15', first_seen: 300, last_seen: 300, state: 'pending' },
};

test('fingerprints are shown upper case in groups of four', () => {
  assert.equal(formatFingerprint('4f2a91c0b77e0d15'), '4F2A 91C0 B77E 0D15');
  assert.equal(formatFingerprint('4F2A 91c0 b7'), '4F2A 91C0 B7');
  assert.equal(formatFingerprint(''), '');
  assert.equal(formatFingerprint(null), '');
});

test('a mail signed with a pending key offers the decision', () => {
  const l = encryptionLabel({ ...SIGNED, signer: 'anna.bianchi@example.com',
    signer_key: 'pending', signer_matches_from: false }, T);
  assert.equal(l.tone, 'warn');
  assert.equal(l.decide, 'anna.bianchi@example.com');
  assert.match(l.text, /non ancora accettata/);
  const html = encryptionBadgeHtml({ ...SIGNED, signer: 'anna.bianchi@example.com',
    signer_key: 'pending', signer_matches_from: false }, T, esc);
  assert.match(html, /data-key-change="anna\.bianchi@example\.com"/);
  assert.match(html, /Vedi e decidi/);
});

test('refused and replaced keys have their own line and never "signed by"', () => {
  const refused = encryptionLabel({ ...SIGNED, signer: 'anna.bianchi@example.com',
    signer_key: 'refused', signer_matches_from: false }, T);
  assert.equal(refused.tone, 'warn');
  assert.match(refused.text, /chiave che hai rifiutato/);
  assert.equal(refused.decide, 'anna.bianchi@example.com');
  assert.doesNotMatch(refused.text, /firmata da/);

  const replaced = encryptionLabel({ ...SIGNED, signer: 'anna.bianchi@example.com',
    signer_key: 'replaced', signer_matches_from: false, signer_fingerprint: '4f2a91c0' }, T);
  assert.equal(replaced.tone, 'warn');
  assert.equal(replaced.text, 'Cifrata · firmata con la chiave precedente di anna.bianchi@example.com');
  assert.equal(replaced.decide, undefined);
  assert.equal(replaced.fingerprint, undefined);
  assert.doesNotMatch(encryptionBadgeHtml({ ...SIGNED, signer: 'anna.bianchi@example.com',
    signer_key: 'replaced', signer_matches_from: false }, T, esc), /data-key-change/);
});

test('an accepted signer shows its fingerprint', () => {
  const enc = { ...SIGNED, signer: 'anna.bianchi@example.com', signer_matches_from: true,
    signer_key: 'accepted', signer_fingerprint: '4f2a91c0b77e0d15' };
  const l = encryptionLabel(enc, T);
  assert.equal(l.tone, 'ok');
  assert.match(l.text, /firmata da anna\.bianchi@example\.com/);
  assert.equal(l.fingerprint, '4F2A 91C0 B77E 0D15');
  assert.match(encryptionBadgeHtml(enc, T, esc), /4F2A 91C0 B77E 0D15/);
  // the user's own key is not a correspondent's: no fingerprint line
  assert.equal(encryptionLabel({ ...enc, signer_key: 'own' }, T).fingerprint, undefined);
});

test('info without signer_key reads as before', () => {
  assert.deepEqual(encryptionLabel({ encrypted: true, decrypted: false }, T),
    { tone: 'bad', text: 'Mail cifrata: nessuna tua chiave può aprirla' });
  assert.deepEqual(encryptionLabel({ ...SIGNED, signer: 'anna.bianchi@example.com', signer_matches_from: true }, T),
    { tone: 'ok', text: 'Cifrata · firmata da anna.bianchi@example.com' });
  assert.deepEqual(encryptionLabel({ ...SIGNED, signer: 'luca.verdi@example.com', signer_matches_from: false }, T),
    { tone: 'warn', text: 'Cifrata · firmata da un altro indirizzo: luca.verdi@example.com' });
  assert.deepEqual(encryptionLabel({ encrypted: true, decrypted: true }, T),
    { tone: 'warn', text: 'Cifrata · mittente non verificato' });
  assert.doesNotMatch(encryptionBadgeHtml({ ...SIGNED, signer: 'anna.bianchi@example.com',
    signer_matches_from: true }, T, esc), /data-key-change|mail-encryption-fpr/);
});

test('a clear mail from a sender with a pending key shows the line', () => {
  const html = keyChangeHtml({ address: 'anna.bianchi@example.com', fingerprint: 'B77E' }, T, esc);
  assert.match(html, /data-key-change="anna\.bianchi@example\.com"/);
  assert.match(html, /anna\.bianchi@example\.com ha una chiave di cifratura nuova, non ancora accettata/);
  assert.match(html, /Vedi e decidi/);
  assert.equal(keyChangeHtml(null, T, esc), '');
  assert.equal(keyChangeHtml({}, T, esc), '');
});

test('the address is escaped in the link', () => {
  const evil = 'x"><img src=x>\'@example.com';
  // the page's esc may not escape quotes (some do not): the attribute must hold anyway
  const html = keyChangeHtml({ address: evil, fingerprint: 'B77E' }, T, esc);
  assert.ok(!html.includes('<img'), html);
  assert.ok(!html.includes('x">'), html);
  assert.match(html, /data-key-change="x&quot;&gt;&lt;img src=x&gt;&#39;@example\.com"/);
  const badge = encryptionBadgeHtml({ ...SIGNED, signer: evil, signer_key: 'pending',
    signer_matches_from: false }, T, esc);
  assert.ok(!badge.includes('<img'), badge);
  assert.ok(!badge.includes('x">'), badge);
});

test('a "$" in an address is put in the text as it is', () => {
  const html = keyChangeHtml({ address: "a$&b$'@example.com" }, T, esc);
  assert.match(html, /a\$&amp;b\$'@example\.com ha una chiave/);
});

test('compose says why it cannot encrypt', () => {
  const s = statusText({ available: true, can_encrypt: false, reason: 'key_changed',
    pending: [{ address: 'anna.bianchi@example.com' }], missing: [] }, T);
  assert.match(s, /anna\.bianchi@example\.com/);
  assert.match(s, /chiave nuova da accettare/);
  assert.equal(s, 'Non posso cifrare per anna.bianchi@example.com: ha una chiave nuova da accettare.');
});

test('fingerprint lines name the user and each recipient', () => {
  const st = { available: true, can_encrypt: true, missing: [], own_fingerprint: 'aaaa1111bbbb2222',
    peers: [{ address: 'anna.bianchi@example.com', fingerprint: '4f2a91c0' },
            { address: 'luca.verdi@example.com', fingerprint: 'c0dec0de' }] };
  assert.deepEqual(fingerprintLines(st, T), [
    'La tua chiave  AAAA 1111 BBBB 2222',
    'anna.bianchi@example.com  4F2A 91C0',
    'luca.verdi@example.com  C0DE C0DE',
  ]);
  assert.deepEqual(fingerprintLines({ ...st, can_encrypt: false }, T), []);
  assert.deepEqual(fingerprintLines(null, T), []);
  assert.deepEqual(fingerprintLines({ can_encrypt: true }, T), []);
});

test('the dialog shows both keys with their dates', () => {
  const m = model(INFO, T, (ts) => `d${ts}`);
  assert.equal(m.title, 'anna.bianchi@example.com ha una chiave di cifratura nuova');
  assert.equal(m.rows.length, 2);
  assert.equal(m.rows[0].fingerprint, '4F2A 91C0');
  assert.equal(m.rows[0].when, 'vista dal d100 al d200');
  assert.equal(m.rows[1].fingerprint, 'B77E 0D15');
  assert.equal(m.rows[1].when, 'arrivata il d300');
  assert.match(m.hint, /per telefono/);
  assert.match(m.keepWarning, /non potrà leggere/);
  assert.equal(m.buttons.length, 3);
  assert.deepEqual(m.buttons.map((b) => b.action), ['accept', 'keep', 'later']);
});

test('the dialog for a refused key offers to accept it after all', () => {
  const m = model({ ...INFO, held: { ...INFO.held, state: 'refused' } }, T, (ts) => `d${ts}`);
  assert.match(m.title, /rifiutato/);
  assert.equal(m.rows[1].label, 'Chiave rifiutata');
  assert.deepEqual(m.buttons.map((b) => b.action), ['accept', 'later']);
  assert.equal(m.buttons[0].label, 'Accettala comunque');
  assert.equal(m.buttons[1].label, 'Chiudi');
  assert.equal(m.keepWarning, '');
});

test('the dialog never focuses the accepting button: a reflexive Enter accepts nothing', () => {
  const pending = model(INFO, T, String);
  assert.equal(pending.focus, 'later');
  assert.ok(pending.buttons.some((b) => b.action === pending.focus));
  const refused = model({ ...INFO, held: { ...INFO.held, state: 'refused' } }, T, String);
  assert.equal(refused.focus, 'later');
  assert.equal(refused.buttons.find((b) => b.action === refused.focus).label, 'Chiudi');
});

// A stand-in for the DOM dialog: records what it was asked to show and
// answers with the scripted choices.
function fakeUi(choices) {
  const shown = [];
  const notices = [];
  let closed = 0;
  return {
    shown, notices, get closed() { return closed; },
    render(m, error) { shown.push({ m, error }); },
    choose() { return Promise.resolve(choices.shift()); },
    notice(text) { notices.push(text); return Promise.resolve(); },
    close() { closed += 1; },
  };
}

function reply(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function scriptedFetch(answers) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    const next = answers.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { fn, calls };
}

test('a decision posts the fingerprint that was shown', async () => {
  const f = scriptedFetch([reply(200, INFO),
    reply(200, { address: INFO.address, outcome: 'accepted', accepted: 'b77e0d15', other: '4f2a91c0' })]);
  const ui = fakeUi(['accept']);
  const done = [];
  const res = await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui,
    formatDate: String, onDone: (r) => done.push(r) });
  assert.equal(f.calls[0].url, 'http://h/encryption/peer_key?address=anna.bianchi%40example.com');
  assert.equal(f.calls[1].url, 'http://h/encryption/peer_key/decide');
  assert.equal(f.calls[1].init.method, 'POST');
  assert.deepEqual(JSON.parse(f.calls[1].init.body),
    { address: INFO.address, fingerprint: 'b77e0d15', accept: true });
  assert.equal(res.outcome, 'accepted');
  assert.deepEqual(done, [res]);
  assert.equal(ui.closed, 1);
});

test('keeping the old key posts accept false', async () => {
  const f = scriptedFetch([reply(200, INFO), reply(200, { address: INFO.address, outcome: 'kept' })]);
  await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui: fakeUi(['keep']), formatDate: String });
  assert.equal(JSON.parse(f.calls[1].init.body).accept, false);
});

test('"Later" closes without calling the server', async () => {
  const f = scriptedFetch([reply(200, INFO)]);
  const ui = fakeUi(['later']);
  const done = [];
  const res = await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui,
    formatDate: String, onDone: (r) => done.push(r) });
  assert.equal(f.calls.length, 1);
  assert.equal(res, null);
  assert.deepEqual(done, [null]);
  assert.equal(ui.closed, 1);
});

test('a 409 on decide reloads the dialog and accepts nothing', async () => {
  const newer = { ...INFO, held: { ...INFO.held, fingerprint: 'c0dec0de', first_seen: 400 } };
  const f = scriptedFetch([
    reply(200, INFO),
    reply(409, { detail: 'La chiave è cambiata nel frattempo.' }),
    reply(200, newer),
  ]);
  const ui = fakeUi(['accept', 'later']);
  const done = [];
  const res = await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui,
    formatDate: String, onDone: (r) => done.push(r) });
  assert.equal(f.calls.length, 3);
  assert.deepEqual(JSON.parse(f.calls[1].init.body).fingerprint, 'b77e0d15');
  assert.equal(f.calls[2].url, 'http://h/encryption/peer_key?address=anna.bianchi%40example.com');
  assert.equal(ui.shown.length, 2);
  assert.equal(ui.shown[1].m.rows[1].fingerprint, 'C0DE C0DE');
  assert.equal(ui.shown[1].error, 'La chiave è cambiata nel frattempo.');
  assert.equal(res, null);
  assert.deepEqual(done, [null]);
});

test('after a 409 with nothing waiting any more the dialog closes with a message', async () => {
  const f = scriptedFetch([
    reply(200, INFO),
    reply(409, { detail: 'Nessuna chiave in attesa.' }),
    reply(200, { address: INFO.address, known: INFO.known, held: null }),
  ]);
  const ui = fakeUi(['accept']);
  const res = await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui, formatDate: String });
  assert.equal(res, null);
  assert.equal(ui.notices.length, 1);
  assert.match(ui.notices[0], /Nessuna chiave in attesa per anna\.bianchi@example\.com/);
  assert.equal(ui.closed, 1);
});

test('a 403 or a network error changes nothing and says so', async () => {
  const f = scriptedFetch([reply(200, INFO), reply(403, { detail: 'no' }), new Error('offline')]);
  const ui = fakeUi(['accept', 'keep', 'later']);
  const res = await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui, formatDate: String });
  assert.equal(res, null);
  // one info read, two posts, no reload
  assert.equal(f.calls.length, 3);
  assert.equal(ui.shown.length, 3);
  assert.ok(ui.shown[1].error);
  assert.ok(ui.shown[2].error);
  assert.notEqual(ui.shown[1].error, ui.shown[2].error);
  // the same keys are shown again: nothing changed
  assert.equal(ui.shown[2].m.rows[1].fingerprint, 'B77E 0D15');
});

test('a dialog whose info cannot be read closes with a message', async () => {
  const f = scriptedFetch([new Error('offline')]);
  const ui = fakeUi([]);
  const done = [];
  const res = await open({ api: 'http://h', address: INFO.address, T, fetchFn: f.fn, ui,
    formatDate: String, onDone: (r) => done.push(r) });
  assert.equal(res, null);
  assert.equal(ui.shown.length, 0);
  assert.equal(ui.notices.length, 1);
  assert.deepEqual(done, [null]);
});

test('the pending line counts', () => {
  assert.equal(pendingLine(0, T), '');
  assert.equal(pendingLine(null, T), '');
  assert.match(pendingLine(2, T), /2/);
  assert.equal(pendingLine(2, T), 'Chiavi nuove da accettare: 2');
});
