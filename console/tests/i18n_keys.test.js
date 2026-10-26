// Guard on the console dictionary (i18n.js): English never lags behind
// Italian, and every key the pages use exists, so switching language never
// leaves Italian text, or a bare key name, on screen.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const DIR = path.join(__dirname, '..');

function load(lang) {
  const dom = new JSDOM('<!DOCTYPE html><body></body>', { runScripts: 'outside-only', url: 'http://localhost/' });
  if (lang) dom.window.localStorage.setItem('ade_lang', lang);
  vm.runInContext(fs.readFileSync(path.join(DIR, 'i18n.js'), 'utf-8'), dom.getInternalVMContext());
  return dom.window.i18n;
}

// Keys written literally in the sources: T('key', ...), L('key', ...),
// i18n.t('key' ...) and the data-i18n* attributes. renderer_automations.js
// passes the texts themselves to its own T(it, en, zh) and is left out.
function usedKeys() {
  const skip = new Set(['i18n.js', 'renderer_automations.js', 'main_i18n.js', 'main.js']);
  const files = fs.readdirSync(DIR).filter((f) => /\.(js|html)$/.test(f) && !skip.has(f));
  const used = new Map();
  const call = /\b(?:T|L|i18n\.t)\(\s*'([a-z][a-z0-9_]*)'\s*[,)]/g;
  const attr = /data-i18n(?:-ph|-title|-label|-html)?="([a-z][a-z0-9_]*)"/g;
  for (const f of files) {
    const src = fs.readFileSync(path.join(DIR, f), 'utf-8');
    for (const re of [call, attr]) {
      for (const m of src.matchAll(re)) if (!used.has(m[1])) used.set(m[1], f);
    }
  }
  return used;
}

test('English and Italian have the same keys', () => {
  const i18n = load();
  const it = new Set(i18n.keys('it'));
  const en = new Set(i18n.keys('en'));
  assert.deepEqual([...it].filter((k) => !en.has(k)), [], 'Italian keys missing in English');
  assert.deepEqual([...en].filter((k) => !it.has(k)), [], 'English keys missing in Italian');
});

test('Chinese has no key that Italian lacks (missing ones fall back to English)', () => {
  const i18n = load();
  const it = new Set(i18n.keys('it'));
  // copy out of the page's realm before comparing
  assert.deepEqual([...i18n.keys('zh')].filter((k) => !it.has(k)), []);
});

test('every key used in the console exists in Italian and English', () => {
  const i18n = load();
  const it = new Set(i18n.keys('it'));
  const en = new Set(i18n.keys('en'));
  const missing = [...usedKeys()].filter(([k]) => !it.has(k) || !en.has(k)).map(([k, f]) => `${k} (${f})`);
  assert.deepEqual(missing, []);
});

test('a key in no dictionary returns the text the caller gives, not the key', () => {
  const i18n = load('en');
  assert.equal(i18n.t('no_such_key_anywhere', 'Testo di riserva'), 'Testo di riserva');
  assert.equal(i18n.t('no_such_key_anywhere'), 'no_such_key_anywhere');
});
