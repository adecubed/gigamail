// The popup a toast button opens for a request (approval_window.html):
// renders the request, approves and rejects through the backend, and edits
// by closing the request with a note.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const NOW = Date.now() / 1000;
const REQ = {
  request_id: 'req_1', tool: 'reply_mail', status: 'pending', expires_at: NOW + 600,
  args: { message_id: 'm1', body: 'Gentile Bruna,\nla consegna è prevista nel 2028.' },
  preview: { replying_to: { from: 'bruna@example.com', subject: 'Richiesta informazioni' },
    body: 'Gentile Bruna,\nla consegna è prevista nel 2028.', attachments: [{ name: 'A.1.pdf' }] },
};

function open(responses) {
  const html = fs.readFileSync(path.join(__dirname, '..', 'approval_window.html'), 'utf-8')
    .replace(/<script src="[^"]+"><\/script>/g, '').replace(/<link[^>]+>/g, '');
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window;
  const calls = [];
  let loaded = null;
  w.fetch = async (url, opts = {}) => {
    const p = String(url).replace('http://127.0.0.1:8002', '');
    calls.push(`${opts.method || 'GET'} ${p}${opts.body ? ' ' + opts.body : ''}`);
    const r = responses(p, opts);
    return { ok: r.status === 200, status: r.status, json: async () => r.body };
  };
  w.GM_CLOSE_DELAY = 0;   // the window closes itself after a decision: at once here
  w.approvalWindowAPI = { onLoad: (cb) => { loaded = cb; }, close() { calls.push('close'); }, minimize() {} };
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'approval_window_page.js'), 'utf-8'), dom.getInternalVMContext());
  const tick = () => new Promise((r) => setTimeout(r, 20));
  return { w, calls, load: async (d) => { await loaded(d); await tick(); }, tick };
}

test('shows who, what and the text, and approves through the backend as executed', async () => {
  let rec = REQ;
  const { w, calls, load, tick } = open((p) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/approve') { rec = { ...rec, status: 'executed', execution_outcome: 'ok' }; return { status: 200, body: { status: 'executed', outcome: 'ok' } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  await load({ request_id: 'req_1', action: 'show' });
  const d = w.document;
  assert.equal(d.getElementById('to').textContent, 'bruna@example.com');
  assert.equal(d.getElementById('subject').textContent, 'Richiesta informazioni');
  assert.match(d.getElementById('body').textContent, /consegna è prevista/);
  assert.equal(d.getElementById('attachments').textContent, 'A.1.pdf');
  assert.match(d.getElementById('state').textContent, /in attesa/);
  d.getElementById('btnApprove').click();
  await tick();
  assert.ok(calls.includes('POST /approvals/req_1/approve'));
  assert.match(d.getElementById('status').textContent, /eseguita/);
  assert.match(d.getElementById('state').textContent, /inviata/);
  assert.equal(d.getElementById('btnApprove').disabled, true);
  await tick();
  assert.ok(calls.includes('close'), 'the window closes by itself once decided');
});

test('Edit closes the request with a note; Reject from the toast rejects at once', async () => {
  let rec = REQ;
  const { w, calls, load, tick } = open((p) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/edit') { rec = { ...rec, status: 'rejected' }; return { status: 200, body: { requeued: true } }; }
    if (p === '/approvals/req_1/reject') { rec = { ...rec, status: 'rejected' }; return { status: 200, body: { success: true } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  await load({ request_id: 'req_1', action: 'edit' });
  const d = w.document;
  assert.ok(d.getElementById('editBox').classList.contains('visible'));
  d.getElementById('note').value = 'più breve';
  d.getElementById('btnEdit').click();
  await tick();
  assert.ok(calls.some((c) => c.startsWith('POST /approvals/req_1/edit') && c.includes('più breve')));
  assert.match(d.getElementById('status').textContent, /rimessa in coda/);

  rec = REQ;
  const second = open((p) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/reject') { rec = { ...rec, status: 'rejected' }; return { status: 200, body: { success: true } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  await second.load({ request_id: 'req_1', action: 'reject' });
  assert.ok(second.calls.includes('POST /approvals/req_1/reject'));
  assert.match(second.w.document.getElementById('state').textContent, /rifiutata/);
  await second.tick();
  assert.ok(second.calls.includes('close'));
});

test('a request that is gone stays on screen: nothing was decided', async () => {
  const { w, calls, load, tick } = open(() => ({ status: 404, body: { detail: 'Richiesta inesistente' } }));
  await load({ request_id: 'req_9', action: 'approve' });
  await tick();
  assert.ok(!calls.includes('close'));
  assert.match(w.document.getElementById('state').textContent, /non trovata/);
});

test('an old notification: the request is gone and the buttons are off', async () => {
  const { w, load } = open(() => ({ status: 404, body: { detail: 'Richiesta inesistente' } }));
  await load({ request_id: 'req_9', action: 'approve' });
  assert.match(w.document.getElementById('state').textContent, /non trovata/);
  assert.equal(w.document.getElementById('btnApprove').disabled, true);
});
