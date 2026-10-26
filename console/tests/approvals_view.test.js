// The "waiting for you" / "recently decided" cards of the Automations view
// (approvals_view.js): what a request looks like on screen and what the
// outcome labels say.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const V = require('../approvals_view');
const t = (_key, fallback) => fallback;
const NOW = 1_800_000_000;

const WATCHER_REPLY = {
  request_id: 'req_abc', tool: 'reply_mail', status: 'pending', completed_by: 'watcher',
  expires_at: NOW + 488,
  args: { message_id: '3690', account_id: 2, body: 'Dear Sir,\nthanks.' },
  preview: {
    replying_to: { from: 'mario.rossi@example.com', subject: 'Message from the site' },
    body: 'Dear Sir,\nthanks.', rule_id: 'rule_x', rule_mode: 'semi',
    to_source: 'address taken from the body',
    attachments: [{ name: 'A.1.pdf', path: 'C:\\docs\\A.1.pdf', size_kb: 400 }],
  },
};

const AGENT_SEND = {
  request_id: 'req_def', tool: 'send_mail', status: 'pending', completed_by: 'agent',
  expires_at: NOW + 60,
  args: { to: 'anna.bianchi@example.com', attachments: ['C:/docs/B.2.pdf'] },
  preview: { to: 'anna.bianchi@example.com', subject: 'Visit <b>tomorrow</b>', body: 'Hello' },
};

test('a watcher draft: recipient and subject come from the mail it answers', () => {
  const s = V.summarize(WATCHER_REPLY, NOW);
  assert.equal(s.completedBy, 'watcher');
  assert.equal(s.to, 'mario.rossi@example.com');
  assert.equal(s.subject, 'Message from the site');
  assert.equal(s.ruleMode, 'semi');
  assert.equal(s.expiresIn, 488);
  assert.equal(s.expired, false);
  assert.deepEqual(s.attachments, ['A.1.pdf']);
});

test('an agent request: explicit recipient, attachments by file name', () => {
  const s = V.summarize(AGENT_SEND, NOW);
  assert.equal(s.completedBy, 'agent');
  assert.equal(s.to, 'anna.bianchi@example.com');
  assert.deepEqual(s.attachments, ['B.2.pdf']);
  assert.equal(V.addressOf([{ address: 'a@example.com' }, 'b@example.com']), 'a@example.com, b@example.com');
});

test('the pending card has approve and reject for that request and escapes the subject', () => {
  const html = V.pendingCard(AGENT_SEND, t, NOW);
  assert.match(html, /data-act="approve" data-id="req_def"/);
  assert.match(html, /data-act="reject" data-id="req_def"/);
  assert.ok(html.includes('Visit &lt;b&gt;tomorrow&lt;/b&gt;'));
  assert.ok(!html.includes('<b>tomorrow</b>'));
  assert.ok(html.includes('scade tra 1m00s'));
  assert.ok(html.includes('richiesta dell&#39;agente'));   // the label goes through the same escaping
});

test('the watcher card names the rule mode, the recipient source and the expiry', () => {
  const html = V.pendingCard(WATCHER_REPLY, t, NOW);
  assert.ok(html.includes('bozza del watcher'));
  assert.ok(html.includes('SEMI'));
  assert.ok(html.includes('address taken from the body'));
  assert.ok(html.includes('scade tra 8m08s'));
  assert.ok(/A\.1\.pdf/.test(html), 'attachments listed');
  assert.ok(html.includes('Dear Sir,\nthanks.'));
});

test('outcome labels: executed means consumed, the provider outcome says sent', () => {
  const o = (patch) => V.outcomeOf(V.summarize({ ...AGENT_SEND, ...patch }, NOW), t).text;
  assert.equal(o({ status: 'executed', execution_outcome: 'ok' }), 'inviata');
  assert.equal(o({ status: 'executed', execution_outcome: 'failed' }), 'invio fallito');
  assert.equal(o({ status: 'executed', execution_outcome: 'dryrun' }), 'prova, non inviata');
  assert.equal(o({ status: 'executed' }), 'in esecuzione');
  assert.equal(o({ status: 'approved', completed_by: 'watcher' }), 'approvata, la invia il watcher');
  assert.equal(o({ status: 'approved' }), 'approvata, in esecuzione');
  assert.equal(o({ status: 'rejected' }), 'rifiutata');
  assert.equal(o({ status: 'pending', expires_at: NOW - 5 }), 'scaduta senza decisione');
});

