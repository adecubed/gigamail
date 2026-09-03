// Unit test della parte pura di renderer_compose.js (window.ComposeView).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load() {
  const dom = new JSDOM('<!DOCTYPE html><body><div id="host"></div></body>', { runScripts: 'outside-only' });
  const ctx = dom.getInternalVMContext();
  vm.runInContext(`
    function esc(v){ return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
    function T(k, it){ return it; }
  `, ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_compose.js'), 'utf-8'), ctx);
  return dom.window;
}

const HOSTILE = '<img src=x onerror="window.__xss=1">"\'&';

function renderInto(w, html) {
  const host = w.document.getElementById('host');
  host.innerHTML = html;
  return host;
}

test('attachmentChipsHtml: nome escapato, bottone con la nostra espressione', () => {
  const w = load();
  const html = w.ComposeView.attachmentChipsHtml(
    [{ name: HOSTILE + '.pdf', size: 3000 }, { name: 'ok.docx', size: 0 }],
    (i) => `removeX(${i})`, 'cursor:default');
  assert.ok(!/<img/.test(html), 'nessun tag iniettato');
  assert.ok(html.includes('&lt;img src=x onerror='), 'nome escapato');
  assert.ok(html.includes('onclick="removeX(0)"') && html.includes('onclick="removeX(1)"'));
  assert.ok(html.includes('(3KB)') && html.includes('(0KB)'));
  const host = renderInto(w, html);
  assert.equal(host.querySelectorAll('img').length, 0);
  assert.equal(host.querySelectorAll('.attachment-chip').length, 2);
  assert.equal(host.querySelector('.attachment-chip').getAttribute('style'), 'cursor:default');
  assert.equal(w.ComposeView.attachmentChipsHtml([], () => ''), '');
});

test('autocompleteItemsHtml: nome e email escapati, data-email integro', () => {
  const w = load();
  const html = w.ComposeView.autocompleteItemsHtml([
    { name: HOSTILE, email: 'a@b.it' },
    { email: 'x"y@evil.it' },
  ]);
  assert.ok(!/<img/.test(html));
  const host = renderInto(w, html);
  const items = host.querySelectorAll('.autocomplete-item');
  assert.equal(items.length, 2);
  assert.equal(items[0].dataset.email, 'a@b.it');
  assert.ok(items[0].textContent.includes('<img src=x onerror='), 'il nome ostile e\' testo, non markup');
  assert.equal(items[1].dataset.email, 'x"y@evil.it', 'virgolette nell\'attributo escapate e ripristinate');
  assert.equal(host.querySelectorAll('img').length, 0);
});

test('suggestedAttachmentsHtml: path/nome negli attributi, score solo numerico', () => {
  const w = load();
  const html = w.ComposeView.suggestedAttachmentsHtml([
    { path: 'C:\\docs\\' + HOSTILE, name: HOSTILE, score: 0.876 },
    { path: 'C:\\docs\\ok.pdf', name: 'ok.pdf', score: '<b>x</b>' },
  ]);
  assert.ok(!/<img|<b>/.test(html));
  const host = renderInto(w, html);
  const checks = host.querySelectorAll('.suggested-attach-check');
  assert.equal(checks.length, 2);
  assert.equal(checks[0].dataset.name, HOSTILE);
  assert.equal(checks[0].dataset.path, 'C:\\docs\\' + HOSTILE);
  assert.ok(host.textContent.includes('score: 0.9'));
  assert.ok(!host.textContent.includes('<b>'), 'score non numerico ignorato');
  assert.equal(host.querySelectorAll('img, b').length, 0);
});

test('splitAddresses / addressToken / mergeAddressSuggestion', () => {
  const w = load();
  const { splitAddresses, addressToken, mergeAddressSuggestion } = w.ComposeView;
  assert.deepEqual(Array.from(splitAddresses(' a@x.it; b@y.it ,c@z.it;; ')), ['a@x.it', 'b@y.it', 'c@z.it']);
  assert.deepEqual(Array.from(splitAddresses('')), []);
  assert.deepEqual(Array.from(splitAddresses(null)), []);
  assert.equal(addressToken('a@x.it; bru'), 'bru');
  assert.equal(addressToken('bru'), 'bru');
  assert.equal(addressToken(''), '');
  assert.equal(addressToken(undefined), '');
  assert.equal(mergeAddressSuggestion('a@x.it; bru', 'bruno@x.it'), 'a@x.it; bruno@x.it');
  assert.equal(mergeAddressSuggestion('bru', 'bruno@x.it'), 'bruno@x.it');
  assert.equal(mergeAddressSuggestion('', 'bruno@x.it'), 'bruno@x.it');
  assert.equal(mergeAddressSuggestion('a@x.it,', 'bruno@x.it'), 'a@x.it; bruno@x.it');
});
