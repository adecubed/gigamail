// The download board on the website (docs/download-count.js): it appears
// under the top Download button once the total is known, adds one on a
// click on an installer, follows the backend's new totals and never goes
// backwards.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { JSDOM } = require('jsdom');

const MODULE = 'file://' + path.join(__dirname, '..', '..', 'docs', 'download-count.js');
const CONFIG = { eventsEndpoint: 'https://counter.example.com/event' };
const DL = 'https://github.com/adecubed/gigamail/releases/latest/download/GigaMail-Setup.exe';

function page(lang = 'en') {
  const dom = new JSDOM(`<!doctype html><html lang="${lang}"><body><header class="topbar">`
    + '<a class="btn btn-primary" href="#install">Download</a></header>'
    + `<a id="dl" href="${DL}">Windows</a><a id="repo" href="https://github.com/adecubed/gigamail">repo</a></body></html>`,
  { url: 'https://gigamail.ai/' });
  const win = dom.window;
  win.document.addEventListener('click', (e) => e.preventDefault());   // jsdom cannot navigate
  win.matchMedia = () => ({ matches: true });                          // no animation: digits land at once
  const intervals = [];
  win.setInterval = (fn) => { intervals.push(fn); return intervals.length; };
  win.clearInterval = () => {};
  return { win, doc: win.document, intervals };
}

function totals(...values) {
  let i = 0;
  return () => Promise.resolve({ ok: true, json: () => Promise.resolve({ total: values[Math.min(i++, values.length - 1)] }) });
}

const shown = (doc) => [...doc.querySelectorAll('.dl-board .tile')].map(t => t.textContent).join('');

test('the board appears under the Download button with the total', async () => {
  global.window = undefined;
  const { showDownloadBoard } = await import(MODULE);
  const { win, doc } = page('it');
  await showDownloadBoard(doc, win, totals(13632), CONFIG);
  assert.equal(shown(doc), '13632');
  assert.equal(doc.querySelector('.dl-board').getAttribute('aria-label'), '13632 download');
  assert.ok(doc.querySelector('.dl-board-wrap > .btn-primary'));
});

test('a click on an installer adds one, other links nothing', async () => {
  const { showDownloadBoard } = await import(MODULE);
  const { win, doc } = page();
  await showDownloadBoard(doc, win, totals(13632), CONFIG);
  doc.querySelector('#dl').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  doc.querySelector('#repo').dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
  assert.equal(shown(doc), '13633');
});

test('every refresh flips to a higher total and never back', async () => {
  const { showDownloadBoard, REFRESH_MS } = await import(MODULE);
  assert.equal(REFRESH_MS, 60000);
  const { win, doc, intervals } = page();
  await showDownloadBoard(doc, win, totals(13632, 13640, 13635, 100000), CONFIG);
  const refresh = intervals[intervals.length - 1];
  const tick = async () => { refresh(); await new Promise(r => setTimeout(r, 0)); };
  await tick(); assert.equal(shown(doc), '13640');
  await tick(); assert.equal(shown(doc), '13640');
  await tick(); assert.equal(shown(doc), '100000');
});

test('nothing appears while the total is unknown', async () => {
  const { showDownloadBoard } = await import(MODULE);
  const { win, doc } = page();
  await showDownloadBoard(doc, win, totals(null), CONFIG);
  assert.equal(doc.querySelector('.dl-board'), null);
  assert.ok(doc.querySelector('header > .btn-primary'));
});
