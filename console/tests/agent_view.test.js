// Unit tests of renderer_agent.js (window.AgentView): the mails the agent
// mentions become links that open the mail.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const BAR = `
  <div id="agentBar"><div id="agentThread"></div>
    <div id="agentChip" hidden><span id="agentChipText"></span><button id="agentChipX"></button></div>
    <textarea id="agentInput"></textarea><button id="agentSend"></button><button id="agentClear"></button>
  </div>
  <div id="mailDetail"></div>`;

function load({ activeAccount = 6, group = null } = {}) {
  const dom = new JSDOM(`<!DOCTYPE html><body>${BAR}</body>`, { runScripts: 'outside-only' });
  const w = dom.window;
  const calls = { pane: [], window: [] };
  w.activeAccountId = activeAccount;
  w.activeGroup = group;
  w.openMail = (id, folder) => calls.pane.push({ id, folder });
  w.electronAPI = {
    agentCommand: async () => ({ answer: '' }),
    // the page builds `data` in its own realm: copy it to compare it here
    openMailWindow: (data) => calls.window.push({ ...data }),
  };
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_agent.js'), 'utf-8'),
    dom.getInternalVMContext());
  return { w, calls };
}

// The script hooks its click handler on DOMContentLoaded, which JSDOM fires
// just after construction.
function ready(w) {
  if (w.document.readyState !== 'loading') return Promise.resolve();
  return new Promise((r) => w.document.addEventListener('DOMContentLoaded', () => r(), { once: true }));
}

function render(w, text) {
  const th = w.document.getElementById('agentThread');
  th.innerHTML = w.AgentView.formatAnswer(text);
  return th;
}

test('a mail link becomes a clickable link with account, id and folder', () => {
  const { w } = load();
  const th = render(w, '- [Invoice March](gigamail://mail/6/arch-123?folder=INBOX) from Mario');
  const a = th.querySelector('a.agent-mail-link');
  assert.ok(a);
  assert.equal(a.textContent, 'Invoice March');
  assert.equal(a.dataset.account, '6');
  assert.equal(a.dataset.id, 'arch-123');
  assert.equal(a.dataset.folder, 'INBOX');
  assert.ok(th.textContent.includes('from Mario'));
});

test('ids with slashes and padding survive, folder is optional', () => {
  const { w } = load();
  const th = render(w, '[Hello](gigamail://mail/2/AAMk/x+y==)');
  const a = th.querySelector('a.agent-mail-link');
  assert.equal(a.dataset.id, 'AAMk/x+y==');
  assert.equal(a.dataset.folder, '');
});

test('the subject is escaped: markup in it does not run', () => {
  const { w } = load();
  const th = render(w, '[<img src=x onerror="window.__xss=1">](gigamail://mail/6/42)');
  assert.equal(th.querySelectorAll('img').length, 0);
  assert.ok(th.querySelector('a.agent-mail-link').textContent.includes('<img'));
});

test('other links stay plain text: only the gigamail://mail scheme is clickable', () => {
  const { w } = load();
  const th = render(w, '[pay here](https://evil.example.com) and [x](javascript:alert(1))');
  assert.equal(th.querySelectorAll('a').length, 0);
  assert.ok(th.textContent.includes('https://evil.example.com'));
});

test('bold and line breaks still work around a link', () => {
  const { w } = load();
  const th = render(w, '**Found:**\n[A](gigamail://mail/6/1)');
  assert.ok(th.querySelector('strong'));
  assert.ok(th.querySelector('br'));
  assert.ok(th.querySelector('a.agent-mail-link'));
});

test('click on a mail of the account on screen opens it in the reading pane', async () => {
  const { w, calls } = load({ activeAccount: 6 });
  await ready(w);
  const th = render(w, '[A](gigamail://mail/6/arch-9?folder=Posta%20inviata)');
  th.querySelector('a').dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.deepEqual(calls.pane, [{ id: 'arch-9', folder: 'Posta inviata' }]);
  assert.equal(calls.window.length, 0);
});

test('click on a mail of another account opens its own window for that account', async () => {
  const { w, calls } = load({ activeAccount: 1 });
  await ready(w);
  const th = render(w, '[A](gigamail://mail/6/77?folder=INBOX)');
  th.querySelector('a').dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.equal(calls.pane.length, 0);
  assert.deepEqual(calls.window, [{ id: '77', folder: 'INBOX', account_id: 6 }]);
});

test('the confirmation after an approval carries the request it came from', async () => {
  const { w } = load();
  const sent = [];
  w.electronAPI.agentCommand = async () => ({
    answer: 'Waiting for you.', approvals: [{ request_id: 'req_1', tool: 'reply_mail', subject: 'Re: Visit' }] });
  w.electronAPI.approveRequest = async () => ({ ok: true });
  w.electronAPI.agentComplete = async (body) => { sent.push({ ...body }); return { answer: 'Hecho.', status: 'executed' }; };
  await ready(w);
  const ta = w.document.getElementById('agentInput');
  ta.value = 'responde a Anna que vale';
  ta.dispatchEvent(new w.Event('input'));
  w.document.getElementById('agentSend').click();
  await new Promise((r) => setTimeout(r, 20));
  w.document.querySelector('[data-act="approve"]').click();
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].request_id, 'req_1');
  assert.equal(sent[0].question, 'responde a Anna que vale');
});

test('the approval card shows the recipient and the full text to approve', async () => {
  const { w } = load();
  w.electronAPI.agentCommand = async () => ({
    answer: 'Ready.', approvals: [{ request_id: 'req_2', tool: 'reply_mail', subject: 'Re: Info',
      summary: 'to=bruna@example.com', to: 'bruna@example.com', body: 'Consegna <primavera 2028>.\nGrazie.' }] });
  await ready(w);
  const ta = w.document.getElementById('agentInput');
  ta.value = 'rispondi a Bruna';
  ta.dispatchEvent(new w.Event('input'));
  w.document.getElementById('agentSend').click();
  await new Promise((r) => setTimeout(r, 20));
  const card = w.document.querySelector('.agent-msg.approval');
  assert.match(card.textContent, /bruna@example\.com/);
  const pre = card.querySelector('.agent-appr-body pre');
  assert.equal(pre.textContent, 'Consegna <primavera 2028>.\nGrazie.');
  assert.equal(card.querySelectorAll('.agent-appr-sum').length, 1);
});

test('in a merged view of several accounts the mail opens in its own window', async () => {
  const { w, calls } = load({ activeAccount: 6, group: 'g1' });
  await ready(w);
  const th = render(w, '[A](gigamail://mail/6/77)');
  th.querySelector('a').dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.equal(calls.pane.length, 0);
  assert.deepEqual(calls.window, [{ id: '77', folder: null, account_id: 6 }]);
});

test('when the backend already executed the approved request, the agent is not called again', async () => {
  const { w } = load();
  let completed = 0;
  w.electronAPI.agentCommand = async () => ({
    answer: 'Waiting.', approvals: [{ request_id: 'req_9', tool: 'send_mail', subject: 'Offer' }] });
  w.electronAPI.approveRequest = async () => ({ success: true, status: 'executed', outcome: 'ok', completed_by: 'agent' });
  w.electronAPI.agentComplete = async () => { completed += 1; return { answer: 'x', status: 'executed' }; };
  await ready(w);
  const ta = w.document.getElementById('agentInput');
  ta.value = 'send the offer';
  ta.dispatchEvent(new w.Event('input'));
  w.document.getElementById('agentSend').click();
  await new Promise((r) => setTimeout(r, 20));
  w.document.querySelector('[data-act="approve"]').click();
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(completed, 0);
  assert.ok(w.document.querySelector('.agent-msg.approval').classList.contains('approved'));
  assert.match(w.document.querySelector('.agent-appr-head').textContent, /eseguita/i);
});
