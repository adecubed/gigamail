// gigamail:// links, as the toast buttons, the CLI's forward and a second
// launch hand them to the console.
const test = require('node:test');
const assert = require('node:assert/strict');
const OpenUrl = require('../open_url');

test('approval links carry the action and the request id', () => {
  assert.deepEqual(OpenUrl.parse('gigamail://approve/req_ab12'), { kind: 'approval', action: 'approve', id: 'req_ab12' });
  assert.deepEqual(OpenUrl.parse('GIGAMAIL://Show/req_AB12/'), { kind: 'approval', action: 'show', id: 'req_AB12' });
  assert.equal(OpenUrl.parse('gigamail://delete/req_ab12'), null);
  assert.equal(OpenUrl.parse('gigamail://approve/nope'), null);
  assert.equal(OpenUrl.parse('http://evil/gigamail://approve/req_1'), null);
});

test('reply and mail links', () => {
  assert.deepEqual(OpenUrl.parse('gigamail://reply/0a1b2c3d'), { kind: 'reply', key: '0a1b2c3d' });
  assert.equal(OpenUrl.parse('gigamail://reply/zz'), null);
  assert.deepEqual(OpenUrl.parse('gigamail://mail/6/AAMk%3D?folder=INBOX'), { kind: 'mail', account_id: 6, id: 'AAMk=', folder: 'INBOX' });
});

test('the URL is found in a process argv, as --open-url= or bare', () => {
  assert.equal(OpenUrl.fromArgv(['GigaMail.exe', '--open-url=gigamail://approve/req_1']), 'gigamail://approve/req_1');
  assert.equal(OpenUrl.fromArgv(['GigaMail.exe', 'gigamail://reply/0a1b2c3d']), 'gigamail://reply/0a1b2c3d');
  assert.equal(OpenUrl.fromArgv(['GigaMail.exe', '--inspect']), '');
  assert.equal(OpenUrl.fromArgv(undefined), '');
});
