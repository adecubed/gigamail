// A file dropped on the AI instruction: only a file whose text came back
// becomes context, and a failure says why instead of showing a badge.
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../file_context.js');

const FILE = new Blob(['A12;395000'], { type: 'text/csv' });
FILE.name = 'price_list.csv';
const reply = (status, body) => async (url, opts) => {
  reply.last = { url, opts };
  return { ok: status < 400, status, json: async () => body };
};

test('the text of the file comes back, from the endpoint the backend has', async () => {
  const fetchFn = reply(200, { name: 'price_list.csv', text: 'A12;395000', chars: 10, type: 'text' });
  const ctx = await C.extract('http://127.0.0.1:1', FILE, fetchFn);
  assert.equal(reply.last.url, 'http://127.0.0.1:1/files/extract_text');
  assert.equal(reply.last.opts.method, 'POST');
  assert.deepEqual(ctx, { ok: true, name: 'price_list.csv', text: 'A12;395000', chars: 10, type: 'text' });
  assert.equal(C.badgeText(ctx, (_k, fb) => fb), 'price_list.csv · 10 caratteri');
});

test('a refusal or an empty text is not context, and says why', async () => {
  let ctx = await C.extract('x', FILE, reply(422, { detail: 'photo.png: unsupported format' }));
  assert.deepEqual(ctx, { ok: false, error: 'photo.png: unsupported format' });
  ctx = await C.extract('x', FILE, reply(404, { detail: 'Not Found' }));
  assert.equal(ctx.ok, false);
  ctx = await C.extract('x', FILE, reply(200, { text: '   ' }));
  assert.equal(ctx.ok, false);
  ctx = await C.extract('x', FILE, async () => { throw new Error('offline'); });
  assert.deepEqual(ctx, { ok: false, error: 'offline' });
});

test('a validation error from FastAPI reads as its message', () => {
  assert.equal(C.errorText({ detail: [{ msg: 'field required' }] }, 422), 'field required');
  assert.equal(C.errorText({}, 500), 'HTTP 500');
});
