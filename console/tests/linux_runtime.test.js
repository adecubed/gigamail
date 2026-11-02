const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { runtimeRoot, ensure, isVersionDir, versionsInUse } = require('../linux_runtime');

function fakeResources(dir, marker) {
  fs.mkdirSync(path.join(dir, 'python', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'python', 'bin', 'python3.12'), `#!/bin/sh\necho ${marker}\n`, { mode: 0o755 });
  fs.symlinkSync('python3.12', path.join(dir, 'python', 'bin', 'python3'));
  fs.mkdirSync(path.join(dir, 'gigamail', 'src', 'gigamail'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'gigamail', 'src', 'gigamail', '__init__.py'), `__version__ = '${marker}'\n`);
}

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'gm-rt-')); }

// A /proc with the given processes: { pid: { exe, cwd, maps } }.
function fakeProc(procs) {
  const dir = tmp();
  for (const [pid, p] of Object.entries(procs)) {
    fs.mkdirSync(path.join(dir, pid));
    if (p.exe) fs.symlinkSync(p.exe, path.join(dir, pid, 'exe'));
    if (p.cwd) fs.symlinkSync(p.cwd, path.join(dir, pid, 'cwd'));
    fs.writeFileSync(path.join(dir, pid, 'maps'), (p.maps || []).map((m) => `7f00-7f01 r-xp 00000000 08:01 123   ${m}`).join('\n') + '\n');
  }
  fs.mkdirSync(path.join(dir, 'self'));
  return dir;
}
const noProc = () => fakeProc({});

test('runtime root: XDG_DATA_HOME, else ~/.local/share', () => {
  assert.equal(runtimeRoot({ XDG_DATA_HOME: '/data' }, '/home/u'), path.join('/data', 'gigamail', 'runtime'));
  assert.equal(runtimeRoot({}, '/home/u'), path.join('/home/u', '.local', 'share', 'gigamail', 'runtime'));
  assert.equal(runtimeRoot({ XDG_DATA_HOME: 'relative' }, '/home/u'), path.join('/home/u', '.local', 'share', 'gigamail', 'runtime'));
});

test('the copy keeps symlinks and the executable bit, current points at it', () => {
  const home = tmp(); const res = tmp(); fakeResources(res, '0.6.7');
  const r = ensure({ resourcesPath: res, version: '0.6.7', env: {}, home, procDir: noProc() });
  const cur = r.python;
  assert.equal(r.src, path.join(runtimeRoot({}, home), '0.6.7'), 'sources through the versioned folder');
  const py = path.join(cur, 'python', 'bin', 'python3');
  assert.equal(fs.readlinkSync(py), 'python3.12');
  assert.ok(fs.statSync(py).mode & 0o100, 'executable');
  assert.equal(fs.readlinkSync(cur), '0.6.7');
  assert.ok(fs.existsSync(path.join(cur, 'gigamail', 'src', 'gigamail', '__init__.py')));
});

test('the path in the configs stays across an update; the old version goes', () => {
  const home = tmp(); const r1 = tmp(); const r2 = tmp();
  fakeResources(r1, '0.6.7'); fakeResources(r2, '0.6.8');
  const a = ensure({ resourcesPath: r1, version: '0.6.7', env: {}, home, procDir: noProc() }).python;
  const b = ensure({ resourcesPath: r2, version: '0.6.8', env: {}, home, procDir: noProc() }).python;
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
  const cur = ensure({ resourcesPath: res, version: '0.6.7', env: {}, home, procDir: noProc() }).python;
  assert.ok(fs.existsSync(path.join(cur, 'python', 'bin', 'python3.12')));
  assert.deepEqual(fs.readdirSync(root).sort(), ['0.6.7', 'current']);
});

test('a second start with the same version copies nothing', () => {
  const home = tmp(); const res = tmp(); fakeResources(res, '0.6.7');
  ensure({ resourcesPath: res, version: '0.6.7', env: {}, home, procDir: noProc() });
  fs.rmSync(res, { recursive: true });   // the mount is gone: nothing to copy from
  assert.doesNotThrow(() => ensure({ resourcesPath: res, version: '0.6.7', env: {}, home, procDir: noProc() }));
});

test('only version names are versions', () => {
  assert.equal(isVersionDir('0.6.7'), true);
  assert.equal(isVersionDir('1.0.0-beta.1'), true);
  assert.equal(isVersionDir('current'), false);
  assert.equal(isVersionDir('../x'), false);
  assert.throws(() => ensure({ resourcesPath: '/x', version: '../../etc', env: {}, home: tmp() }));
});

test('a version a process still runs from survives the update, and goes once unused', () => {
  const home = tmp(); const r1 = tmp(); const r2 = tmp();
  fakeResources(r1, '0.6.7'); fakeResources(r2, '0.6.8');
  const root = runtimeRoot({}, home);
  ensure({ resourcesPath: r1, version: '0.6.7', env: {}, home, procDir: noProc() });
  // Codex's MCP server, started through current before the update: /proc
  // shows the resolved path of its interpreter.
  const busy = fakeProc({ 4242: { exe: path.join(root, '0.6.7', 'python', 'bin', 'python3.12') } });
  ensure({ resourcesPath: r2, version: '0.6.8', env: {}, home, procDir: busy });
  assert.deepEqual(fs.readdirSync(root).sort(), ['0.6.7', '0.6.8', 'current']);
  assert.equal(fs.readlinkSync(path.join(root, 'current')), '0.6.8');
  ensure({ resourcesPath: r2, version: '0.6.8', env: {}, home, procDir: noProc() });
  assert.deepEqual(fs.readdirSync(root).sort(), ['0.6.8', 'current']);
});

test('in use: by executable, working folder or a mapped library, under the resolved root too', () => {
  // /proc shows resolved paths: build them from the resolved folder (on
  // macOS the temp folder itself sits behind /var -> /private/var).
  const real = fs.realpathSync(tmp()); const viaLink = path.join(tmp(), 'runtime');
  fs.symlinkSync(real, viaLink);
  const proc = fakeProc({
    10: { exe: path.join(real, '0.6.5', 'python', 'bin', 'python3.12') },
    11: { cwd: path.join(real, '0.6.6', 'gigamail', 'src') },
    12: { exe: '/usr/bin/bash', maps: [path.join(real, '0.6.7', 'python', 'lib', 'libpython3.12.so.1.0') + ' (deleted)'] },
    13: { exe: path.join(real, 'current', 'python', 'bin', 'python3') },   // never a version name
    14: { exe: '/usr/bin/node', maps: ['/usr/lib/x86_64-linux-gnu/libc.so.6'] },
  });
  assert.deepEqual([...versionsInUse(viaLink, { procDir: proc })].sort(), ['0.6.5', '0.6.6', '0.6.7']);
  assert.deepEqual([...versionsInUse(viaLink, { procDir: '/nonexistent' })], []);
});
