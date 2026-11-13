// GENERA in the Forward window. The window clears mailData.id so the
// forward does not join the original thread; GENERA used to ask the
// backend for mail "null" and replaced the forwarded text with the error.
// It now drafts from the original mail and writes the note above it.
// The page's own applyMailData and GENERA handler run with a fake DOM.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'reply_window_page.js'), 'utf8');

function slice(from, to) {
  const start = SRC.indexOf(from);
  const end = SRC.indexOf(to, start);
  assert.ok(start >= 0 && end > start, `${from} … ${to}`);
  return SRC.slice(start, end);
}

const APPLY = SRC.match(/^async function applyMailData\(data\) \{[\s\S]*?^\}/m)[0];
const GENERATE = slice("document.getElementById('btnGenerate').addEventListener",
  'async function addSuggestedAttachments');

const FORWARDED = '---------- Messaggio inoltrato ----------\nDa: cliente@example.com\n\nVorrei visitare il trilocale.';

function windowWith(response) {
  const el = {};
  const get = (id) => (el[id] ||= {
    id, value: '', textContent: '', innerHTML: '', disabled: false, style: {},
    focus() {}, addEventListener(type, fn) { this.handlers = { ...this.handlers, [type]: fn }; },
  });
  const requests = [];
  const ctx = {
    API: 'http://fixture.invalid', mailData: null, forwardSrc: null, attachments: [],
    instructionContext: '', instructionContextName: '',
    maskOriginalText: '', maskCandidates: [],
    applyMaskToBody() {}, showMaskBadge() {}, renderAttachments() {},
    T: (_key, it) => it, esc: (s) => String(s),
    window: {}, console,
    document: { getElementById: get, querySelector: () => null },
    async fetch(url, opts) {
      if (String(url).endsWith('/mask/detect')) return { json: async () => ({ candidates: [] }) };
      requests.push({ url: String(url), body: JSON.parse(opts.body) });
      if (response instanceof Error) throw response;
      return { ok: true, status: 200, json: async () => response };
    },
  };
  ctx.instrEl = get('instruction');
  vm.createContext(ctx);
  vm.runInContext(`${APPLY}\n${GENERATE}`, ctx);
  return { ctx, get, requests, generate: () => get('btnGenerate').handlers.click() };
}

const FORWARD = {
  mode: 'forward', subject: 'Visita trilocale', account_id: 3,
  forward_body: FORWARDED, forward_attachments: [],
  forward_src_id: '901', forward_src_folder: 'INBOX.Sent', forward_src_account: 3,
};

test('forward: GENERA drafts from the original mail and keeps it below the note', async () => {
  const w = windowWith({ draft: 'Ti inoltro la richiesta del cliente.', suggested_attachments: [] });
  await w.ctx.applyMailData({ ...FORWARD });
  assert.equal(w.ctx.mailData.id, null, 'the forward still stays out of the original thread');
  w.get('replyTo').value = 'mario.rossi@example.com';
  w.ctx.instrEl.value = 'digli che il cliente vuole visitare';
  await w.generate();

  const [req] = w.requests;
  assert.match(req.url, /\/mail\/901\/smart_draft\?account_id=3&folder=INBOX\.Sent$/);
  assert.equal(req.body.mode, 'forward');
  assert.equal(req.body.to, 'mario.rossi@example.com');
  assert.equal(w.get('replyText').value, `Ti inoltro la richiesta del cliente.\n\n${FORWARDED}`);
});

test('forward: an error goes above the forwarded mail, which stays', async () => {
  const w = windowWith(new Error('agent offline'));
  await w.ctx.applyMailData({ ...FORWARD });
  await w.generate();
  const text = w.get('replyText').value;
  assert.match(text, /^Errore: Error: agent offline/);
  assert.ok(text.endsWith(FORWARDED), 'the forwarded mail is still there');
});

test('reply: GENERA still drafts from the mail being answered, as a reply', async () => {
  const w = windowWith({ draft: 'Buongiorno, la aspetto giovedi.', suggested_attachments: [] });
  await w.ctx.applyMailData({ id: '42', account_id: 3, folder: 'INBOX', subject: 'Visita',
    sender: 'cliente@example.com', body_text: 'Posso venire giovedi?' });
  await w.generate();
  const [req] = w.requests;
  assert.match(req.url, /\/mail\/42\/smart_draft\?account_id=3&folder=INBOX$/);
  assert.equal(req.body.mode, undefined);
  assert.equal(w.get('replyText').value, 'Buongiorno, la aspetto giovedi.');
});
