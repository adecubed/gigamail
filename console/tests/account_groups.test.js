// Unit tests for renderer_groups.js (window.AccountGroups and the tile
// bindings): several accounts shown as one, and split again.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load() {
  const dom = new JSDOM('<!DOCTYPE html><body><select id="accountSelect"><option value="1">a</option><option value="2">b</option></select><div id="grid"></div></body>', { runScripts: 'outside-only' });
  const ctx = dom.getInternalVMContext();
  vm.runInContext(`
    function esc(v){ return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
    function T(k, it){ return it; }
    function byId(id){ return document.getElementById(id); }
    function fmtDate(d){ return d ? 'DATE' : ''; }
    function cleanFolder(f){ return f || ''; }
    var calls = [];
    var activeAccountId = 1, activeGroup = null;
    var currentFolder = 'inbox', currentFolderLabel = 'inbox';
    var customFolderCountsRequestId = 0, customFolderNewCounts = new Map(), mailFolderCache = [];
    var api = {
      switchAccount: (id) => { calls.push(['switch', id]); return Promise.resolve({}); },
      mergeAccounts: (s, t) => { calls.push(['merge', s, t]); return Promise.resolve({ id: 1, account_ids: [t, s] }); },
      splitAccountGroup: (id) => { calls.push(['split', id]); return Promise.resolve({ success: true }); },
    };
    function loadMailFolders(){ calls.push(['folders', activeAccountId]); return Promise.resolve([]); }
    function refreshCurrentFolder(){ calls.push(['refresh']); return Promise.resolve([]); }
    function setFolderTitle(){ calls.push(['title']); }
    function showToast(){}
    function renderDashboard(){ calls.push(['dashboard']); }
    window._switchAccount = (id) => { calls.push(['single', id]); };
  `, ctx);
  for (const f of ['mail_render.js', 'renderer_mail.js', 'renderer_groups.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', f), 'utf-8'), ctx);
  }
  return { w: dom.window, run: (code) => vm.runInContext(code, ctx) };
}

const ACCOUNTS = [
  { id: 1, name: 'work', email: 'work@example.com' },
  { id: 2, name: 'shop', email: 'shop@example.com' },
  { id: 3, name: 'home', email: 'home@example.com' },
];
// Values built inside the jsdom context have another realm's prototypes:
// compare what they contain, not their identity.
function same(actual, expected, message) {
  assert.equal(JSON.stringify(actual), JSON.stringify(expected), message);
}

const HOSTILE = '<img src=x onerror="window.__xss=1">"\'&';

test('tiles: a group takes the place of its first account', () => {
  const { w } = load();
  const tiles = w.AccountGroups.tiles(ACCOUNTS, [{ id: 7, account_ids: [3, 1] }]);
  assert.equal(tiles.length, 2);
  assert.equal(tiles[0].group.id, 7);
  same(tiles[0].accounts.map(a => a.id), [3, 1]);
  assert.equal(tiles[1].group, null);
  same(tiles[1].accounts.map(a => a.id), [2]);
});

test('tiles: no groups, or a group of unknown accounts, leaves single tiles', () => {
  const { w } = load();
  for (const groups of [[], null, [{ id: 1, account_ids: [1, 99] }]]) {
    const tiles = w.AccountGroups.tiles(ACCOUNTS, groups);
    assert.equal(tiles.length, 3);
    assert.ok(tiles.every(t => t.group === null));
  }
});

test('mergeLists: newest first, each mail remembers its account', () => {
  const { w } = load();
  const merged = w.AccountGroups.mergeLists([
    { account: ACCOUNTS[0], mails: [
      { id: '5', receivedDateTime: '2026-03-02T10:00:00Z' },
      { id: '4', receivedDateTime: '2026-03-01T08:00:00Z' }] },
    { account: ACCOUNTS[1], mails: [
      { id: '5', receivedDateTime: 'Mon, 2 Mar 2026 09:00:00 +0000 (UTC)' }] },
  ]);
  same(merged.map(m => [m.id, m._accountId]), [['5', 1], ['5', 2], ['4', 1]]);
  assert.equal(merged[1]._accountLabel, 'shop');
});

test('mergeLists: stops where the busiest account\'s page ends', () => {
  const { w } = load();
  const merged = w.AccountGroups.mergeLists([
    // a full page of 2: older mail of this account was not fetched
    { account: ACCOUNTS[0], mails: [
      { id: 'a2', receivedDateTime: '2026-03-10T10:00:00Z' },
      { id: 'a1', receivedDateTime: '2026-03-09T10:00:00Z' }] },
    { account: ACCOUNTS[1], mails: [
      { id: 'b2', receivedDateTime: '2026-03-09T12:00:00Z' },
      { id: 'b1', receivedDateTime: '2026-02-01T10:00:00Z' }] },
  ], 2);
  // b1 is older than the oldest mail fetched for the first account, and so
  // is everything else of the second: showing it would leave a hole.
  same(merged.map(m => m.id), ['a2', 'b2', 'a1']);
});

test('sum: counters added up, the most recent last mail wins', () => {
  const { w } = load();
  const s = w.AccountGroups.sum([
    { unread: 4, sentToday: 1, lastMail: 'old', lastTs: 10 },
    { unread: 8, sentToday: 0, lastMail: 'new', lastTs: 20 },
    undefined,
  ]);
  assert.equal(s.unread, 12);
  assert.equal(s.sentToday, 1);
  assert.equal(s.lastMail, 'new');
});

