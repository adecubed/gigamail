// Edit on a rule card: the rule goes into the form, Create becomes Save,
// and Save sends the changed fields to PUT /rules/{id}; the rule keeps
// its id. renderer_automations.js runs in JSDOM with a stub backend.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const RULE = {
  rule_id: 'rule_1', account_id: 2, trigger_kind: 'senders',
  trigger_values: ['postmaster@example.com'], reply_style: 'attach plans B.1.3, A.1.4 and B.1.4',
  doc_paths: ['C:/docs/listino.xlsx'], mode: 'semi', first_contact: 'semi',
  daily_cap: 10, cooldown_hours: 4, expiry_days: 30,
  expires_at: Date.now() / 1000 + 29 * 86400, created_at: Date.now() / 1000,
  paused: false, expired: false, expiring: false, state: 'active', sent_today: 0,
  attachments: ['B.1.3.pdf', 'A.1.4.pdf', 'B.1.4.pdf'], cc: [],
};

test('Edit on a rule card fills the form and Save puts the changes to the rule', async () => {
  const html = `<!DOCTYPE html><body>
    <div class="sidebar"><div class="s-item" id="btnShowAutomations"><span class="s-badge" id="pendingBadge" hidden></span></div></div>
    <div class="view active" id="view-mail"></div>
    <div class="view" id="view-automations"><div class="auto-body">
      <div id="pendingList"></div><div id="recentList"></div><div id="rulesList"></div>
      <div id="ruleForm">
        <div id="ruleFormTitle">Nuova regola</div>
        <select id="ruleAccount"><option value="2">info@example.com</option></select>
        <select id="ruleTriggerKind"><option value="senders">s</option><option value="folder">f</option></select>
        <input id="ruleTriggerValues"/><div id="ruleFolderWarn"></div>
        <textarea id="ruleStyle"></textarea><div id="ruleDocsList"></div>
        <input id="ruleAttachments"/><input id="ruleCc"/>
        <select id="ruleMode"><option value="semi">semi</option><option value="auto">auto</option></select>
        <div id="ruleFirstContactRow"><select id="ruleFirstContact"><option value="semi">semi</option><option value="auto">auto</option></select></div>
        <input id="ruleCap" type="number"/><input id="ruleCooldown" type="number"/><input id="ruleExpiry" type="number"/>
        <span id="ruleFormStatus"></span>
        <button id="btnCancelEdit" style="display:none">Annulla</button>
        <button id="btnCreateRule">Crea regola</button>
      </div>
    </div></div></body>`;
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window;
  const calls = [];
  let rules = [RULE];
  w.fetch = async (url, opts = {}) => {
    const p = String(url).replace('http://127.0.0.1:8002', '');
    calls.push({ method: opts.method || 'GET', path: p, body: opts.body ? JSON.parse(opts.body) : null });
    if (p === '/rules') return { ok: true, status: 200, json: async () => rules };
    if (p === '/rules/rule_1' && opts.method === 'PUT') {
      const changed = { ...RULE, ...JSON.parse(opts.body) };
      rules = [changed];
      return { ok: true, status: 200, json: async () => changed };
    }
    if (p === '/approvals' || p.startsWith('/approvals/recent')) return { ok: true, status: 200, json: async () => [] };
    if (p === '/accounts') return { ok: true, status: 200, json: async () => [{ id: 2, email: 'info@example.com', active: true }] };
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
  const $ = (id) => w.document.getElementById(id);
  try {
  w.document.getElementById('btnShowAutomations').click();
  await tick();
  const card = $('rulesList').querySelector('.ai-card[data-rule="rule_1"]');
  assert.ok(card, 'the rule is listed');
  const edit = card.querySelector('button[data-act="edit"]');
  assert.ok(edit, 'the card has Edit');
  edit.click();
  await tick();
  // the form holds the rule, Create became Save, Cancel is visible
  assert.equal($('ruleStyle').value, RULE.reply_style);
  assert.equal($('ruleTriggerValues').value, 'postmaster@example.com');
  assert.equal($('ruleAttachments').value, 'B.1.3.pdf, A.1.4.pdf, B.1.4.pdf');
  assert.equal($('ruleCap').value, '10');
  assert.ok($('ruleDocsList').textContent.includes('listino.xlsx'));
  assert.ok($('btnCreateRule').textContent.includes('Salva'));
  assert.notEqual($('btnCancelEdit').style.display, 'none');
  assert.ok(!calls.some((c) => c.method === 'PUT'), 'nothing is sent by opening the edit');

  // the person corrects the instruction and the fixed attachments, then saves
  $('ruleStyle').value = 'attach the plans of the type the customer asks for';
  $('ruleAttachments').value = '';
  $('ruleCc').value = 'ufficio@example.com';
  $('btnCreateRule').click();
  await tick();
  const put = calls.find((c) => c.method === 'PUT');
  assert.ok(put, 'Save puts the rule');
  assert.equal(put.path, '/rules/rule_1');
  assert.equal(put.body.reply_style, 'attach the plans of the type the customer asks for');
  assert.deepEqual(put.body.attachments, []);
  assert.deepEqual(put.body.cc, ['ufficio@example.com']);
  assert.deepEqual(put.body.doc_paths, ['C:/docs/listino.xlsx']);
  assert.equal(put.body.account_id, undefined, 'the account of a rule does not change');
  assert.equal(put.body.expiry_days, undefined, 'the expiry of a rule does not change');
  assert.ok(!calls.some((c) => c.method === 'POST' && c.path === '/rules'), 'no second rule is created');
  // back to the empty creation form, the list shows the new instruction
  assert.ok($('btnCreateRule').textContent.includes('Crea'));
  assert.equal($('btnCancelEdit').style.display, 'none');
  assert.equal($('ruleStyle').value, '');
  assert.ok($('ruleFormStatus').textContent.includes('rule_1'));
  assert.ok($('rulesList').textContent.includes('attach the plans of the type the customer asks for'));

  // Cancel leaves the rule alone
  $('rulesList').querySelector('button[data-act="edit"]').click();
  await tick();
  $('btnCancelEdit').click();
  assert.equal($('ruleStyle').value, '');
  assert.ok($('btnCreateRule').textContent.includes('Crea'));
  assert.equal(calls.filter((c) => c.method === 'PUT').length, 1);
  } finally {
    // the page keeps refresh timers: the window must close or the runner waits for them
    w.close();
  }
});
