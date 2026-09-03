// Unit test della parte pura di renderer_calendar.js (window.CalendarView).
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
    function fmtDate(d){ return d ? 'D:' + d : ''; }
    function fmtDateTime(d){ return d ? 'DT:' + d : ''; }
  `, ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_calendar.js'), 'utf-8'), ctx);
  return dom.window;
}

const HOSTILE = '<img src=x onerror="window.__xss=1">"\'&';

test('eventItemHtml: titolo, luogo e id escapati', () => {
  const w = load();
  const html = w.CalendarView.eventItemHtml({ id: 'e"1', subject: HOSTILE, start: { dateTime: '2026-09-03T10:00' }, location: { displayName: HOSTILE } });
  assert.ok(!/<img/.test(html));
  const host = w.document.getElementById('host');
  host.innerHTML = html;
  assert.equal(host.querySelector('.event-item').dataset.id, 'e"1');
  assert.ok(host.querySelector('.event-subject').textContent.includes('<img src=x'));
  assert.ok(host.querySelector('.event-location').textContent.includes('📍 <img'));
  assert.equal(host.querySelectorAll('img').length, 0);
  const noLoc = w.CalendarView.eventItemHtml({ id: 'x', subject: 's' });
  assert.ok(!noLoc.includes('event-location'));
  assert.ok(noLoc.includes('(senza titolo)') === false && noLoc.includes('>s<'));
});

test('notesText: tag via, spazi compressi; attendeesText solo indirizzi validi', () => {
  const w = load();
  assert.equal(w.CalendarView.notesText({ body: { content: '<p>Porta   i <b>documenti</b></p>\n<script>x</script>' } }), 'Porta i documenti x');
  assert.equal(w.CalendarView.notesText({ bodyPreview: '  ciao  ' }), 'ciao');
  assert.equal(w.CalendarView.notesText({}), '');
  assert.equal(w.CalendarView.attendeesText({ attendees: [{ emailAddress: { address: 'a@x.it' } }, {}, { emailAddress: {} }, { emailAddress: { address: 'b@y.it' } }] }), 'a@x.it, b@y.it');
});

test('eventPopupHtml: struttura .modal della console, tutto escapato, bottoni con data-act', () => {
  const w = load();
  const html = w.CalendarView.eventPopupHtml({
    subject: HOSTILE, start: { dateTime: 's' }, end: { dateTime: 'e' },
    location: { displayName: HOSTILE }, body: { content: '<b>note</b>' + HOSTILE },
    attendees: [{ emailAddress: { address: HOSTILE } }],
  });
  assert.ok(!/<img|<b>/.test(html), 'nessun markup dai dati');
  const host = w.document.getElementById('host');
  host.innerHTML = html;
  assert.ok(host.querySelector('.modal .modal-hdr .modal-title'));
  assert.ok(host.querySelector('.modal-body') && host.querySelector('.modal-ftr'));
  assert.equal(host.querySelectorAll('[data-act="close"]').length, 2);
  assert.equal(host.querySelectorAll('[data-act="edit"]').length, 1);
  assert.ok(host.querySelector('.modal-title').textContent.includes('<img src=x'));
  assert.ok(host.querySelector('.modal-body').textContent.includes('🕐 DT:s → DT:e'));
  assert.equal(host.querySelectorAll('img, b').length, 0);
  // senza dati opzionali: niente righe vuote
  const bare = w.CalendarView.eventPopupHtml({ subject: 'x' });
  assert.ok(!bare.includes('📍') && !bare.includes('👥') && !bare.includes('ob-p'));
  assert.ok(bare.includes('(senza titolo)') === false);
});
