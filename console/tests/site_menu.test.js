// The top bar's Menu button on the website (docs/menu.js): on narrow
// screens it opens the section links under the bar, and closes them on a
// link, on Escape or on a click elsewhere.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { JSDOM } = require('jsdom');

const MODULE = 'file://' + path.join(__dirname, '..', '..', 'docs', 'menu.js');

function page(lang = 'en') {
  const dom = new JSDOM(`<!doctype html><html lang="${lang}"><body>`
    + '<header class="topbar"><div class="wrap"><a class="brand" href="/">GigaMail</a>'
    + '<nav class="topnav"><a href="./features.html">Features</a><a href="#faq">FAQ</a></nav>'
    + '<a class="btn btn-ghost" href="https://github.com/">GitHub</a><a class="btn btn-primary" href="#install">Download</a></div></header>'
    + '<main><p id="out">text</p></main></body></html>');
  return dom.window.document;
}

async function load() {
  return import(MODULE);
}

test('labels follow the page language', async () => {
  const { labelFor } = await load();
  assert.deepEqual(['en', 'it', 'zh-Hans', 'fr', ''].map(labelFor), ['Menu', 'Menu', '菜单', 'Menu', 'Menu']);
});

test('the button sits just before Download and opens and closes the links', async () => {
  const { addMenu } = await load();
  const doc = page('zh-Hans');
  const btn = addMenu(doc);
  const bar = doc.querySelector('.topbar');
  assert.equal(doc.querySelector('.btn-primary').previousElementSibling, btn);
  assert.equal(btn.textContent, '菜单');
  assert.equal(btn.getAttribute('aria-controls'), doc.querySelector('.topnav').id);
  btn.click();
  assert.ok(bar.classList.contains('menu-open'));
  assert.equal(btn.getAttribute('aria-expanded'), 'true');
  doc.querySelector('.topnav a').click();
  assert.ok(!bar.classList.contains('menu-open'));
  btn.click();
  doc.dispatchEvent(new doc.defaultView.KeyboardEvent('keydown', { key: 'Escape' }));
  assert.ok(!bar.classList.contains('menu-open'));
  btn.click();
  doc.getElementById('out').click();
  assert.equal(btn.getAttribute('aria-expanded'), 'false');
});

test('added once, and not on a page without section links', async () => {
  const { addMenu } = await load();
  const doc = page();
  assert.ok(addMenu(doc));
  assert.equal(addMenu(doc), null);
  assert.equal(doc.querySelectorAll('.menu-btn').length, 1);
  const bare = new JSDOM('<!doctype html><html><body><header class="topbar"></header></body></html>').window.document;
  assert.equal(addMenu(bare), null);
});
