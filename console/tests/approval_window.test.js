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
  d.getElementById('note').dispatchEvent(new w.Event('input'));
  d.getElementById('btnNote').click();
  await tick();
  assert.ok(calls.some((c) => c.startsWith('POST /approvals/req_1/edit') && c.includes('più breve')));
  assert.match(d.getElementById('status').textContent, /rimessa in coda/);
  assert.equal(d.getElementById('btnApprove').disabled, true, 'the old text cannot be sent any more');

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

test('Edit opens the text in place: Approve is off until it changes, then sends the corrected version', async () => {
  let rec = REQ;
  const { w, calls, load, tick } = open((p, opts) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/amend') {
      const body = JSON.parse(opts.body).body;
      rec = { ...rec, args: { ...rec.args, body }, preview: { ...rec.preview, body } };
      return { status: 200, body: { success: true, status: 'pending', preview: rec.preview } };
    }
    if (p === '/approvals/req_1/approve') { rec = { ...rec, status: 'executed', execution_outcome: 'ok' }; return { status: 200, body: { status: 'executed', outcome: 'ok' } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  await load({ request_id: 'req_1', action: 'show' });
  const d = w.document;
  assert.equal(d.getElementById('btnApprove').disabled, false);
  d.getElementById('btnEdit').click();
  await tick();
  assert.ok(d.getElementById('editBox').classList.contains('visible'));
  assert.equal(d.getElementById('bodyEdit').style.display, '', 'the text is there to correct');
  assert.match(d.getElementById('bodyEdit').value, /2028/);
  assert.equal(d.getElementById('btnEdit').textContent, 'Annulla modifica');
  assert.equal(d.getElementById('btnApprove').disabled, true, 'untouched text: nothing to send from here');
  assert.equal(d.getElementById('btnSave').disabled, true);
  // Approve clicked anyway sends nothing
  d.getElementById('btnApprove').click();
  await tick();
  assert.ok(!calls.some((c) => c.includes('/approve')));
  d.getElementById('bodyEdit').value = 'Gentile Bruna,\nla consegna è prevista nel 2027.';
  d.getElementById('bodyEdit').dispatchEvent(new w.Event('input'));
  assert.equal(d.getElementById('btnApprove').disabled, false);
  assert.equal(d.getElementById('btnApprove').textContent, 'Invia modificata');
  d.getElementById('btnApprove').click();
  await tick();
  const amend = calls.findIndex((c) => c.startsWith('POST /approvals/req_1/amend') && c.includes('2027'));
  const approve = calls.indexOf('POST /approvals/req_1/approve');
  assert.ok(amend >= 0 && approve > amend, `the text goes first, then the approval: ${calls.join(' | ')}`);
  assert.match(d.getElementById('status').textContent, /eseguita/);
  assert.match(d.getElementById('state').textContent, /inviata/);
  await tick();
  assert.ok(calls.includes('close'));
});

test('Edit takes files from anywhere: they go with the amend, then the approval sends', async () => {
  let rec = { ...REQ, tool: 'reply_mail' };
  const { w, calls, load, tick } = open((p, opts) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/amend') {
      const names = JSON.parse(opts.body).attachments.map((f) => ({ name: f.name }));
      rec = { ...rec, preview: { ...rec.preview, attachments: [...rec.preview.attachments, ...names] } };
      return { status: 200, body: { success: true, status: 'pending', preview: rec.preview } };
    }
    if (p === '/approvals/req_1/approve') { rec = { ...rec, status: 'executed', execution_outcome: 'ok' }; return { status: 200, body: { status: 'executed', outcome: 'ok' } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  w.GMAttachmentGuard = { isExecutableName: (n) => /\.exe$/i.test(n) };
  await load({ request_id: 'req_1', action: 'show' });
  const d = w.document;
  assert.ok(!d.getElementById('editBox').classList.contains('visible'), 'no attaching outside the edit box');
  d.getElementById('btnEdit').click();
  assert.equal(d.getElementById('attachRow').style.display, '');
  assert.equal(d.getElementById('btnApprove').disabled, true);
  const pick = async (files) => {
    const input = d.getElementById('fileInput');
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    input.dispatchEvent(new w.Event('change'));
    await tick();
    await tick();
  };
  await pick([new w.File(['MZ'], 'setup.exe')]);
  assert.equal(d.getElementById('addedBox').children.length, 0, 'a program is not attached');
  assert.match(d.getElementById('status').textContent, /setup\.exe/);
  await pick([new w.File(['terms'], 'terms.txt'), new w.File(['plan'], 'floor plan.pdf')]);
  assert.equal(d.getElementById('addedBox').children.length, 2);
  assert.equal(d.getElementById('btnApprove').disabled, false, 'a file alone is a change to send');
  assert.equal(d.getElementById('btnApprove').textContent, 'Invia modificata');
  // the cross on a chip takes the file away
  d.getElementById('addedBox').children[0].querySelector('button').click();
  assert.equal(d.getElementById('addedBox').children.length, 1);
  d.getElementById('btnApprove').click();
  await tick();
  const amend = calls.find((c) => c.startsWith('POST /approvals/req_1/amend'));
  const sent = JSON.parse(amend.slice(amend.indexOf('{')));
  assert.deepEqual(sent, { attachments: [{ name: 'floor plan.pdf', data_b64: Buffer.from('plan').toString('base64') }] });
  assert.ok(calls.indexOf('POST /approvals/req_1/approve') > calls.indexOf(amend));
  assert.equal(d.getElementById('attachments').textContent, 'A.1.pdf, floor plan.pdf');
});

test('files are not offered on a request that sends no mail, and leaving Edit drops them', async () => {
  const other = { ...REQ, tool: 'create_event' };
  const first = open((p) => (p === '/approvals/req_1' ? { status: 200, body: other } : { status: 404, body: {} }));
  await first.load({ request_id: 'req_1', action: 'edit' });
  assert.equal(first.w.document.getElementById('attachRow').style.display, 'none');

  const { w, calls, load, tick } = open((p) => (p === '/approvals/req_1' ? { status: 200, body: REQ } : { status: 404, body: {} }));
  await load({ request_id: 'req_1', action: 'edit' });
  const d = w.document;
  const input = d.getElementById('fileInput');
  Object.defineProperty(input, 'files', { value: [new w.File(['terms'], 'terms.txt')], configurable: true });
  input.dispatchEvent(new w.Event('change'));
  await tick();
  await tick();
  assert.equal(d.getElementById('addedBox').children.length, 1);
  d.getElementById('btnEdit').click();   // "Annulla modifica"
  assert.equal(d.getElementById('addedBox').children.length, 0);
  assert.equal(d.getElementById('btnApprove').textContent, 'Approva');
  assert.ok(!calls.some((c) => c.includes('/amend')));
});

test('a note for the agent keeps Approve off, even with the text changed; Escape and Edit again leave the box', async () => {
  let rec = REQ;
  const { w, calls, load, tick } = open((p) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/edit') { rec = { ...rec, status: 'rejected' }; return { status: 200, body: { requeued: false } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  await load({ request_id: 'req_1', action: 'show' });
  const d = w.document;
  d.getElementById('btnEdit').click();
  d.getElementById('bodyEdit').value = 'altro testo';
  d.getElementById('bodyEdit').dispatchEvent(new w.Event('input'));
  assert.equal(d.getElementById('btnApprove').disabled, false);
  d.getElementById('note').value = 'metti il prezzo';
  d.getElementById('note').dispatchEvent(new w.Event('input'));
  assert.equal(d.getElementById('btnApprove').disabled, true, 'a note is being written: the agent rewrites it');
  assert.equal(d.getElementById('btnNote').disabled, false);
  // Escape closes the box, not the window; Edit again reopens it clean
  d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
  assert.ok(!d.getElementById('editBox').classList.contains('visible'));
  assert.ok(!calls.includes('close'));
  assert.equal(d.getElementById('btnApprove').disabled, false, 'out of the box the request is approvable as it is');
  d.getElementById('btnEdit').click();
  assert.equal(d.getElementById('note').value, '');
  d.getElementById('note').value = 'metti il prezzo';
  d.getElementById('note').dispatchEvent(new w.Event('input'));
  d.getElementById('btnNote').click();
  await tick();
  assert.ok(calls.some((c) => c.startsWith('POST /approvals/req_1/edit') && c.includes('metti il prezzo')));
  assert.ok(!calls.some((c) => c.includes('/amend') || c.includes('/approve')), 'nothing was sent');
  assert.match(d.getElementById('status').textContent, /nuova bozza/);
  assert.equal(d.getElementById('btnApprove').disabled, true);
  await tick();
  assert.ok(calls.includes('close'));
});

test('Edit on a request without a body takes only the note', async () => {
  const moveReq = { request_id: 'req_2', tool: 'move_message', status: 'pending', expires_at: NOW + 600,
    args: { message_id: 'm1', folder_id: 'Archive' }, preview: { from: 'bruna@example.com', folder: 'Archive' } };
  const { w, load } = open((p) => (p === '/approvals/req_2' ? { status: 200, body: moveReq } : { status: 404, body: {} }));
  await load({ request_id: 'req_2', action: 'edit' });
  const d = w.document;
  assert.ok(d.getElementById('editBox').classList.contains('visible'));
  assert.equal(d.getElementById('bodyEdit').style.display, 'none');
  assert.equal(d.getElementById('body').style.display, '');
  assert.equal(d.getElementById('btnApprove').disabled, true);
});

test('Save keeps the request waiting: it says for how long and the window closes', async () => {
  let rec = REQ;
  const { w, calls, load, tick } = open((p) => {
    if (p === '/approvals/req_1') return { status: 200, body: rec };
    if (p === '/approvals/req_1/save') { rec = { ...rec, saved_at: NOW, expires_at: NOW + 7 * 86400 }; return { status: 200, body: { status: 'pending' } }; }
    return { status: 404, body: { detail: 'no' } };
  });
  await load({ request_id: 'req_1', action: 'show' });
  const d = w.document;
  assert.equal(d.getElementById('btnSave').disabled, false);
  d.getElementById('btnSave').click();
  await tick();
  assert.ok(calls.includes('POST /approvals/req_1/save'));
  assert.ok(!calls.some((c) => c.includes('/approve') || c.includes('/reject')), 'saving decides nothing');
  assert.match(d.getElementById('status').textContent, /7 giorni/);
  assert.match(d.getElementById('state').textContent, /salvata · scade tra 7 giorni/);
  assert.equal(d.getElementById('btnApprove').disabled, false, 'still approvable');
  await tick();
  assert.ok(calls.includes('close'));
});

test('Save is off for a request that is no longer waiting', async () => {
  const { w, load } = open((p) => (p === '/approvals/req_1'
    ? { status: 200, body: { ...REQ, status: 'rejected' } } : { status: 404, body: {} }));
  await load({ request_id: 'req_1', action: 'show' });
  assert.equal(w.document.getElementById('btnSave').disabled, true);
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
