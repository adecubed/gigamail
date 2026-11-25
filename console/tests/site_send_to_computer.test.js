// "Send to my computer" on the website (docs/send-to-computer.js): on a
// phone or tablet each row of download buttons becomes one button that
// shares the site's link, or copies it; on a computer nothing changes.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { JSDOM } = require('jsdom');

const MODULE = 'file://' + path.join(__dirname, '..', '..', 'docs', 'send-to-computer.js');
const CONFIG = { eventsEndpoint: 'https://counter.example.com/event', site: 'gigamail', productionHosts: ['gigamail.ai'] };
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)';
const WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)';

function page(ua, lang = 'en', nav = {}) {
  const dom = new JSDOM(`<!doctype html><html lang="${lang}"><body>`
    + '<div class="hero-actions"><div class="dl3"><a class="btn" href="https://github.com/adecubed/gigamail/releases/latest/download/GigaMail-Setup.exe">Windows</a></div>'
    + '<span class="alt"><a href="./install.html#step-get">Intel Mac</a></span><span class="alt">Developer? <a href="#setup-mcp">MCP</a></span></div>'
    + '<div class="dl3"><a class="btn" href="#">macOS</a></div><section id="updates"></section></body></html>',
  { url: 'https://gigamail.ai/' });
  const win = dom.window;
  Object.defineProperty(win.navigator, 'userAgent', { value: ua });
  Object.defineProperty(win.navigator, 'maxTouchPoints', { value: ua === IPHONE ? 5 : 0 });
  for (const [k, v] of Object.entries(nav)) Object.defineProperty(win.navigator, k, { value: v });
  const sent = [];
  win.fetch = (u, opts) => { sent.push(JSON.parse(opts.body)); return Promise.resolve(); };
  return { win, doc: win.document, sent };
}

async function load() {
  global.window = undefined;
  return import(MODULE);
}

test('on a computer the download buttons stay', async () => {
  const { install } = await load();
  const { win, doc } = page(WINDOWS);
  assert.equal(install(doc, win, CONFIG), 0);
  assert.equal(doc.querySelectorAll('.send-computer').length, 0);
  assert.equal(doc.querySelectorAll('.dl3[hidden]').length, 0);
  assert.equal(doc.querySelectorAll('.alt[hidden]').length, 0);
});

test('on a phone every row becomes one Send to my computer button', async () => {
  const { install } = await load();
  const { win, doc } = page(IPHONE, 'it');
  assert.equal(install(doc, win, CONFIG), 2);
  assert.equal(doc.querySelectorAll('.dl3[hidden]').length, 2);
  const boxes = doc.querySelectorAll('.send-computer');
  assert.equal(boxes.length, 2);
  assert.equal(boxes[0].querySelector('button').textContent, 'Mandalo al mio computer');
  assert.equal(boxes[0].querySelector('a.send-updates').getAttribute('href'), '#updates');
  assert.equal(doc.querySelectorAll('.alt[hidden]').length, 2, 'the installer and MCP lines go too');
});

test('sharing sends the link and counts one send_link', async () => {
  const { install, SHARE_URL } = await load();
  const shared = [];
  const { win, doc, sent } = page(IPHONE, 'en', { share: (data) => { shared.push(data); return Promise.resolve(); } });
  install(doc, win, CONFIG);
  doc.querySelector('.send-computer button').click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(shared[0].url, SHARE_URL);
  assert.deepEqual(sent.map(e => [e.type, e.text]), [['send_link', 'shared']]);
});

test('closing the share sheet counts nothing', async () => {
  const { install } = await load();
  const abort = () => Promise.reject(Object.assign(new Error('closed'), { name: 'AbortError' }));
  const { win, doc, sent } = page(IPHONE, 'en', { share: abort });
  install(doc, win, CONFIG);
  doc.querySelector('.send-computer button').click();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(sent.length, 0);
});

test('without a share sheet the link is copied', async () => {
  const { install, SHARE_URL } = await load();
  const copied = [];
  const { win, doc, sent } = page(IPHONE, 'en', { clipboard: { writeText: (t) => { copied.push(t); return Promise.resolve(); } } });
  install(doc, win, CONFIG);
  doc.querySelector('.send-computer button').click();
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(copied, [SHARE_URL]);
  assert.equal(doc.querySelector('.send-note').textContent, 'Link copied. Open it on your computer.');
  assert.deepEqual(sent.map(e => [e.type, e.text]), [['send_link', 'copied']]);
});
