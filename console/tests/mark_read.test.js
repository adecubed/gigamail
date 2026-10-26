// A mail the human opens in the console is marked read on the server too.
// The backend reads with BODY.PEEK, so without this the mail came back
// unread as soon as the list reloaded (switching account, for instance).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const R = require('../mail_render');

test('shouldMarkRead: the server flag wins, then what the list showed', () => {
  assert.equal(R.shouldMarkRead({ isRead: true }, true), false);
  assert.equal(R.shouldMarkRead({ isRead: false }, false), true);
  assert.equal(R.shouldMarkRead({}, true), true);        // IMAP: no flag, the list said unread
  assert.equal(R.shouldMarkRead({}, false), false);      // the list said read: nothing to do
  assert.equal(R.shouldMarkRead({}, null), true);        // not from a list: mark, it is harmless
});

test('markReadTarget: archive ids are marked through the provider id and folder', () => {
  assert.deepEqual(R.markReadTarget({}, '365', 'INBOX'), { id: '365', folder: 'INBOX' });
  assert.deepEqual(R.markReadTarget({ provider_id: '453', folder: 'INBOX.Clienti' }, 'arch-86541', 'INBOX'),
    { id: '453', folder: 'INBOX.Clienti' });
  assert.equal(R.markReadTarget({}, 'arch-9', 'INBOX'), null);
  assert.equal(R.markReadTarget({}, '', 'INBOX'), null);
});

test('markReadUrl encodes id, account and folder', () => {
  assert.equal(R.markReadUrl('http://127.0.0.1:8002', { id: 'AA/b=', folder: 'Posta inviata' }, 6),
    'http://127.0.0.1:8002/mail/AA%2Fb%3D/read?account_id=6&folder=Posta%20inviata');
  assert.equal(R.markReadUrl('http://x', { id: '1', folder: null }, null), 'http://x/mail/1/read');
});

// openMail itself, with a fake server: the call happens with the account and
// folder the mail was read from.
function loadMail({ listUnread, msg }) {
  const item = listUnread == null ? '' :
    `<div class="mail-item ${listUnread ? 'unread' : ''}" data-id="42" data-account-id="6"></div>`;
  const dom = new JSDOM(`<!DOCTYPE html><body>${item}<div id="mailDetail"></div></body>`, { runScripts: 'outside-only' });
  const ctx = dom.getInternalVMContext();
  const calls = [];
  dom.window.__fake = { msg, calls };
  vm.runInContext(`
    function esc(v){ return String(v==null?'':v); }
    function T(k, it){ return it; }
    function fmtDate(d){ return ''; }
    function cleanFolder(f){ return f || ''; }
    function byId(id){ return document.getElementById(id); }
    function updateVoiceContext(){}
    function getCurrentFolderRequestValue(){ return 'INBOX'; }
    var activeAccountId = 6, activeGroup = null, currentFolder = 'inbox';
    var api = {
      readMail: async () => window.__fake.msg,
      markRead: async (id, account, folder) => { window.__fake.calls.push({ id, account, folder }); return { success: true }; },
      getTtsUrl: () => '',
    };
  `, ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'mail_render.js'), 'utf-8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_mail.js'), 'utf-8'), ctx);
  return { w: dom.window, calls };
}

const tick = () => new Promise((r) => setTimeout(r, 10));

test('opening an unread mail of the list marks it read on the server', async () => {
  const { w, calls } = loadMail({ listUnread: true, msg: { id: '42', subject: 'Visit' } });
  await w.openMail('42', 'INBOX');
  await tick();
  assert.deepEqual(calls.map((c) => ({ ...c })), [{ id: '42', account: 6, folder: 'INBOX' }]);
  assert.equal(w.document.querySelector('.mail-item').classList.contains('unread'), false);
});

test('opening a mail the list showed as read sends nothing', async () => {
  const { w, calls } = loadMail({ listUnread: false, msg: { id: '42', subject: 'Visit' } });
  await w.openMail('42', 'INBOX');
  await tick();
  assert.equal(calls.length, 0);
});

test('a mail opened from an agent link (archive id) is marked by its provider id', async () => {
  const { w, calls } = loadMail({ listUnread: null,
    msg: { id: 'arch-7', provider_id: '365', folder: 'INBOX', subject: 'Visit' } });
  await w.openMail('arch-7', 'INBOX');
  await tick();
  assert.deepEqual(calls.map((c) => ({ ...c })), [{ id: '365', account: 6, folder: 'INBOX' }]);
});
