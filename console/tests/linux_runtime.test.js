const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { runtimeRoot, ensure, isVersionDir } = require('../linux_runtime');

function fakeResources(dir, marker) {
  fs.mkdirSync(path.join(dir, 'python', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'python', 'bin', 'python3.12'), `#!/bin/sh\necho ${marker}\n`, { mode: 0o755 });
  fs.symlinkSync('python3.12', path.join(dir, 'python', 'bin', 'python3'));
  fs.mkdirSync(path.join(dir, 'gigamail', 'src', 'gigamail'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'gigamail', 'src', 'gigamail', '__init__.py'), `__version__ = '${marker}'\n`);
}

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'gm-rt-')); }

test('runtime root: XDG_DATA_HOME, else ~/.local/share', () => {
  assert.equal(runtimeRoot({ XDG_DATA_HOME: '/data' }, '/home/u'), path.join('/data', 'gigamail', 'runtime'));
  assert.equal(runtimeRoot({}, '/home/u'), path.join('/home/u', '.local', 'share', 'gigamail', 'runtime'));
  assert.equal(runtimeRoot({ XDG_DATA_HOME: 'relative' }, '/home/u'), path.join('/home/u', '.local', 'share', 'gigamail', 'runtime'));
});

test('the copy keeps symlinks and the executable bit, current points at it', () => {
  const home = tmp(); const res = tmp(); fakeResources(res, '0.6.7');
  const cur = ensure({ resourcesPath: res, version: '0.6.7', env: {}, home });
  const py = path.join(cur, 'python', 'bin', 'python3');
  assert.equal(fs.readlinkSync(py), 'python3.12');
  assert.ok(fs.statSync(py).mode & 0o100, 'executable');
  assert.equal(fs.readlinkSync(cur), '0.6.7');
  assert.ok(fs.existsSync(path.join(cur, 'gigamail', 'src', 'gigamail', '__init__.py')));
});

test('the path in the configs stays across an update; the old version goes', () => {
  const home = tmp(); const r1 = tmp(); const r2 = tmp();
  fakeResources(r1, '0.6.7'); fakeResources(r2, '0.6.8');
  const a = ensure({ resourcesPath: r1, version: '0.6.7', env: {}, home });
  const b = ensure({ resourcesPath: r2, version: '0.6.8', env: {}, home });
  assert.equal(a, b);
  assert.match(fs.readFileSync(path.join(b, 'gigamail', 'src', 'gigamail', '__init__.py'), 'utf-8'), /0\.6\.8/);
  const root = runtimeRoot({}, home);
  assert.deepEqual(fs.readdirSync(root).sort(), ['0.6.8', 'current']);
});

test('a copy cut short is redone, not trusted', () => {
  const home = tmp(); const res = tmp(); fakeResources(res, '0.6.7');
  const root = runtimeRoot({}, home);
  fs.mkdirSync(path.join(root, '0.6.7', 'python'), { recursive: true });      // no .complete
  fs.mkdirSync(path.join(root, '.tmp-0.6.7-12345'), { recursive: true });      // left by a crash
  const cur = ensure({ resourcesPath: res, version: '0.6.7', env: {}, home });
  assert.ok(fs.existsSync(path.join(cur, 'python', 'bin', 'python3.12')));
  assert.deepEqual(fs.readdirSync(root).sort(), ['0.6.7', 'current']);
});

test('a second start with the same version copies nothing', () => {
  const home = tmp(); const res = tmp(); fakeResources(res, '0.6.7');
  ensure({ resourcesPath: res, version: '0.6.7', env: {}, home });
  fs.rmSync(res, { recursive: true });   // the mount is gone: nothing to copy from
  assert.doesNotThrow(() => ensure({ resourcesPath: res, version: '0.6.7', env: {}, home }));
});

test('only version names are versions', () => {
  assert.equal(isVersionDir('0.6.7'), true);
  assert.equal(isVersionDir('1.0.0-beta.1'), true);
  assert.equal(isVersionDir('current'), false);
  assert.equal(isVersionDir('../x'), false);
  assert.throws(() => ensure({ resourcesPath: '/x', version: '../../etc', env: {}, home: tmp() }));
});
