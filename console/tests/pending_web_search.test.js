// Approving an internet search from the "waiting for you" list: the approve
// call lasts as long as the search (up to two minutes, no timeout), so the
// card says it is searching and keeps its buttons off until the call returns.
// renderer_automations.js runs in JSDOM with a stub backend.
const test = require('node:test');
const { after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const NOW = Date.now() / 1000;
const WEB = {
  request_id: 'req_w', tool: 'web_search', status: 'pending', completed_by: 'agent',
  expires_at: NOW + 600, editable: false, verified: false,
  args: { question: 'town hall hours' },
  preview: { action: 'web_search', subject: 'Search the internet: «town hall hours»',
    body: 'town hall hours\nNo search starts until you approve.' },
};

// the page keeps refresh timers: the windows must close or the runner waits for them
const windows = [];
after(() => windows.forEach((w) => w.close()));

async function setup(approve) {
  const html = `<!DOCTYPE html><body>
    <div class="sidebar"><div class="s-item" id="btnShowAutomations"><span class="s-badge" id="pendingBadge" hidden></span></div></div>
    <div class="view active" id="view-mail"></div>
    <div class="view" id="view-automations"><div class="auto-body">
      <div id="pendingList"></div><div id="recentList"></div><div id="rulesList"></div>
      <div id="ruleForm">
        <select id="ruleAccount"><option value="2">info@example.com</option></select>
        <select id="ruleTriggerKind"><option value="senders">s</option></select>
        <input id="ruleTriggerValues"/><div id="ruleFolderWarn"></div>
        <textarea id="ruleStyle"></textarea><div id="ruleDocsList"></div>
        <input id="ruleAttachments"/><input id="ruleCc"/>
        <select id="ruleMode"><option value="semi">semi</option></select>
        <div id="ruleFirstContactRow"><select id="ruleFirstContact"><option value="semi">semi</option></select></div>
        <input id="ruleCap" type="number"/><input id="ruleCooldown" type="number"/><input id="ruleExpiry" type="number"/>
        <span id="ruleFormStatus"></span><button id="btnCancelEdit"></button><button id="btnCreateRule"></button>
      </div>
    </div></div></body>`;
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window;
  windows.push(w);
  const calls = [];
  let pending = [WEB];
  w.showToast = (msg, kind) => calls.push(`toast ${kind || ''} ${msg}`);
  w.fetch = async (url, opts = {}) => {
    const p = String(url).replace('http://127.0.0.1:8002', '');
    calls.push(`${opts.method || 'GET'} ${p}`);
    if (p === '/approvals') return { ok: true, status: 200, json: async () => pending };
    if (p.startsWith('/approvals/recent')) return { ok: true, status: 200, json: async () => [] };
    if (p === '/accounts') return { ok: true, status: 200, json: async () => [{ id: 2, email: 'info@example.com', active: true }] };
    if (p === '/rules') return { ok: true, status: 200, json: async () => [] };
    if (p === '/approvals/req_w/approve') {
      const r = await approve();
      if (r.status === 200) pending = [];
      return { ok: r.status === 200, status: r.status, json: async () => r.body };
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'not in this test' }) };
  };
  const ctx = dom.getInternalVMContext();
  for (const f of ['approvals_view.js', 'renderer_automations.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', f), 'utf-8'), ctx);
  }
  if (w.document.readyState === 'loading') {
    await new Promise((r) => w.document.addEventListener('DOMContentLoaded', () => r(), { once: true }));
  }
  const tick = () => new Promise((r) => setTimeout(r, 30));
  w.document.getElementById('btnShowAutomations').click();
  await tick();
  return { w, calls, tick, setPending: (p) => { pending = p; } };
}

test('approving a search from the list shows that it is searching, buttons off, then done', async () => {
  let release;
  const held = new Promise((r) => { release = r; });
  const { w, calls, tick } = await setup(() => held);
  const card = w.document.querySelector('.pending-card[data-tool="web_search"]');
  assert.ok(card, 'the search is listed');
  card.querySelector('button[data-act="approve"]').click();
  await tick();
  assert.ok(calls.includes('POST /approvals/req_w/approve'));
  const wait = card.querySelector('.agent-appr-wait');
  assert.ok(wait && /Ricerca su internet in corso/.test(wait.textContent), 'a waiting line is shown');
  assert.ok([...card.querySelectorAll('button')].every((b) => b.disabled), 'every button is off');
  assert.ok(!calls.some((c) => /Windows Hello/.test(c)), 'no Hello prompt is announced');
  release({ status: 200, body: { status: 'executed', outcome: 'ok', completed_by: 'agent' } });
  await tick();
  assert.ok(calls.some((c) => c.startsWith('toast ok') && /ricerca eseguita/.test(c)));
});

test('a failed search from the list says why, and a refused approval gives the buttons back', async () => {
  let r1 = { status: 200, body: { status: 'executed', outcome: 'failed', error: 'Claude Code gave no answer.' } };
  const first = await setup(async () => r1);
  first.w.document.querySelector('.pending-card button[data-act="approve"]').click();
  await first.tick();
  assert.ok(first.calls.some((c) => c.startsWith('toast error') && /ricerca fallita: Claude Code gave no answer\./.test(c)));

  const second = await setup(async () => ({ status: 409, body: { detail: 'Request not approvable' } }));
  const card = second.w.document.querySelector('.pending-card');
  card.querySelector('button[data-act="approve"]').click();
  await second.tick();
  assert.ok(second.calls.some((c) => c.startsWith('toast error') && /Request not approvable/.test(c)));
  // the list is drawn again from the backend: the request is still pending
  assert.ok(second.w.document.querySelector('.pending-card button[data-act="approve"]'));
  assert.ok([...second.w.document.querySelectorAll('.pending-card button')].every((b) => !b.disabled));
});

test('a redraw during the search keeps the card and its waiting line until the call returns', async () => {
  let release;
  const held = new Promise((r) => { release = r; });
  const { w, tick, setPending } = await setup(() => held);
  const card = w.document.querySelector('.pending-card[data-tool="web_search"]');
  card.querySelector('button[data-act="approve"]').click();
  await tick();
  // approved: the backend no longer lists it as pending, and the list redraws
  setPending([]);
  w.document.getElementById('btnShowAutomations').click();
  await tick();
  const kept = w.document.querySelector('.pending-card[data-request="req_w"]');
  assert.ok(kept, 'the card is still shown');
  assert.ok(/Ricerca su internet in corso/.test(kept.querySelector('.agent-appr-wait')?.textContent || ''),
    'with its waiting line');
  assert.ok([...kept.querySelectorAll('button')].every((b) => b.disabled), 'buttons still off');
  assert.ok(!/Nessuna richiesta in attesa/.test(w.document.getElementById('pendingList').textContent));
  release({ status: 200, body: { status: 'executed', outcome: 'ok', completed_by: 'agent' } });
  await tick();
  // the call returned: the next drawing is the backend's list alone
  assert.equal(w.document.querySelector('.pending-card[data-request="req_w"]'), null);
  assert.ok(/Nessuna richiesta in attesa/.test(w.document.getElementById('pendingList').textContent));
});
