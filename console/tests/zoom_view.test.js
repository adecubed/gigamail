// Unit test di renderer_zoom.js (window.ZoomView): scheda Zoom della console.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load(api) {
  const dom = new JSDOM('<!DOCTYPE html><body><div id="zoomBody"></div></body>', { runScripts: 'outside-only' });
  dom.window.ademail = api || {};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'renderer_zoom.js'), 'utf-8'), dom.getInternalVMContext());
  return dom.window;
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const HOSTILE = '<img src=x onerror="window.__xss=1">';

test('non collegato: tre campi, il segreto e\' un campo password', () => {
  const w = load();
  const body = w.document.getElementById('zoomBody');
  body.innerHTML = w.ZoomView.bodyHtml({ configured: false });
  assert.ok(body.querySelector('#zoomAccountId'));
  assert.ok(body.querySelector('#zoomClientId'));
  assert.equal(body.querySelector('#zoomClientSecret').type, 'password');
  assert.ok(body.querySelector('#btnZoomConnect'));
});

test('collegato: Account ID escapato, niente campi da compilare', () => {
  const w = load();
  const body = w.document.getElementById('zoomBody');
  body.innerHTML = w.ZoomView.bodyHtml({ configured: true, account_id: HOSTILE });
  assert.equal(body.querySelectorAll('img').length, 0);
  assert.ok(body.textContent.includes('<img src=x'));
  assert.equal(body.querySelector('#zoomClientSecret'), null);
  assert.ok(body.querySelector('#btnZoomRemove'));
});

test('collega: manda i codici ripuliti e poi mostra lo stato collegato', async () => {
  let configurato = false;
  const inviati = [];
  const w = load({
    zoomStatus: async () => ({ configured: configurato, account_id: 'acc1' }),
    zoomSetup: async (dati) => { inviati.push(dati); configurato = true; return { success: true, email: 'me@example.com' }; },
  });
  await w.ZoomView.render();
  w.document.getElementById('zoomAccountId').value = ' acc1 ';
  w.document.getElementById('zoomClientId').value = 'cid';
  w.document.getElementById('zoomClientSecret').value = 'sec ';
  await w.ZoomView.connect();
  await tick();
  assert.deepEqual(JSON.parse(JSON.stringify(inviati)), [{ account_id: 'acc1', client_id: 'cid', client_secret: 'sec' }]);
  assert.ok(w.document.getElementById('btnZoomRemove'), 'scheda ridisegnata come collegata');
  assert.ok(w.document.getElementById('zoomStatus').textContent.includes('me@example.com'));
});

test('credenziali rifiutate: il messaggio di Zoom compare e il segreto resta nel campo', async () => {
  const w = load({
    zoomStatus: async () => ({ configured: false }),
    zoomSetup: async () => { throw new Error('Zoom rifiuta le credenziali: invalid_client'); },
  });
  await w.ZoomView.render();
  w.document.getElementById('zoomAccountId').value = 'acc1';
  w.document.getElementById('zoomClientId').value = 'cid';
  w.document.getElementById('zoomClientSecret').value = 'sec';
  await w.ZoomView.connect();
  assert.ok(w.document.getElementById('zoomStatus').textContent.includes('invalid_client'));
  assert.equal(w.document.getElementById('zoomClientSecret').value, 'sec');
  assert.equal(w.document.getElementById('btnZoomConnect').disabled, false);
});

test('link personale: campo precompilato ed escapato, salvataggio ripulito', async () => {
  const salvati = [];
  const w = load({
    zoomStatus: async () => ({ configured: false, link: 'https://zoom.us/j/1?x="><img>' }),
    zoomLink: async (url) => { salvati.push(url); return { success: true, link: url }; },
  });
  await w.ZoomView.render();
  const campo = w.document.getElementById('zoomLink');
  assert.equal(campo.value, 'https://zoom.us/j/1?x="><img>');
  assert.equal(w.document.querySelectorAll('img').length, 0);
  campo.value = '  https://us02web.zoom.us/j/123  ';
  await w.ZoomView.salvaLink();
  assert.deepEqual(salvati, ['https://us02web.zoom.us/j/123']);
  assert.ok(w.document.getElementById('zoomStatus').textContent.includes('salvato'));
});

test('campi vuoti: nessuna chiamata al backend', async () => {
  let chiamato = false;
  const w = load({
    zoomStatus: async () => ({ configured: false }),
    zoomSetup: async () => { chiamato = true; return {}; },
  });
  await w.ZoomView.render();
  await w.ZoomView.connect();
  assert.equal(chiamato, false);
  assert.ok(w.document.getElementById('zoomStatus').textContent.includes('tre i codici'));
});
