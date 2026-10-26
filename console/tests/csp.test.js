// The console windows run with a Content-Security-Policy that forbids inline
// scripts: no 'unsafe-inline' in script-src, no <script> blocks without src,
// no on*="..." handlers in the pages or in the HTML the scripts generate.
// A text that slips past escaping (a mail subject, a calendar invite) then
// stays text: the browser refuses to run it, and a send from the console,
// which needs no Windows Hello, cannot be triggered by injected code.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const pages = fs.readdirSync(ROOT).filter((f) => f.endsWith('.html'));
const scripts = fs.readdirSync(ROOT).filter((f) => f.endsWith('.js')
  && !['main.js', 'eslint.config.js', 'sign.js', 'afterpack.js', 'sync-version.js'].includes(f)
  && !f.startsWith('preload'));
const HANDLER = /\son[a-z]+\s*=\s*\\?["']/i;

test('every window has a CSP whose script-src forbids inline code', () => {
  assert.ok(pages.length >= 7);
  for (const f of pages) {
    const html = fs.readFileSync(path.join(ROOT, f), 'utf-8');
    const csp = (html.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/) || [])[1];
    assert.ok(csp, `${f}: CSP meta tag`);
    const scriptSrc = (csp.match(/script-src ([^;]+)/) || [])[1] || '';
    assert.ok(scriptSrc, `${f}: script-src`);
    assert.ok(!/'unsafe-inline'|'unsafe-eval'/.test(scriptSrc), `${f}: ${scriptSrc}`);
  }
});

test('no inline <script> blocks and no on*= handlers in the pages', () => {
  for (const f of pages) {
    const html = fs.readFileSync(path.join(ROOT, f), 'utf-8');
    const inline = html.match(/<script(?![^>]*\bsrc=)[^>]*>/g) || [];
    assert.deepEqual(inline, [], `${f}: inline <script>`);
    const tags = html.match(/<[a-z][^>]*>/gi) || [];
    const bad = tags.filter((t) => HANDLER.test(t));
    assert.deepEqual(bad, [], `${f}: inline handlers`);
  }
});

test('the HTML the console scripts generate carries no on*= handlers', () => {
  for (const f of scripts) {
    const src = fs.readFileSync(path.join(ROOT, f), 'utf-8');
    const bad = src.split('\n').filter((l) => !/^\s*\/\//.test(l) && /<[a-z][^>]*\son[a-z]+=/i.test(l));
    assert.deepEqual(bad, [], `${f}: inline handler in generated HTML`);
  }
});
