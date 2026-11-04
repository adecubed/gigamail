// The website's counter (docs/business/analytics.js): download clicks send
// one 'download' event with the installer's kind, and nothing else.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { JSDOM } = require('jsdom');

const MODULE = 'file://' + path.join(__dirname, '..', '..', 'docs', 'business', 'analytics.js');
const CONFIG = { eventsEndpoint: 'https://counter.example.com/event', site: 'gigamail', cloudflareToken: '', productionHosts: ['gigamail.ai'] };

function page(url = 'https://gigamail.ai/') {
  const dom = new JSDOM('<!doctype html><body></body>', { url });
  const sent = [];
  dom.window.fetch = (u, opts) => { sent.push({ url: u, body: JSON.parse(opts.body) }); return Promise.resolve(); };
  // jsdom cannot navigate: stop the link after the counter has seen it
  dom.window.document.addEventListener('click', (e) => e.preventDefault());
  return { dom, sent };
}

async function load() {
  // the module counts a visit on import: give it a page to do that on
  const { dom } = page('http://localhost/');
  global.window = dom.window; global.document = dom.window.document;
  return import(MODULE);
}

test('download links are named by installer, everything else is ignored', async () => {
  const { downloadKind } = await load();
  const base = 'https://github.com/adecubed/gigamail/releases/latest';
  assert.equal(downloadKind(base + '/download/GigaMail-Setup.exe'), 'win');
  assert.equal(downloadKind(base + '/download/GigaMail-arm64.dmg'), 'mac-arm');
  assert.equal(downloadKind(base + '/download/GigaMail-x64.dmg'), 'mac-intel');
  assert.equal(downloadKind(base + '/download/GigaMail-amd64.deb'), 'linux-deb');
  assert.equal(downloadKind(base + '/download/GigaMail-x86_64.AppImage'), 'linux-appimage');
  assert.equal(downloadKind(base), 'release-page');
  assert.equal(downloadKind('https://github.com/adecubed/gigamail'), '');
  assert.equal(downloadKind('https://example.com/GigaMail-Setup.exe'), '');
});

test('a click on an installer sends one download event, a click elsewhere nothing', async () => {
  const { trackDownloads } = await load();
  const { dom, sent } = page();
  const doc = dom.window.document;
  doc.body.innerHTML = '<a id="d" href="https://github.com/adecubed/gigamail/releases/latest/download/GigaMail-amd64.deb"><span>Linux</span></a>'
    + '<a id="o" href="https://github.com/adecubed/gigamail">repo</a>';
  trackDownloads(CONFIG, dom.window, doc);
  doc.querySelector('#d span').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  doc.querySelector('#o').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].body, { type: 'download', site: 'gigamail', text: 'linux-deb' });
});

test('no event with Do Not Track, or off the production site', async () => {
  const { trackDownloads } = await load();
  for (const [url, dnt] of [['https://gigamail.ai/', '1'], ['http://localhost/', '0']]) {
    const { dom, sent } = page(url);
    Object.defineProperty(dom.window.navigator, 'doNotTrack', { value: dnt });
    dom.window.document.body.innerHTML = '<a id="d" href="https://github.com/adecubed/gigamail/releases/latest/download/GigaMail-Setup.exe">Win</a>';
    trackDownloads(CONFIG, dom.window, dom.window.document);
    dom.window.document.querySelector('#d').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
    assert.equal(sent.length, 0, url);
  }
});
