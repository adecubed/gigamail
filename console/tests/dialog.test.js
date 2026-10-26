// The console's confirm and alert (dialog.js): a box in the page, not the
// browser's, resolving on the buttons and the keys.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load() {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', { runScripts: 'outside-only' });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'dialog.js'), 'utf-8'), dom.getInternalVMContext());
  return dom.window;
}

test('confirm resolves true on the primary button and false on cancel', async () => {
  const w = load();
  const p1 = w.GMDialog.confirm('Spostare in spam?');
  const box = w.document.querySelector('.gm-dialog');
  assert.ok(box, 'a box is in the page');
  assert.equal(box.querySelector('.gm-dialog-text').textContent, 'Spostare in spam?');
  const buttons = [...box.querySelectorAll('.gm-dialog-btn')].map((b) => b.textContent);
  assert.deepEqual(buttons, ['Annulla', 'OK']);
  box.querySelector('.gm-dialog-btn.primary').click();
  assert.equal(await p1, true);
  assert.equal(w.document.querySelector('.gm-dialog-overlay'), null, 'the box is gone');

  const p2 = w.GMDialog.confirm('Eliminare?', { danger: true });
  assert.ok(w.document.querySelector('.gm-dialog-btn.danger'));
  w.document.querySelector('.gm-dialog-btn:not(.danger)').click();
  assert.equal(await p2, false);
});

test('Escape cancels, Enter confirms; the text is never HTML', async () => {
  const w = load();
  const p1 = w.GMDialog.confirm('x');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(await p1, false);
  const p2 = w.GMDialog.confirm('<b>bold</b>');
  assert.equal(w.document.querySelector('.gm-dialog-text').innerHTML, '&lt;b&gt;bold&lt;/b&gt;');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.equal(await p2, true);
});

test('alert has one button and replaces window.alert', async () => {
  const w = load();
  w.alert('Errore: qualcosa');
  const box = w.document.querySelector('.gm-dialog');
  assert.ok(box);
  assert.equal(box.querySelectorAll('.gm-dialog-btn').length, 1);
  assert.equal(box.querySelector('.gm-dialog-text').textContent, 'Errore: qualcosa');
  box.querySelector('.gm-dialog-btn').click();
  assert.equal(w.document.querySelector('.gm-dialog-overlay'), null);
});

test('Enter follows the focused button: on a destructive box it starts on Cancel', async () => {
  const w = load();
  const p = w.GMDialog.confirm('Eliminare questa mail?', { danger: true });
  const cancel = w.document.querySelector('.gm-dialog-btn:not(.danger)');
  assert.equal(w.document.activeElement, cancel);
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.equal(await p, false);
  // Tab to the red button, then Enter confirms
  const p2 = w.GMDialog.confirm('Eliminare?', { danger: true });
  w.document.querySelector('.gm-dialog-btn.danger').focus();
  w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  assert.equal(await p2, true);
});
