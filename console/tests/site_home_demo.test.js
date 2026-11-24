// The home page's live demo (docs/home-demo.js): one email, the facts the
// agent finds, the draft waiting for the OK, then sent, in a loop; with
// reduced motion it shows the finished draft and does not move.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { JSDOM } = require('jsdom');

const MODULE = 'file://' + path.join(__dirname, '..', '..', 'docs', 'home-demo.js');

function page() {
  const dom = new JSDOM('<!doctype html><html><body><figure class="demo" data-phase="draft">'
    + '<ul class="demo-facts"><li class="on">a</li><li class="on">b</li><li class="on">c</li></ul>'
    + '</figure></body></html>');
  return dom.window;
}

// A window whose timers run only when the test says so.
function clock(win, calm = false) {
  let now = 0;
  let next = 1;
  const timers = new Map();
  return {
    matchMedia: () => ({ matches: calm }),
    setTimeout: (fn, ms) => { const id = next++; timers.set(id, [now + ms, fn]); return id; },
    clearTimeout: (id) => timers.delete(id),
    advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...timers].filter(([, [at]]) => at <= end).sort((a, b) => a[1][0] - b[1][0])[0];
        if (!due) break;
        timers.delete(due[0]);
        now = due[1][0];
        due[1][1]();
      }
      now = end;
    },
    document: win.document,
  };
}

async function load() {
  return import(MODULE);
}

test('one round goes mail, search fact by fact, draft, sent', async () => {
  const { schedule } = await load();
  const { steps, length } = schedule(2, { mail: 100, found: 10, draft: 20, wait: 30, sent: 40 });
  assert.deepEqual(steps, [[0, 'mail', 0], [100, 'search', 0], [110, 'search', 1], [120, 'search', 2],
    [140, 'draft', 2], [170, 'sent', 2]]);
  assert.equal(length, 210);
});

test('the demo plays by itself and starts again', async () => {
  const { startDemo, schedule } = await load();
  const win = page();
  const root = win.document.querySelector('.demo');
  const t = clock(win);
  startDemo(root, t);
  const on = () => root.querySelectorAll('.demo-facts li.on').length;
  assert.equal(root.getAttribute('data-phase'), 'mail');
  assert.equal(on(), 0);
  t.advance(1600 + 550);
  assert.equal(root.getAttribute('data-phase'), 'search');
  assert.equal(on(), 1);
  t.advance(550 * 2 + 700);
  assert.equal(root.getAttribute('data-phase'), 'draft');
  assert.equal(on(), 3);
  t.advance(2600);
  assert.equal(root.getAttribute('data-phase'), 'sent');
  const { length } = schedule(3);
  t.advance(length - (1600 + 550 * 3 + 700 + 2600));
  assert.equal(root.getAttribute('data-phase'), 'mail');
  assert.equal(on(), 0);
});

test('with reduced motion it shows the draft and stays still', async () => {
  const { startDemo } = await load();
  const win = page();
  const root = win.document.querySelector('.demo');
  const t = clock(win, true);
  startDemo(root, t);
  assert.equal(root.getAttribute('data-phase'), 'draft');
  assert.equal(root.querySelectorAll('.demo-facts li.on').length, 3);
  t.advance(60000);
  assert.equal(root.getAttribute('data-phase'), 'draft');
});

test('no demo on the page: nothing happens', async () => {
  const { startDemo } = await load();
  assert.equal(startDemo(null), null);
});
