// Unit test della parte pura di renderer_accounts.js (window.AccountsView).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load() {
  const dom = new JSDOM('<!DOCTYPE html><body><select id="accountSelect"></select></body>', { runScripts: 'outside-only' });
  const ctx = dom.getInternalVMContext();
  vm.runInContext(`
    function esc(v){ return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
    function T(k, it){ return it; }
    function byId(id){ return document.getElementById(id); }
  `, ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_accounts.js'), 'utf-8'), ctx);
  return dom.window;
}

const HOSTILE = '<img src=x onerror="window.__xss=1">"\'&';

test('optionsHtml: nome/tipo escapati, attivo selezionato, valore integro', () => {
  const w = load();
  const html = w.AccountsView.optionsHtml([
    { id: 1, name: HOSTILE, type: 'imap', active: false },
    { id: 2, name: 'Lavoro', type: 'microsoft"', active: true },
  ]);
  assert.ok(!/<img/.test(html));
  const sel = w.document.getElementById('accountSelect');
  sel.innerHTML = html;
  assert.equal(sel.options.length, 2);
  assert.equal(sel.value, '2', 'l\'account attivo e\' selezionato');
  assert.ok(sel.options[0].textContent.includes('<img src=x'), 'nome ostile come testo');
  assert.equal(sel.options[1].textContent, 'Lavoro (microsoft")');
  assert.equal(sel.querySelectorAll('img').length, 0);
});

test('optionsHtml: lista vuota → opzione "Nessun account" con value vuoto', () => {
  const w = load();
  for (const v of [[], null, undefined]) {
    const sel = w.document.getElementById('accountSelect');
    sel.innerHTML = w.AccountsView.optionsHtml(v);
    assert.equal(sel.options.length, 1);
    assert.equal(sel.value, '');
    assert.equal(sel.options[0].textContent, 'Nessun account');
  }
});

test('activeOf: marcato attivo, altrimenti il primo, altrimenti null', () => {
  const w = load();
  const a = w.AccountsView.activeOf;
  assert.equal(a([{ id: 1 }, { id: 2, active: true }]).id, 2);
  assert.equal(a([{ id: 1 }, { id: 2 }]).id, 1);
  assert.equal(a([]), null);
  assert.equal(a(null), null);
});
