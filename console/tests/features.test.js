// Unit test del gate di capability (features.js).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

function load(fetchImpl) {
  const dom = new JSDOM(`<!DOCTYPE html><body>
    <button id="a" data-requires="/accounts">A</button>
    <button id="b" data-requires="/voice/transcribe">B</button>
    <button id="c" data-requires="/accounts /mail/{message_id}/summary">C</button>
    <div id="sub"><button id="d" data-requires="/mail_ask">D</button></div>
  </body>`, { runScripts: 'outside-only' });
  const ctx = dom.getInternalVMContext();
  dom.window.fetch = fetchImpl;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'features.js'), 'utf-8'), ctx);
  return dom.window;
}

const SPEC = { paths: { '/accounts': {}, '/mail_ask': {}, '/health': {} } };
const okFetch = async () => ({ ok: true, json: async () => SPEC });

test('load + apply: nasconde cio\' che il backend non offre, tiene il resto', async () => {
  const w = load(okFetch);
  await w.Features.load('http://x');
  assert.equal(w.Features.known, true);
  assert.equal(w.Features.has('/accounts'), true);
  assert.equal(w.Features.has('/voice/transcribe'), false);
  w.Features.apply();
  const cls = (id) => w.document.getElementById(id).classList.contains('hidden');
  assert.equal(cls('a'), false, '/accounts esiste → visibile');
  assert.equal(cls('b'), true, '/voice/transcribe manca → nascosto');
  assert.equal(cls('c'), true, 'basta un path mancante su due → nascosto');
  assert.equal(w.document.getElementById('c').dataset.featureMissing, '/mail/{message_id}/summary');
  assert.equal(cls('d'), false);
});

test('apply su un sotto-albero tocca solo quello', async () => {
  const w = load(okFetch);
  await w.Features.load('http://x');
  w.Features.apply(w.document.getElementById('sub'));
  assert.equal(w.document.getElementById('b').classList.contains('hidden'), false, 'fuori dal root: intatto');
  assert.equal(w.document.getElementById('d').classList.contains('hidden'), false);
});

test('backend muto → stato sconosciuto → non si nasconde nulla', async () => {
  const w = load(async () => { throw new Error('offline'); });
  await w.Features.load('http://x');
  assert.equal(w.Features.known, false);
  assert.equal(w.Features.has('/qualunque'), true);
  w.Features.apply();
  for (const id of ['a', 'b', 'c', 'd']) assert.equal(w.document.getElementById(id).classList.contains('hidden'), false, id);
});

test('HTTP non ok → sconosciuto; riapplicare dopo un load buono riporta a vista', async () => {
  let ok = false;
  const w = load(async () => (ok ? { ok: true, json: async () => ({ paths: { '/voice/transcribe': {} } }) } : { ok: false, json: async () => ({}) }));
  await w.Features.load('http://x');
  assert.equal(w.Features.known, false);
  ok = true;
  await w.Features.load('http://x');
  w.Features.apply();
  assert.equal(w.document.getElementById('b').classList.contains('hidden'), false, 'ora /voice/transcribe esiste');
  assert.equal(w.document.getElementById('a').classList.contains('hidden'), true, '/accounts non piu\' nello spec');
  assert.equal(w.document.getElementById('a').dataset.featureMissing, '/accounts');
});