test('the recent card says who decided, by channel', () => {
  const html = V.recentCard({ ...AGENT_SEND, status: 'rejected', decided_by: 'console:tester', decided_at: NOW }, t, NOW);
  assert.ok(html.includes('rifiutata'));
  assert.ok(html.includes('console'));
  assert.ok(!html.includes('console:tester'));          // the user name stays out of the card
  const tg = V.recentCard({ ...AGENT_SEND, status: 'approved', decided_by: 'telegram:123+pin', decided_at: NOW }, t, NOW);
  assert.ok(tg.includes('Telegram') && !tg.includes('123'));
});

test('badge and expiry formatting', () => {
  assert.equal(V.badgeText(0), '');
  assert.equal(V.badgeText(3), '3');
  assert.equal(V.badgeText(12), '9+');
  assert.equal(V.fmtEta(0, t), 'scaduta');
  assert.equal(V.fmtEta(45, t), 'scade tra 45s');
});

// The Automations view wired for real: renderer_automations.js in JSDOM with a
// stub backend. Opening the view lists the request, the badge counts it,
// Reject posts to the backend and the list is read again.
test('opening Automations lists what waits, counts it on the badge, and Reject reaches the backend', async () => {
  const vm = require('node:vm');
  const { JSDOM } = require('jsdom');
  const html = `<!DOCTYPE html><body>
    <div class="sidebar">
      <div class="s-item" id="btnShowAutomations"><span class="s-badge" id="pendingBadge" hidden></span></div>
    </div>
    <div class="view active" id="view-mail"></div>
    <div class="view" id="view-automations"><div class="auto-body">
      <div id="pendingList"></div><div id="recentList"></div><div id="rulesList"></div>
      <select id="ruleTriggerKind"><option value="senders">s</option></select>
      <input id="ruleTriggerValues"/><div id="ruleFolderWarn"></div>
      <select id="ruleMode"><option value="semi">semi</option></select><div id="ruleFirstContactRow"></div>
    </div></div></body>`;
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window;
  const calls = [];
  let pending = [WATCHER_REPLY];
  w.fetch = async (url, opts = {}) => {
    const p = String(url).replace('http://127.0.0.1:8002', '');
    calls.push(`${opts.method || 'GET'} ${p}`);
    if (p === '/approvals') return { ok: true, status: 200, json: async () => pending };
    if (p.startsWith('/approvals/recent')) {
      // decided a minute ago: seen once the page opens, so the icon only
      // counts what is still to decide
      return { ok: true, status: 200, json: async () => [{ ...AGENT_SEND, status: 'rejected', decided_by: 'console:tester', decided_at: Date.now() / 1000 - 60 }] };
    }
    if (p === '/approvals/req_abc/reject') { pending = []; return { ok: true, status: 200, json: async () => ({ success: true }) }; }
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
  try {
  w.document.getElementById('btnShowAutomations').click();
  await tick();
  assert.ok(w.document.getElementById('view-automations').classList.contains('active'));
  const list = w.document.getElementById('pendingList');
  assert.ok(list.querySelector('.pending-card[data-request="req_abc"]'), 'the waiting request is listed');
  assert.ok(list.textContent.includes('mario.rossi@example.com'));
  const badge = w.document.getElementById('pendingBadge');
  assert.equal(badge.textContent, '1');
  assert.equal(badge.hidden, false);
  assert.ok(w.document.getElementById('recentList').textContent.includes('rifiutata'));

  list.querySelector('button[data-act="reject"]').click();
  await tick();
  assert.ok(calls.includes('POST /approvals/req_abc/reject'), calls.join(', '));
  assert.ok(!list.querySelector('.pending-card'), 'the list is read again after the decision');
  assert.equal(badge.hidden, true);
  } finally {
    // a failed assertion must not leave the window's timers running: the
    // test process would never exit
    w.close();
  }
});

test('Waiting for you has its own view and icon, which carries the badge', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index_v2.html'), 'utf-8');
  assert.ok(html.includes('id="pendingList"'));
  assert.ok(html.includes('id="recentList"'));
  // Waiting for you has its own icon, under Automations, and carries the badge
  assert.match(html, /id="btnShowPending"[^>]*><span class="s-badge" id="pendingBadge" hidden>/);
  assert.ok(html.indexOf('id="btnShowPending"') > html.indexOf('id="btnShowAutomations"'));
  assert.ok(html.includes('id="view-pending"'));
  assert.ok(html.includes('src="approvals_view.js"'));
  const auto = fs.readFileSync(path.join(__dirname, '..', 'renderer_automations.js'), 'utf-8');
  assert.ok(auto.includes("api('/approvals')") && auto.includes("/approvals/recent"));
  assert.ok(auto.includes("$('pendingList')?.addEventListener('click', onPendingAction)"));
});


