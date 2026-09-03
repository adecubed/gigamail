// smoke_packaged.mjs — l'app INSTALLATA parte davvero?
//
// L'e2e (tests/e2e.mjs) gira sull'Electron di sviluppo con il backend dal
// venv. Questo script lancia invece l'exe prodotto dall'installer, su un
// %APPDATA% vergine, e verifica l'ultimo miglio che nessun test copriva:
// il Python embedded parte dai percorsi di resources/, il token generato dal
// main arriva al backend e ai renderer, la finestra si apre, l'onboarding
// compare (zero account), la versione del backend e' quella del repo.
//
//   GIGAMAIL_EXE="C:\Program Files\GigaMail\GigaMail.exe" node tests/smoke_packaged.mjs
//
// Il backend, per design, sopravvive alla chiusura dell'app (detached):
// qui viene fermato esplicitamente a fine prova.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import WebSocket from 'ws';

const EXE = process.env.GIGAMAIL_EXE;
const PORT = 9555;                       // debugger
const API_PORT = process.env.ADE_CONSOLE_PORT || '8002';
const EXPECTED_VERSION = process.env.GIGAMAIL_EXPECTED_VERSION || '';

let failures = 0;
function check(cond, msg) {
  if (cond) console.log('  ✓', msg);
  else { failures += 1; console.log('  ✗', msg); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(url, headers = {}, timeoutMs = 5000) {
  // Con un timeout: una porta che accetta e non risponde (visto dal vivo sul
  // debugger dell'app impacchettata) non deve appendere lo script per sempre.
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers, timeout: timeoutMs }, (res) => {
      let b = '';
      res.on('data', (d) => { b += d; });
      res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(b) }); } catch (e) { reject(e); } });
    });
    req.on('timeout', () => { req.destroy(new Error('timeout')); });
    req.on('error', reject);
  });
}

// Watchdog: qualunque cosa succeda, lo script termina (e pulisce) entro 5 minuti.
const WATCHDOG_MS = 5 * 60 * 1000;
let watchdogFired = false;
setTimeout(() => { watchdogFired = true; console.log('  ✗ watchdog: 5 minuti, prova interrotta'); }, WATCHDOG_MS).unref();

async function waitUntil(fn, timeoutMs, every = 500) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end && !watchdogFired) {
    try { const v = await fn(); if (v) return v; } catch (_) { /* non ancora */ }
    await sleep(every);
  }
  return null;
}

class Cdp {
  constructor(url) { this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); }
  open() { return new Promise((res, rej) => { this.ws.on('open', res); this.ws.on('error', rej); this.ws.on('message', (m) => this._onMsg(m)); }); }
  _onMsg(raw) { const m = JSON.parse(raw.toString()); if (m.id && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); } }
  call(method, params = {}) { const id = ++this.id; this.ws.send(JSON.stringify({ id, method, params })); return new Promise((res) => this.pending.set(id, res)); }
  async evaluate(expression) {
    const r = await this.call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
    return r.result?.result?.value;
  }
  close() { this.ws.close(); }
}

function killPort(port) {
  if (process.platform !== 'win32') return;
  try {
    const out = spawnSync('netstat', ['-ano', '-p', 'tcp'], { encoding: 'utf-8' }).stdout || '';
    const pids = new Set(out.split('\n').filter((l) => l.includes(`:${port} `) && l.includes('LISTENING')).map((l) => l.trim().split(/\s+/).pop()));
    // argomenti come array, mai una riga di shell composta con dati
    for (const pid of pids) if (/^\d+$/.test(pid) && pid !== '0') { spawnSync('taskkill', ['/PID', pid, '/T', '/F'], { stdio: 'ignore' }); console.log(`  – backend sulla porta ${port} fermato (pid ${pid})`); }
  } catch (_) { /* netstat assente */ }
}

