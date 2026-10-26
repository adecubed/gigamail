// The spam filter cards in Automations (spam_filter_ui.js).
const test = require('node:test');
const assert = require('node:assert/strict');

global.document = { readyState: 'complete', getElementById: () => null, addEventListener: () => {} };
const S = require('../spam_filter_ui');

test('a card names field, text, action, account and hits, escaped', () => {
  const html = S.card({ id: 'sf_1', field: 'subject', contains: '<b>sito</b>', action: 'spam', account_id: 2, hits: 3 },
    [{ id: 2, name: 'Northgate' }]);
  assert.match(html, /Oggetto: “&lt;b&gt;sito&lt;\/b&gt;”/);
  assert.match(html, /Northgate/);
  assert.match(html, /3 bloccate/);
  assert.match(html, /data-sf-delete="sf_1"/);
  const all = S.card({ id: 'sf_2', field: 'from', contains: 'promo', action: 'trash', account_id: null, hits: 0 }, []);
  assert.match(all, /Mittente: “promo”/);
  assert.match(all, /tutti gli account/);
  assert.match(all, /cestino/);
});
