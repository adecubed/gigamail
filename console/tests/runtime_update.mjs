// runtime_update.mjs — an update of the AppImage must not pull the runtime
// out from under processes still using it.
//
// Inside an AppImage the backend and the MCP servers started by the agents
// (Codex keeps one open for the whole session) run the Python copied to
// ~/.local/share/gigamail/runtime/<version>. When a new version starts, its
// copy becomes `current`. On Linux deleting a folder succeeds while
// processes still use it: an MCP server of the old version then failed on
// its next import (ModuleNotFoundError). This test, on the real runtime of
// the package:
//   1. installs version A and starts from it, the way the app and Codex do,
//      an MCP server (stdio, kept open) and a backend-like process (the
//      PYTHONPATH main.js gives the backend, an import left for later);
//   2. switches to version B while both are alive;
//   3. checks A is still on disk, the MCP server answers tools/list and a
//      tool call, the backend-like process imports a module it had not
//      loaded, and both still run A's code, not a mix with B's;
//   4. with both gone, the next start removes A.
//
//   GIGAMAIL_RESOURCES=dist/linux-unpacked/resources node tests/runtime_update.mjs
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const linuxRuntime = require('../linux_runtime');

const RES = path.resolve(process.env.GIGAMAIL_RESOURCES || 'dist/linux-unpacked/resources');
const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'gigamail-rt-update-'));
const env = { ...process.env, XDG_DATA_HOME: DATA, GIGAMAIL_ROOT: path.join(DATA, 'ade'), PYTHONNOUSERSITE: '1' };
delete env.PYTHONPATH;
fs.mkdirSync(env.GIGAMAIL_ROOT, { recursive: true });
const ROOT = linuxRuntime.runtimeRoot(env);

let failures = 0;
function check(cond, msg) {
  if (cond) console.log('  ✓', msg);
  else { failures += 1; console.log('  ✗', msg); }
}
setTimeout(() => { console.log('  ✗ watchdog: 4 minutes'); process.exit(1); }, 4 * 60 * 1000).unref();

// What main.js uses: the interpreter through `current` (the stable path the
// agents' configs keep), the sources for PYTHONPATH as ensure() returns them.
function install(version) {
  const r = linuxRuntime.ensure({ resourcesPath: RES, version, env });
  const p = typeof r === 'string' ? { python: r, src: r } : r;   // the API before the fix returned the link
  return { python: path.join(p.python, 'python', 'bin', 'python3'), src: path.join(p.src, 'gigamail', 'src') };
}

// A line-oriented child: send a line, wait for the first reply line matching.
function lineChild(cmd, args, extraEnv) {
  const child = spawn(cmd, args, { env: { ...env, ...extraEnv }, stdio: ['pipe', 'pipe', 'pipe'] });
  let buf = ''; let err = ''; const waiters = [];
  child.stdout.on('data', (d) => {
    buf += d.toString();
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1);
      const w = waiters.findIndex((x) => x.match(line));
      if (w >= 0) waiters.splice(w, 1)[0].resolve(line);
    }
  });
  child.stderr.on('data', (d) => { err += d.toString(); });
  return {
    child,
    stderr: () => err,
    ask(line, match, ms = 60000) {
      return new Promise((resolve) => {
        const t = setTimeout(() => resolve(null), ms);
        waiters.push({ match, resolve: (l) => { clearTimeout(t); resolve(l); } });
        if (line != null) child.stdin.write(line + '\n');
      });
    },
  };
}
const rpc = (id, method, params = {}) => JSON.stringify({ jsonrpc: '2.0', id, method, params });
const byId = (id) => (l) => { try { return JSON.parse(l).id === id; } catch (_) { return false; } };

async function main() {
  if (!fs.existsSync(path.join(RES, 'python', 'bin', 'python3'))) { console.log('  ✗ no runtime in', RES); process.exit(1); }
  console.log('[runtime] ' + ROOT);

  console.log('\n[1. version A, an MCP server and a backend-like process on it]');
  const A = install('9.0.0');
  const mcp = lineChild(A.python, ['-s', '-m', 'gigamail.server'], {});
  const init = await mcp.ask(rpc(1, 'initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } }), byId(1));
  check(!!init && !!JSON.parse(init).result, 'MCP server of A answers initialize');
  mcp.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  // Like the backend: PYTHONPATH from main.js, then, later, a module it had
  // not imported yet (the backend imports most of its modules lazily).
  const probeCode = [
    'import sys, gigamail',
    'print("ready", gigamail.__file__, flush=True)',
    'sys.stdin.readline()',
    'import gigamail.core.knowledge_index as k, json',
    'print("imported", k.__file__, flush=True)',
  ].join('\n');
  const probe = lineChild(A.python, ['-s', '-c', probeCode], { PYTHONPATH: A.src });
  const ready = await probe.ask(null, (l) => l.startsWith('ready '));
  check(!!ready, `backend-like process of A started (${ready ? ready.split(' ')[1] : probe.stderr().slice(-200)})`);
  const aDir = fs.realpathSync(path.join(ROOT, 'current'));

  console.log('\n[2. version B starts while they run]');
  install('9.0.1');
  check(fs.readlinkSync(path.join(ROOT, 'current')) === '9.0.1', 'current points at B');
  check(fs.existsSync(path.join(aDir, 'python', 'bin', 'python3')), 'A is still on disk while it is used');

  console.log('\n[3. the processes of A keep working, on A]');
  const list = await mcp.ask(rpc(2, 'tools/list'), byId(2));
  const tools = list ? (JSON.parse(list).result?.tools || []).length : 0;
  check(tools > 0, `MCP of A: tools/list after the update (${tools} tools)`);
  const call = await mcp.ask(rpc(3, 'tools/call', { name: 'list_accounts', arguments: {} }), byId(3));
  const res = call ? JSON.parse(call) : null;
  check(!!res && !!res.result && !res.result.isError, `MCP of A: a tool call after the update (${res ? JSON.stringify(res.result || res.error).slice(0, 120) : mcp.stderr().slice(-300)})`);
  const imp = await probe.ask('go', (l) => l.startsWith('imported '));
  check(!!imp, `backend-like process of A: a new import after the update (${imp || probe.stderr().split('\n').filter(Boolean).slice(-1)[0]})`);
  check(!!imp && imp.includes('/9.0.0/'), 'the import came from A, not from B');

  console.log('\n[4. with A unused, the next start removes it]');
  for (const c of [mcp.child, probe.child]) { try { c.kill(); } catch (_) { /* gone */ } }
  await new Promise((r) => setTimeout(r, 1000));
  install('9.0.1');
  check(!fs.existsSync(aDir), 'A removed once nothing uses it');
  check(fs.readdirSync(ROOT).sort().join(',') === '9.0.1,current', `left: ${fs.readdirSync(ROOT).sort().join(', ')}`);

  fs.rmSync(DATA, { recursive: true, force: true });
  console.log(failures ? `\n${failures} checks failed` : '\nall checks passed');
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.log('  ✗ fatal:', e.stack); process.exit(1); });