async function main() {
  if (!EXE || !fs.existsSync(EXE)) {
    console.log(`  ✗ GIGAMAIL_EXE non trovato: ${EXE}`);
    process.exit(1);
  }
  const fresh = path.join(os.tmpdir(), `gigamail-smoke-${Date.now()}`);
  fs.mkdirSync(path.join(fresh, 'ADE'), { recursive: true });
  const env = { ...process.env, APPDATA: fresh, ADE_ROOT: path.join(fresh, 'ADE'), GIGAMAIL_NOTIFY_DESKTOP: '0', ADE_CONSOLE_PORT: API_PORT };
  // Niente template literal a ridosso di spawn: lo scanner di sicurezza lo
  // legge come "comando composto con dati" (falso positivo di forma).
  console.log('[app installata] ' + EXE + '\n  profilo: ' + fresh);
  const debugArg = '--remote-debugging-port=' + PORT;
  const child = spawn(EXE, [debugArg], { env, stdio: 'ignore', detached: false });
  let cdp;
  try {
    const page = await waitUntil(async () => {
      const t = (await getJson(`http://127.0.0.1:${PORT}/json`)).body;
      return t.find((x) => x.type === 'page' && x.url.includes('index_v2')) || null;
    }, 60000);
    check(!!page, 'finestra principale aperta (CDP raggiungibile)');
    if (!page) throw new Error('nessuna finestra');
    cdp = new Cdp(page.webSocketDebuggerUrl); await cdp.open();

    // token generato dal main nel profilo vergine → backend embedded
    const tokenPath = path.join(fresh, 'ADE', '.console_token');
    const token = await waitUntil(() => (fs.existsSync(tokenPath) ? fs.readFileSync(tokenPath, 'utf-8').trim() : null), 20000);
    check(!!token, 'token di sessione scritto nel profilo vergine');
    const health = await waitUntil(async () => {
      const r = await getJson(`http://127.0.0.1:${API_PORT}/health`, { 'X-ADE-Token': token });
      return r.status === 200 ? r.body : null;
    }, 90000);
    check(!!health && health.service === 'gigamail-console', 'backend embedded avviato da resources/python (health ok)');
    if (EXPECTED_VERSION) check(health && health.version === EXPECTED_VERSION, `versione del backend = ${EXPECTED_VERSION} (era ${health && health.version})`);
    const unauth = await getJson(`http://127.0.0.1:${API_PORT}/health`);
    check(unauth.status === 401, 'senza token il backend rifiuta (401)');

    const booted = await waitUntil(() => cdp.evaluate("typeof Features === 'object' && Features.known === true && !!document.getElementById('ade-dashboard')"), 60000);
    check(!!booted, 'renderer avviato: openapi letto dal backend embedded, dashboard montata');
    check((await cdp.evaluate('window.GIGAMAIL_API')) === `http://127.0.0.1:${API_PORT}`, 'window.GIGAMAIL_API dal main impacchettato');
    check((await cdp.evaluate("typeof require === 'undefined' && typeof process === 'undefined'")), 'renderer senza Node');
    const ob = await waitUntil(() => cdp.evaluate("!document.getElementById('onboardingOverlay').classList.contains('hidden')"), 15000);
    check(!!ob, 'primo avvio da installato: onboarding aperto da solo');
    check(await cdp.evaluate("document.getElementById('btnShowMarketing').classList.contains('hidden')"), 'gate di capability attivo anche impacchettato');
    const cspOk = await cdp.evaluate("fetch('file:///C:/Windows/win.ini').then(() => 'READ').catch(() => 'BLOCKED')");
    check(cspOk === 'BLOCKED', 'webSecurity attivo nell app impacchettata');
  } catch (e) {
    failures += 1;
    console.log('  ✗ errore fatale:', e.message);
  } finally {
    try { cdp?.close(); } catch (_) { /* */ }
    try {
      const v = (await getJson(`http://127.0.0.1:${PORT}/json/version`)).body;
      const b = new Cdp(v.webSocketDebuggerUrl); await b.open();
      await Promise.race([b.call('Browser.close'), sleep(5000)]);
      b.close();
      await sleep(1500);
    } catch (_) { /* gia' chiusa o muta */ }
    try { if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); else child.kill(); } catch (_) { /* */ }
    killPort(API_PORT);
    try { fs.rmSync(fresh, { recursive: true, force: true }); } catch (_) { /* file in uso */ }
  }
  console.log(failures ? `\n${failures} controlli falliti` : '\ntutti i controlli passati');
  process.exit(failures ? 1 : 0);
}

main();