test('tileHtml: account data escaped, group tile offers Split', () => {
  const { w } = load();
  const grid = w.document.getElementById('grid');
  const hostile = { id: 1, name: HOSTILE, email: HOSTILE };
  grid.innerHTML =
    w.AccountGroups.tileHtml({ group: null, accounts: [hostile] },
      { unread: 2, sentToday: 0, lastMail: HOSTILE }, '#185FA5', true) +
    w.AccountGroups.tileHtml({ group: { id: 7, account_ids: [2, 3] }, accounts: [ACCOUNTS[1], ACCOUNTS[2]] },
      { unread: 0, sentToday: 0, lastMail: '' }, '#A32D2D', true);
  assert.equal(grid.querySelectorAll('img').length, 0);
  assert.equal(w.__xss, undefined);
  const tiles = grid.querySelectorAll('[data-tile]');
  assert.equal(tiles.length, 2);
  assert.equal(tiles[0].getAttribute('draggable'), 'true');
  assert.equal(tiles[0].querySelector('[data-split-group]'), null);
  assert.ok(tiles[1].textContent.includes('shop + home'));
  assert.ok(tiles[1].textContent.includes('shop@example.com, home@example.com'));
  assert.equal(tiles[1].querySelector('[data-split-group]').dataset.splitGroup, '7');
});

test('tileHtml: with a single account, or an old backend, nothing to drag', () => {
  const { w } = load();
  const html = w.AccountGroups.tileHtml({ group: null, accounts: [ACCOUNTS[0]] }, null, '#000', false);
  assert.ok(!html.includes('draggable'));
});

function tilesOnGrid(w) {
  const tiles = w.AccountGroups.tiles(ACCOUNTS, [{ id: 7, account_ids: [2, 3] }]);
  const grid = w.document.getElementById('grid');
  grid.innerHTML = tiles.map(t => w.AccountGroups.tileHtml(t, null, '#000', true)).join('');
  w.bindDashboardTiles(grid, tiles);
  return grid.querySelectorAll('[data-tile]');
}

test('click: a single tile opens the account, a group tile the merged view', () => {
  const { w, run } = load();
  run('function openFolder(){ calls.push(["openFolder"]); return Promise.resolve(); } function renderCustomFolders(){} function loadEvents(){ return Promise.resolve(); }');
  const [single, group] = tilesOnGrid(w);
  single.click();
  same(run('calls[0]'), ['single', 1]);
  group.click();
  assert.equal(run('activeGroup.id'), 7);
  same(run('activeGroup.accounts.map(a => a.id)'), [2, 3]);
  assert.equal(run('activeAccountId'), 2, 'the first account of the group becomes the active one');
});

test('drop: dragging one tile onto another merges the two accounts', async () => {
  const { w, run } = load();
  const [single, group] = tilesOnGrid(w);
  const data = { 'text/x-gigamail-account': '1' };
  const ev = new w.Event('drop', { bubbles: true, cancelable: true });
  ev.dataTransfer = { getData: (k) => data[k], types: Object.keys(data) };
  group.dispatchEvent(ev);
  await new Promise(r => setTimeout(r, 0));
  same(run('calls.find(c => c[0] === "merge")'), ['merge', 1, 2]);
  assert.ok(run('calls.some(c => c[0] === "dashboard")'), 'the dashboard is redrawn');
  // dropping a tile on itself does nothing
  run('calls.length = 0');
  const self = new w.Event('drop', { bubbles: true, cancelable: true });
  self.dataTransfer = { getData: () => '1', types: ['text/x-gigamail-account'] };
  single.dispatchEvent(self);
  await new Promise(r => setTimeout(r, 0));
  assert.equal(run('calls.length'), 0);
});

test('Split: removes the group and leaves the merged view', async () => {
  const { w, run } = load();
  const [, group] = tilesOnGrid(w);
  run('activeGroup = { id: 7, account_ids: [2, 3], accounts: [] }');
  group.querySelector('[data-split-group]').click();
  await new Promise(r => setTimeout(r, 0));
  same(run('calls.find(c => c[0] === "split")'), ['split', 7]);
  assert.equal(run('activeGroup'), null);
  assert.ok(!run('calls.some(c => c[0] === "single")'), 'Split does not open the tile');
});

test('useAccountOfItem: in a merged view the mail\'s account becomes active', () => {
  const { w, run } = load();
  w.useAccountOfItem('2');
  assert.equal(run('activeAccountId'), 1, 'outside a merged view nothing changes');
  run('activeGroup = { id: 7, account_ids: [1, 2], accounts: [] }');
  w.useAccountOfItem('2');
  assert.equal(run('activeAccountId'), 2);
  assert.equal(w.document.getElementById('accountSelect').value, '2');
  same(run('calls.map(c => c[0])'), ['switch', 'folders']);
});

test('listItemHtml: a merged list says which account each mail belongs to', () => {
  const { w } = load();
  const m = { id: '9', subject: 's', from: { emailAddress: { name: 'Anna' } } };
  const grid = w.document.getElementById('grid');
  grid.innerHTML = w.MailView.listItemHtml(m, 2, HOSTILE);
  assert.equal(grid.querySelectorAll('img').length, 0);
  assert.equal(grid.querySelector('.mail-item').dataset.accountId, '2');
  assert.ok(grid.querySelector('.mail-sender').textContent.includes('Anna · <img'));
  grid.innerHTML = w.MailView.listItemHtml(m, 2);
  assert.equal(grid.querySelector('.mail-sender').textContent, 'Anna');
});
