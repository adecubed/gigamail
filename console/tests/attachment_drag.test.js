// Unit tests of attachment_drag.js: an attachment of a received mail is
// dragged onto a mail being written and attached to it.
const test = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const Drag = require('../attachment_drag');

const REF = { id: 'msg-1', name: 'floor plan.pdf', accountId: 2, folder: 'INBOX.Leads', type: 'application/pdf' };

// What a drag carries from dragstart to drop, as the browser keeps it.
function transfer() {
  const data = {};
  return {
    data,
    setData: (type, value) => { data[type] = value; },
    getData: (type) => data[type] || '',
    get types() { return Object.keys(data); },
    files: [],
  };
}

function chip() {
  const dom = new JSDOM('<!DOCTYPE html><body><div id="c"></div></body>');
  return { el: dom.window.document.getElementById('c'), w: dom.window };
}

function drag(el, w, dt) {
  const ev = new w.Event('dragstart', { bubbles: true });
  ev.dataTransfer = dt;
  el.dispatchEvent(ev);
}

const answer = (bytes, type) => ({
  ok: true, status: 200,
  headers: { get: (h) => (h === 'content-type' ? type : null) },
  arrayBuffer: async () => Uint8Array.from(bytes).buffer,
});

test('a chip becomes draggable and the drag names the file, not its bytes', () => {
  const { el, w } = chip();
  assert.equal(Drag.makeSource(el, REF), true);
  assert.equal(el.getAttribute('draggable'), 'true');
  const dt = transfer();
  drag(el, w, dt);
  assert.deepEqual(dt.types, [Drag.TYPE]);
  assert.deepEqual(JSON.parse(dt.data[Drag.TYPE]), REF);
  assert.equal(dt.effectAllowed, 'copy');
  assert.deepEqual(Drag.refFrom({ dataTransfer: dt }), REF);
});

test('a file that runs a program is not draggable, nor fetched if named', async () => {
  const { el } = chip();
  assert.equal(Drag.makeSource(el, { ...REF, name: 'invoice.pdf.exe' }), false);
  assert.equal(el.hasAttribute('draggable'), false);
  let asked = 0;
  await assert.rejects(Drag.fetchFile('http://api', { ...REF, name: 'run.ps1' },
    async () => { asked += 1; return answer([1], 'text/plain'); }));
  assert.equal(asked, 0);
});

test('a reference without a message or a name is no reference', () => {
  const { el } = chip();
  assert.equal(Drag.makeSource(el, { name: 'a.pdf' }), false);
  assert.equal(Drag.makeSource(el, { id: 'm' }), false);
  const dt = transfer();
  dt.setData(Drag.TYPE, 'not json');
  assert.equal(Drag.refFrom({ dataTransfer: dt }), null);
  dt.setData(Drag.TYPE, JSON.stringify({ id: 5, name: ['x'] }));
  assert.equal(Drag.refFrom({ dataTransfer: dt }), null);
});

test('the address asked is built here: nothing in the drag can point elsewhere', () => {
  const dt = transfer();
  dt.setData(Drag.TYPE, JSON.stringify({ id: '../../x?y=1', name: 'a/b c.pdf',
    accountId: '3&admin=1', folder: 'A&B', url: 'http://evil.example.com/' }));
  const ref = Drag.refFrom({ dataTransfer: dt });
  assert.equal(ref.url, undefined);
  assert.equal(Drag.urlFor('http://api', ref),
    'http://api/mail/..%2F..%2Fx%3Fy%3D1/attachment/a%2Fb%20c.pdf?account_id=3&folder=A%26B');
  assert.equal(Drag.urlFor('http://api', { id: 'm', name: 'a.pdf', accountId: null, folder: '' }),
    'http://api/mail/m/attachment/a.pdf');
});

test('the file comes back in the shape a mail being written keeps', async () => {
  const urls = [];
  const bytes = Array.from({ length: 70000 }, (_, i) => i % 251);
  const file = await Drag.fetchFile('http://api', REF,
    async (url) => { urls.push(url); return answer(bytes, 'application/pdf; name="x"'); });
  assert.deepEqual(urls, ['http://api/mail/msg-1/attachment/floor%20plan.pdf?account_id=2&folder=INBOX.Leads']);
  assert.equal(file.name, 'floor plan.pdf');
  assert.equal(file.type, 'application/pdf');
  assert.equal(file.size, 70000);
  assert.deepEqual(Array.from(Buffer.from(file.data_b64, 'base64')), bytes);
});

test('a backend that refuses is an error, not an empty attachment', async () => {
  await assert.rejects(Drag.fetchFile('http://api', REF, async () => ({ ok: false, status: 404 })), /HTTP 404/);
});

test('a drop of files from the desktop is left to the window, as before', () => {
  const dt = transfer();
  dt.setData('Files', '');
  let called = 0;
  assert.equal(Drag.takeDrop({ dataTransfer: dt }, 'http://api', () => { called += 1; }), false);
  assert.equal(called, 0);
});

test('a drop of an attachment is taken, and its file handed over', async (t) => {
  const { el, w } = chip();
  Drag.makeSource(el, REF);
  const dt = transfer();
  drag(el, w, dt);
  t.mock.method(globalThis, 'fetch', async () => answer([80, 68, 70], 'application/pdf'));
  const got = await new Promise((resolve, reject) => {
    assert.equal(Drag.takeDrop({ dataTransfer: dt }, 'http://api', resolve, (_n, e) => reject(e)), true);
  });
  assert.deepEqual(got, { name: 'floor plan.pdf', data_b64: 'UERG', type: 'application/pdf', size: 3 });
});

test('a failed fetch reaches the window with the name of the file', async (t) => {
  const dt = transfer();
  dt.setData(Drag.TYPE, JSON.stringify(REF));
  t.mock.method(globalThis, 'fetch', async () => ({ ok: false, status: 500 }));
  const [name, err] = await new Promise((resolve) => {
    Drag.takeDrop({ dataTransfer: dt }, 'http://api', () => {}, (n, e) => resolve([n, e]));
  });
  assert.equal(name, 'floor plan.pdf');
  assert.match(err.message, /HTTP 500/);
});
