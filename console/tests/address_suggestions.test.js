// The recipient fields of the reply/forward and new-mail windows suggest
// known addresses: on CC and BCC as on To, replacing only the address
// being typed. The pages' own autocomplete blocks run in JSDOM with a
// fake address endpoint.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const KNOWN = [{ name: 'Gianni Verdi', email: 'gianni@example.com' }];

function block(file, from, to) {
  const src = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
  const start = src.indexOf(from);
  const end = src.indexOf(to, start);
  assert.ok(start >= 0 && end > start, `${from} … ${to} in ${file}`);
  return src.slice(start, end);
}

function page(htmlFile, jsFile, from, to) {
  const html = fs.readFileSync(path.join(__dirname, '..', htmlFile), 'utf8');
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  const w = dom.window;
  const queries = [];
  w.fetch = async (url) => {
    queries.push(String(url));
    return { json: async () => KNOWN };
  };
  w.esc = (s) => String(s);
  w.API = 'http://fixture.invalid';
  w.mailData = { account_id: 7 };
  w.console = console;
  vm.runInContext(block(jsFile, from, to), dom.getInternalVMContext());
  return { w, queries };
}

async function tick() { await new Promise(r => setTimeout(r, 20)); }

test('reply window: CC suggests known addresses and keeps the ones already there', async () => {
  const { w, queries } = page('reply_window.html', 'reply_window_page.js',
    '// ── AUTOCOMPLETE A: e CC:', 'async function applyMailData(');
  const cc = w.document.getElementById('replyCc');
  const box = w.document.getElementById('replyCcAutocomplete');
  assert.ok(box, 'the CC row has its suggestion box');
  cc.value = 'ufficio@example.com, gi';
  cc.dispatchEvent(new w.Event('input'));
  await tick();
  assert.match(queries.at(-1), /addresses\/search\?q=gi&account_id=7/);
  assert.equal(box.style.display, 'block');
  box.querySelector('[data-email]').dispatchEvent(new w.Event('click'));
  assert.equal(cc.value, 'ufficio@example.com, gianni@example.com');
  assert.equal(box.style.display, 'none');
  // To still works the same way
  const to = w.document.getElementById('replyTo');
  to.value = 'gia';
  to.dispatchEvent(new w.Event('input'));
  await tick();
  w.document.getElementById('replyToAutocomplete').querySelector('[data-email]').dispatchEvent(new w.Event('click'));
  assert.equal(to.value, 'gianni@example.com');
});

test('new mail window: To, CC and BCC all suggest', async () => {
  const { w, queries } = page('new_mail_window.html', 'new_mail_window_page.js',
    '// ── AUTOCOMPLETE A:, CC:, BCC:', '// ── GENERA ──');
  for (const [field, boxId] of [['mailTo', 'mailToAutocomplete'], ['mailCc', 'mailCcAutocomplete'], ['mailBcc', 'mailBccAutocomplete']]) {
    const input = w.document.getElementById(field);
    const box = w.document.getElementById(boxId);
    assert.ok(box, `${field} has its suggestion box`);
    input.value = 'primo@example.com; gi';
    input.dispatchEvent(new w.Event('input'));
    await tick();
    assert.match(queries.at(-1), /addresses\?q=gi$/);
    assert.ok(!box.classList.contains('hidden'), `${field}: suggestions shown`);
    box.querySelector('.autocomplete-item').dispatchEvent(new w.MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    assert.equal(input.value, 'primo@example.com; gianni@example.com');
    assert.ok(box.classList.contains('hidden'));
  }
});
