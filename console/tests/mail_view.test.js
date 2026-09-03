// Unit test della parte pura di renderer_mail.js (window.MailView):
// tutto cio' che arriva dalla rete — mittente, oggetto, nomi allegato,
// indirizzi, anteprima — deve uscire escapato, e il testo per l'inoltro
// deve venire da un documento inerte.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load() {
  const dom = new JSDOM('<!DOCTYPE html><body><div id="host"></div></body>', { runScripts: 'outside-only' });
  const ctx = dom.getInternalVMContext();
  // Gli helper globali che renderer_mail.js si aspetta da renderer_utils.js
  vm.runInContext(`
    function esc(v){ return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
    function T(k, it){ return it; }
    function fmtDate(d){ return d ? 'DATA' : ''; }
    function cleanFolder(f){ return f || ''; }
  `, ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'mail_render.js'), 'utf-8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_mail.js'), 'utf-8'), ctx);
  return dom.window;
}

const HOSTILE = '<img src=x onerror="window.__xss=1">"\'&';

test('listItemHtml: oggetto, mittente, anteprima e id escapati', () => {
  const w = load();
  const html = w.MailView.listItemHtml({
    id: 'abc"><script>1</script>',
    subject: HOSTILE,
    from: { emailAddress: { name: HOSTILE, address: 'a@b.it' } },
    bodyPreview: HOSTILE,
    folder: 'INBOX',
    isRead: false,
    hasAttachments: true,
  }, 7);
  assert.ok(!/<img|<script/.test(html), 'nessun tag iniettato');
  assert.ok(html.includes('&lt;img src=x onerror='), 'oggetto escapato');
  assert.ok(html.includes('data-id="abc&quot;&gt;&lt;script&gt;'), 'id escapato negli attributi');
  assert.ok(html.includes('class="mail-item unread"'), 'stato non letta');
  assert.ok(html.includes('data-account-id="7"'));
  assert.ok(html.includes('mail-attach-icon'), 'icona allegati');
  // renderizzato: nessun elemento pericoloso
  const host = w.document.getElementById('host');
  host.innerHTML = html;
  assert.equal(host.querySelectorAll('img, script').length, 0);
  assert.equal(host.querySelector('.mail-item').dataset.id, 'abc"><script>1</script>');
});

test('senderLabel: nome, poi indirizzo, poi sender, poi ?', () => {
  const w = load();
  const s = w.MailView.senderLabel;
  assert.equal(s({ from: { emailAddress: { name: 'Anna', address: 'a@b' } } }), 'Anna');
  assert.equal(s({ from: { emailAddress: { address: 'a@b' } } }), 'a@b');
  assert.equal(s({ sender: { emailAddress: { name: 'S' } } }), 'S');
  assert.equal(s({}), '?');
});

test('detailHeaderHtml: header, destinatari e allegati escapati; bottoni giusti', () => {
  const w = load();
  const msg = {
    subject: HOSTILE,
    toRecipients: [{ emailAddress: { address: 'to@x.it' } }, { emailAddress: { address: HOSTILE } }],
    ccRecipients: [{ emailAddress: { address: 'cc@x.it' } }],
    attachments: [{ name: 'piano<script>.pdf', size: 2048 }],
    receivedDateTime: '2026-09-03T10:00:00Z',
  };
  const html = w.MailView.detailHeaderHtml(msg, { sender: 'a@b.it', senderName: HOSTILE, ttsUrl: 'http://127.0.0.1:8002/x"><img src=x>', inSpam: false });
  assert.ok(!/<img|<script/.test(html), 'nessun tag iniettato');
  assert.ok(html.includes('to@x.it, &lt;img'), 'indirizzi escapati');
  assert.ok(html.includes('piano&lt;script&gt;.pdf (2KB)'), 'nome allegato escapato');
  assert.ok(html.includes('id="btnSpam"') && !html.includes('id="btnNotSpam"'), 'fuori dallo spam: bottone SPAM');
  const inSpam = w.MailView.detailHeaderHtml(msg, { sender: 'a', senderName: 'b', ttsUrl: '', inSpam: true });
  assert.ok(inSpam.includes('id="btnNotSpam"') && !inSpam.includes('id="btnSpam"'), 'nello spam: bottone NON E SPAM');
  for (const id of ['btnAscolta', 'btnShowReply', 'btnShowReplyAll', 'btnForward', 'btnRiassumi', 'btnMove', 'btnDelete', 'btnMarkUnread', 'mailAudio', 'mailSummaryBox', 'mailSuggestionBox']) {
    assert.ok(html.includes(`id="${id}"`), `manca #${id}`);
  }
  const host = w.document.getElementById('host');
  host.innerHTML = html;
  assert.equal(host.querySelectorAll('img, script').length, 0);
  assert.equal(host.querySelector('audio').getAttribute('src'), 'http://127.0.0.1:8002/x"><img src=x>');
});

test('detailHeaderHtml senza allegati non stampa il blocco allegati', () => {
  const w = load();
  const html = w.MailView.detailHeaderHtml({ subject: 'x' }, { sender: 'a', senderName: 'b', ttsUrl: '', inSpam: false });
  assert.ok(!html.includes('mail-attachments'));
});

test('htmlToText: documento inerte, niente esecuzione, testo leggibile', () => {
  const w = load();
  w.__xss = false;
  const text = w.MailView.htmlToText(
    '<html><head><style>p{color:red}</style><script>window.__xss=true</script></head>' +
    '<body><img src="x" onerror="window.__xss=true"><p>Buongiorno,</p><p>ecco il <b>listino</b>.</p><br>Saluti<div>Anna</div></body></html>');
  assert.equal(w.__xss, false, 'nessuno script eseguito');
  assert.ok(!text.includes('color:red') && !text.includes('__xss'), 'style e script esclusi dal testo');
  assert.ok(text.includes('Buongiorno,') && text.includes('ecco il listino.') && text.includes('Saluti') && text.includes('Anna'));
  assert.ok(text.indexOf('Buongiorno,') < text.indexOf('ecco il listino.'), 'ordine mantenuto');
  assert.ok(/Buongiorno,\n/.test(text), 'i paragrafi vanno a capo');
  assert.equal(w.document.querySelectorAll('img').length, 0, 'niente inserito nel documento vivo');
});

test('htmlToText: input degeneri', () => {
  const w = load();
  for (const v of ['', null, undefined, '<<<', 'solo testo']) {
    assert.doesNotThrow(() => w.MailView.htmlToText(v), String(v));
  }
  assert.equal(w.MailView.htmlToText('solo testo'), 'solo testo');
});
