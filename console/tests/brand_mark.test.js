// brand_mark.test.js — the GigaMail mark sits at the bottom of the icon bar.
//
// The flower + "GigaMail" mark replaced the account-initial avatar at the
// bottom of the sidebar, and the wordmark above the mail list is gone.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index_v2.html'), 'utf-8');

test('the brand mark is the last item of the sidebar', () => {
  const sidebar = html.slice(html.indexOf('class="sidebar"'), html.indexOf('class="views-wrap"'));
  const items = sidebar.match(/<(?:div|img)\b[^>]*class="s-[a-z-]+"/g) || [];
  assert.ok(items.length > 0, 'sidebar not found');
  assert.match(items[items.length - 1], /<img\b[^>]*class="s-brand"/);
  assert.match(sidebar, /<img class="s-brand" src="gigamail-mark\.png" alt="GigaMail"/);
});

test('the mark image ships with the console', () => {
  assert.ok(fs.existsSync(path.join(ROOT, 'gigamail-mark.png')));
});

test('no account avatar and no wordmark above the mail list', () => {
  assert.doesNotMatch(html, /sidebarAvatar|s-avatar/);
  assert.doesNotMatch(html, /gm-wordmark/);
  const js = fs.readFileSync(path.join(ROOT, 'renderer_accounts.js'), 'utf-8');
  assert.doesNotMatch(js, /updateSidebarAvatar|sidebarAvatar/);
});
