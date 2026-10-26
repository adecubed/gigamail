// Unit tests of main_i18n.js: the texts the main process shows by itself
// (right-click menu, notifications, file dialogs, window titles).
const test = require('node:test');
const assert = require('node:assert/strict');

const m = require('../main_i18n');

test('every main process text exists in English and Chinese too', () => {
  const it = Object.keys(m.TEXTS.it).sort();
  assert.deepEqual(Object.keys(m.TEXTS.en).sort(), it);
  assert.deepEqual(Object.keys(m.TEXTS.zh).sort(), it);
});

test('the language set by the main window is used, with values filled in', () => {
  m.setLang('en');
  assert.equal(m.mt('menu_copy'), 'Copy');
  assert.equal(m.mt('new_mail_many', { count: 3 }), '3 new mails');
  assert.equal(m.mt('update_ready', { version: '0.6.0' }), 'Update 0.6.0 ready: it installs the next time you quit.');
  m.setLang('it');
  assert.equal(m.mt('menu_copy'), 'Copia');
  m.setLang('zh-CN');
  assert.equal(m.getLang(), 'zh');
  assert.equal(m.mt('menu_copy'), '复制');
});

test('an unknown language is ignored and an unknown key comes back as is', () => {
  m.setLang('en');
  m.setLang('xx');
  assert.equal(m.getLang(), 'en');
  assert.equal(m.mt('no_such_key'), 'no_such_key');
  m.setLang('it');
});
