// appimage_persistence.mjs — does what the AppImage leaves behind survive it?
//
// An AppImage runs from a mount under /tmp that disappears when the app
// quits. The backend outlives the window, and the agents' MCP configs point
// at the backend's Python: they must not point into that mount. This test
// starts the real AppImage on a fresh HOME and checks, in order:
//   1. the runtime is copied to ~/.local/share/gigamail/runtime/current and
//      the backend runs from there, not from the mount;
//   2. "Connect Codex" (a console click) writes that stable path;
//   3. console.json names the AppImage file, not the binary in the mount;
//   4. after the app quits the mount is gone, the backend still answers, and
//      the command in Codex's config starts the MCP server (initialize);
//   5. a second start of the AppImage finds everything still connected.
//
//   GIGAMAIL_APPIMAGE=dist/GigaMail-0.6.7-x86_64.AppImage xvfb-run -a node tests/appimage_persistence.mjs
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import WebSocket from 'ws';

const APPIMAGE = path.resolve(process.env.GIGAMAIL_APPIMAGE || '');
const DEBUG_PORT = 9566;
const API_PORT = process.env.ADE_CONSOLE_PORT || '8032';
const HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'gigamail-appimage-home-'));
const RT = path.join(HOME, '.local', 'share', 'gigamail', 'runtime');
const RT_PY = path.join(RT, 'current', 'python', 'bin', 'python3');

let failures = 0;
function check(cond, msg) {
  if (cond) console.log('  ✓', msg);
  else { failures += 1; console.log('  ✗', msg); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
setTimeout(() => { console.log('  ✗ watchdog: 6 minutes'); process.exit(1); }, 6 * 60 * 1000).unref();

function getJson(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers, timeout: 5000 }, (res) => {
      let b = '';
      res.on('data', (d) => { b += d; });
      res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(b) }); } catch (e) { reject(e); } });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}
async function waitUntil(fn, ms, every = 500) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { const v = await fn(); if (v) return v; } catch (_) { /* not yet */ }
    await sleep(every);
  }
  return null;
}
class Cdp {
  constructor(url) { this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); }
  open() { return new Promise((res, rej) => { this.ws.on('open', res); this.ws.on('error', rej); this.ws.on('message', (m) => { const x = JSON.parse(m.toString()); if (x.id && this.pending.has(x.id)) { this.pending.get(x.id)(x); this.pending.delete(x.id); } }); }); }
  call(method, params = {}) { const id = ++this.id; this.ws.send(JSON.stringify({ id, method, params })); return new Promise((res) => this.pending.set(id, res)); }
  async evaluate(expression) {
    const r = await this.call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
    return r.result?.result?.value;
  }
  close() { this.ws.close(); }
}

const env = { ...process.env, HOME, ADE_CONSOLE_PORT: API_PORT, GIGAMAIL_NOTIFY_DESKTOP: '0' };
delete env.XDG_DATA_HOME; delete env.XDG_CONFIG_HOME; delete env.ADE_ROOT; delete env.GIGAMAIL_ROOT; delete env.APPDATA;
const token = () => fs.readFileSync(path.join(HOME, '.ade', '.console_token'), 'utf-8').trim();
const health = async () => { const r = await getJson(`http://127.0.0.1:${API_PORT}/health`, { 'X-ADE-Token': token() }); return r.status === 200 ? r.body : null; };
// Mounted AppImages, from /proc/mounts: a folder left behind by a runtime
// that was killed is not a mount.
const mounts = () => fs.readFileSync('/proc/mounts', 'utf-8').split('\n')
  .map((l) => l.split(' ')[1] || '').filter((m) => m.startsWith('/tmp/.mount_')).map((m) => path.basename(m));
const exited = (child) => child.exitCode !== null || child.signalCode !== null;
const cmdline = (pid) => fs.readFileSync(`/proc/${pid}/cmdline`, 'utf-8').split('\0').filter(Boolean);

async function startApp(n) {
  const log = fs.openSync(path.join(HOME, `app-${n}.log`), 'w');
  const debugArg = '--remote-debugging-port=' + DEBUG_PORT;
  const child = spawn(APPIMAGE, [debugArg], { env, stdio: ['ignore', log, log], detached: true });
  const page = await waitUntil(async () => (await getJson(`http://127.0.0.1:${DEBUG_PORT}/json`)).body
    .find((x) => x.type === 'page' && x.url.includes('index_v2')), 90000);
  const h = await waitUntil(health, 90000);
  return { child, page, h };
}
// Quit the way a user does (close the window), so the AppImage runtime
// unmounts by itself. Killing the runtime would leave its mount behind and
// prove nothing. Only if the app does not go: SIGTERM to Electron's main
// process, and as a last resort the whole process group.
async function stopApp(app) {
  try {
    const v = (await getJson(`http://127.0.0.1:${DEBUG_PORT}/json/version`)).body;
    const b = new Cdp(v.webSocketDebuggerUrl); await b.open();
    await Promise.race([b.call('Browser.close'), sleep(5000)]); b.close();
  } catch (_) { /* already closed */ }
  if (await waitUntil(() => exited(app.child), 20000)) return 'closed';
  for (const d of fs.readdirSync('/proc').filter((x) => /^\d+$/.test(x))) {
    try {
      const c = cmdline(d);
      if (c[0] && c[0].startsWith('/tmp/.mount_') && !c.some((a) => a.startsWith('--type='))) process.kill(Number(d), 'SIGTERM');
    } catch (_) { /* not ours */ }
  }
  if (await waitUntil(() => exited(app.child), 20000)) return 'sigterm';
  try { process.kill(-app.child.pid, 'SIGKILL'); } catch (_) { /* gone */ }
  return 'killed';
}
function dump(n) {
  try { console.log(`\n[app-${n}.log, last lines]\n` + fs.readFileSync(path.join(HOME, `app-${n}.log`), 'utf-8').split('\n').slice(-25).join('\n')); } catch (_) { /* none */ }
}