test('a recently decided card opens on what was sent, escaped', () => {
  const t = (k, f) => f;
  const rec = { ...AGENT_SEND, status: 'executed', execution_outcome: 'ok', decided_by: 'console:tester', decided_at: NOW,
    created_at: NOW - 60, provider_result: { accepted: ['anna.bianchi@example.com'] } };
  const html = V.recentCard(rec, t, NOW);
  assert.ok(html.startsWith('\n      <details class="ai-card recent-card"'));
  assert.ok(html.includes('<summary>') && html.includes('class="recent-detail"'));
  assert.ok(html.includes('anna.bianchi@example.com'));
  assert.ok(html.includes('Visit &lt;b&gt;tomorrow&lt;/b&gt;'));     // subject escaped in the detail too
  assert.ok(!html.includes('<b>tomorrow</b>'));
  assert.ok(html.includes('class="recent-body">Hello</pre>'));
  const failed = V.recentCard({ ...rec, execution_outcome: 'failed', provider_result: { error: 'SMTP <550>' } }, t, NOW);
  assert.ok(failed.includes('SMTP &lt;550&gt;'));
});

test('a request whose notification failed says so, with the channel and the reason', () => {
  const rec = { ...WATCHER_REPLY, status: 'expired', expires_at: NOW - 10,
    notified: [{ channel: 'desktop', ok: true, error: '' },
      { channel: 'telegram', ok: false, error: 'sendMessage: 401 Unauthorized' }] };
  const s = V.summarize(rec, NOW);
  assert.equal(V.notifyFailed(s), true);
  assert.equal(V.notifiedText(s, t), 'desktop ✓ · telegram: sendMessage: 401 Unauthorized');
  const html = V.recentCard(rec, t, NOW);
  assert.match(html, /notifica non arrivata/);
  assert.match(html, /Notifiche<\/span><span class="recent-v">desktop ✓ · telegram: sendMessage: 401 Unauthorized/);
  // all delivered, or nothing recorded: no tag
  assert.doesNotMatch(V.pendingCard(WATCHER_REPLY, t, NOW), /notifica non arrivata/);
  const ok = { ...WATCHER_REPLY, notified: [{ channel: 'telegram', ok: true, error: '' }] };
  assert.doesNotMatch(V.pendingCard(ok, t, NOW), /notifica non arrivata/);
});

test('only a rule paused by the burst guard counts as paused by itself', () => {
  const rules = [
    { rule_id: 'a', state: 'paused', pause_reason: 'raffica: 10 match in 10 minuti' },
    { rule_id: 'b', state: 'paused', pause_reason: 'burst: 6 matches in 10 minutes' },
    { rule_id: 'c', state: 'paused', pause_reason: '' },
    { rule_id: 'd', state: 'active', pause_reason: 'raffica: 10 match in 10 minuti' },
    { rule_id: 'e', state: 'expired' },
  ];
  assert.deepEqual(V.autoPaused(rules).map((r) => r.rule_id), ['a', 'b']);
  assert.deepEqual(V.autoPaused([]), []);
});

test('the icon counts what is to decide and what was decided since the page was last opened, by colour', () => {
  const decided = (over, at, extra = {}) => ({ ...AGENT_SEND, request_id: 'r' + at, status: 'executed',
    decided_at: at, execution_outcome: over, ...extra });
  const recent = [
    decided('ok', NOW - 100),                       // sent → green
    decided('failed', NOW - 90),                    // send failed → red
    { ...AGENT_SEND, request_id: 'exp', status: 'pending', expires_at: NOW - 80 },   // expired → red
    { ...AGENT_SEND, request_id: 'app', status: 'approved', decided_at: NOW - 70 },  // executing → amber
    { ...AGENT_SEND, request_id: 'rej', status: 'rejected', decided_at: NOW - 60 },  // rejected → red
    decided('ok', NOW - 1000),                      // before the last visit: not counted
  ];
  assert.deepEqual(V.badgeCounts([WATCHER_REPLY], recent, NOW - 500, NOW), { todo: 1, ok: 1, warn: 1, err: 3 });
  // the page opened just now: only what is still to decide remains
  assert.deepEqual(V.badgeCounts([WATCHER_REPLY], recent, NOW, NOW), { todo: 1, ok: 0, warn: 0, err: 0 });
  assert.deepEqual(V.badgeCounts([], [], 0, NOW), { todo: 0, ok: 0, warn: 0, err: 0 });
});