async function main() {
  if (!fs.existsSync(APPIMAGE)) { console.log('  ✗ GIGAMAIL_APPIMAGE not found:', APPIMAGE); process.exit(1); }
  console.log('[AppImage] ' + APPIMAGE + '\n  HOME: ' + HOME);
  const before = new Set(mounts());

  console.log('\n[1. first start]');
  const a = await startApp(1);
  check(!!a.page && !!a.h, 'window open and backend healthy');
  if (!a.page || !a.h) { console.log(fs.readFileSync(path.join(HOME, 'app-1.log'), 'utf-8').split('\n').slice(-30).join('\n')); process.exit(1); }
  const mine = mounts().filter((m) => !before.has(m));
  check(mine.length === 1, `AppImage mounted (${mine.join(', ')})`);
  check(fs.existsSync(path.join(RT, 'current', '.complete')), `runtime copied to ${RT}/${fs.readlinkSync(path.join(RT, 'current'))}`);
  const bcmd = cmdline(a.h.pid);
  check(bcmd[0] === RT_PY, `backend runs from runtime/current (${bcmd[0]})`);
  check(!bcmd.join(' ').includes('/tmp/.mount_'), 'nothing of the backend points into the mount');

  console.log('\n[2. connect Codex from the console]');
  const cdp = new Cdp(a.page.webSocketDebuggerUrl); await cdp.open();
  const res = await cdp.evaluate("fetch(window.GIGAMAIL_API + '/agent/codex/connect', {method: 'POST'}).then(r => r.status)");
  cdp.close();
  check(res === 200, `POST /agent/codex/connect from the window (${res})`);
  const toml = fs.readFileSync(path.join(HOME, '.codex', 'config.toml'), 'utf-8');
  const cmd = JSON.parse((toml.match(/^command\s*=\s*(".*")\s*$/m) || [])[1] || '""');
  check(cmd === RT_PY, `Codex starts ${cmd}`);

  console.log('\n[3. how to reopen the console]');
  const cj = JSON.parse(fs.readFileSync(path.join(HOME, '.ade', 'console.json'), 'utf-8'));
  check(cj.exe === APPIMAGE, `console.json exe = the AppImage file (${cj.exe})`);

  console.log('\n[4. after the app quits]');
  const how = await stopApp(a);
  check(how === 'closed', `the app quits when its window is closed (${how})`);
  const gone = await waitUntil(() => mounts().filter((m) => mine.includes(m)).length === 0, 30000);
  check(!!gone, 'the AppImage mount is gone');
  const h2 = await waitUntil(health, 10000);
  check(!!h2 && h2.pid === a.h.pid, 'the backend still answers, same process');
  const cj2 = JSON.parse(fs.readFileSync(path.join(HOME, '.ade', 'console.json'), 'utf-8'));
  check(cj2.exe === APPIMAGE, 'console.json still names the AppImage after the window closed');
  const args = JSON.parse('[' + ((toml.match(/^args\s*=\s*\[(.*)\]\s*$/m) || [])[1] || '') + ']');
  const root = (toml.match(/GIGAMAIL_ROOT\s*=\s*(".*?")/) || [])[1];
  const mcp = spawnSync(cmd, args, {
    env: { ...env, GIGAMAIL_ROOT: root ? JSON.parse(root) : path.join(HOME, '.ade') },
    input: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'ci', version: '0' } } }) + '\n',
    encoding: 'utf-8', timeout: 60000,
  });
  const first = (mcp.stdout || '').split('\n').find((l) => l.includes('"id":1')) || '';
  let info = null; try { info = JSON.parse(first).result?.serverInfo; } catch (_) { info = null; }
  check(!!info, `Codex's command starts the MCP server with the app closed (${info ? info.name + ' ' + info.version : (mcp.stderr || mcp.error?.message || '').slice(-200)})`);

  console.log('\n[5. second start]');
  const b = await startApp(2);
  check(!!b.page && !!b.h, 'window open and backend healthy again');
  if (!b.page || !b.h) dump(2);
  if (b.h) check(cmdline(b.h.pid)[0] === RT_PY, 'backend again from runtime/current');
  const st = await getJson(`http://127.0.0.1:${API_PORT}/agent/codex`, { 'X-ADE-Token': token() });
  check(st.status === 200 && st.body.connected === true, 'Codex still connected to this installation');
  await stopApp(b);
  const last = await waitUntil(health, 5000);
  if (last?.pid) { try { process.kill(last.pid); } catch (_) { /* gone */ } }
  try { fs.rmSync(HOME, { recursive: true, force: true }); } catch (_) { /* in use */ }

  if (failures) dump(1);
  console.log(failures ? `\n${failures} checks failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.log('  ✗ fatal:', e.message); process.exit(1); });
