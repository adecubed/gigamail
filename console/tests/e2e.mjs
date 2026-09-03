// e2e.mjs — collaudo della console nell'Electron VERO via Chrome DevTools
// Protocol. Copre cio' che jsdom non puo' provare: che un payload XSS
// dentro l'iframe della mail NON esegua in Chromium, che il renderer non
// abbia Node (nodeIntegration off), che il preload esponga solo cio' che
// deve, e — su un backend vergine — che l'onboarding si apra da solo.
//
//   npm run test:e2e
//
// Avvia `electron .` con --remote-debugging-port; in dev main.js lancia il
// backend dal venv del repo (../.venv). Con E2E_FRESH_APPDATA=<dir> la
// console parte su un %APPDATA% vuoto (primo avvio): e' cosi' che gira in
// CI. Senza, si aggancia al backend che trova e salta i controlli che
// richiedono zero account.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONSOLE_DIR = path.join(__dirname, '..');
const PORT = 9444;
const ELECTRON = path.join(CONSOLE_DIR, 'node_modules', '.bin', process.platform === 'win32' ? 'electron.cmd' : 'electron');

let failures = 0;
function check(cond, msg) {
  if (cond) console.log('  ✓', msg);
  else { failures += 1; console.log('  ✗', msg); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let b = '';
      res.on('data', (d) => { b += d; });
      res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

async function waitForTarget(timeoutMs) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      const targets = await getJson(`http://127.0.0.1:${PORT}/json`);
      const page = targets.find((t) => t.type === 'page' && t.url.includes('index_v2'));
      if (page) return page;
    } catch (_) { /* non ancora su */ }
    await sleep(500);
  }
  throw new Error('finestra principale non trovata via CDP');
}

class Cdp {
  constructor(url) { this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); }
  open() { return new Promise((res, rej) => { this.ws.on('open', res); this.ws.on('error', rej); this.ws.on('message', (m) => this._onMsg(m)); }); }
  _onMsg(raw) {
    const m = JSON.parse(raw.toString());
    if (m.id && this.pending.has(m.id)) { this.pending.get(m.id)(m); this.pending.delete(m.id); }
  }
  call(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res) => this.pending.set(id, res));
  }
  async evaluate(expression) {
    const r = await this.call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
    return r.result?.result?.value;
  }
  close() { this.ws.close(); }
}

async function main() {
  const env = { ...process.env };
  const fresh = process.env.E2E_FRESH_APPDATA;
  if (fresh) {
    fs.mkdirSync(path.join(fresh, 'ADE'), { recursive: true });
    env.APPDATA = fresh;
    env.ADE_ROOT = path.join(fresh, 'ADE');
    env.GIGAMAIL_NOTIFY_DESKTOP = '0';
  }
  const logPath = path.join(CONSOLE_DIR, 'e2e-electron.log');
  const log = fs.openSync(logPath, 'w');
  // Porta gia' in ascolto = un'altra istanza con il debugger: si fermerebbe
  // a interrogare quella, non la nostra. Meglio dirlo subito.
  try {
    await getJson(`http://127.0.0.1:${PORT}/json/version`);
    console.log(`  ✗ porta ${PORT} gia' occupata da un'altra istanza Electron: chiudila e riprova`);
    process.exit(1);
  } catch (_) { /* libera: bene */ }
  const child = spawn(ELECTRON, ['.', '--enable-logging', `--remote-debugging-port=${PORT}`], {
    cwd: CONSOLE_DIR, env, stdio: ['ignore', log, log], shell: process.platform === 'win32',
  });

  let cdp;
  try {
    const page = await waitForTarget(60000);
    cdp = new Cdp(page.webSocketDebuggerUrl);
    await cdp.open();

    // aspetta il bootstrap (backend + init)
    const bootEnd = Date.now() + 90000;
    let booted = false;
    while (Date.now() < bootEnd) {
      booted = await cdp.evaluate("typeof window.MailRender === 'object' && typeof window.openOnboarding === 'function' && document.getElementById('authLabel')?.textContent !== 'BACKEND NON RAGGIUNGIBILE' && !!document.getElementById('ade-dashboard')");
      if (booted) break;
      await sleep(1000);
    }
    check(booted, 'console avviata (backend raggiunto, moduli caricati)');

    console.log('\n[isolamento renderer / preload]');
    check(await cdp.evaluate("typeof require === 'undefined'"), 'require non esiste nel renderer (nodeIntegration off)');
    check(await cdp.evaluate("typeof process === 'undefined'"), 'process non esiste nel renderer');
    const apiKeys = await cdp.evaluate('Object.keys(window.ademail || {})');
    check(Array.isArray(apiKeys) && apiKeys.length > 10, `window.ademail espone ${apiKeys.length} metodi`);
    check(!apiKeys.some((k) => /token|secret|password/i.test(k)), 'nessun metodo che esponga token o segreti');
    const eaKeys = await cdp.evaluate('Object.keys(window.electronAPI || {})');
    check(!eaKeys.some((k) => /^(send|invoke|ipcRenderer|shell|exec)$/i.test(k)), 'electronAPI non espone ipcRenderer/shell grezzi');

    console.log('\n[XSS nell iframe della mail]');
    const PAYLOAD = [
      '<p id="ok">ciao</p>',
      '<script>parent.__xss = "script"; top.__xss = "script"</script>',
      '<img src="x" onerror="parent.__xss=\'onerror\'">',
      '<svg onload="parent.__xss=\'svg\'"></svg>',
      '<iframe srcdoc="<script>parent.parent.__xss=\'srcdoc\'</script>"></iframe>',
      '<a id="js" href="javascript:parent.__xss=\'href\'">js</a>',
      '<a id="ext" href="https://example.com/x">ext</a>',
      '<form action="https://example.com/steal"><input name="a"><button>go</button></form>',
      '<meta http-equiv="refresh" content="0;url=https://example.com/">',
      '<img src="cid:logo@x">',
    ].join('');
    await cdp.evaluate(`(() => {
      window.__xss = false; window.__opened = [];
      const host = document.createElement('div'); host.id = 'e2e-host'; document.body.appendChild(host);
      window.MailRender.renderMailHtml(host, ${JSON.stringify(PAYLOAD)}, {
        attachments: [{ name: 'logo.png', contentId: '<logo@x>' }],
        attachmentUrl: (a) => '/att/' + a.name,
        openExternal: (h) => window.__opened.push(h),
        autoHeight: true,
      }); return 'ok'; })()`);
    await sleep(1500);
    check((await cdp.evaluate('window.__xss')) === false, 'nessun payload ha eseguito codice nel padre');
    const frameInfo = await cdp.evaluate(`(() => {
      const f = document.querySelector('#e2e-host iframe');
      const d = f.contentDocument;
      return {
        sandbox: f.getAttribute('sandbox'),
        scripts: d.querySelectorAll('script').length,
        iframes: d.querySelectorAll('iframe').length,
        forms: d.querySelectorAll('form').length,
        metas: d.querySelectorAll('meta').length,
        jsHref: d.getElementById('js')?.getAttribute('href'),
        okText: d.getElementById('ok')?.textContent,
        cidSrc: d.querySelector('img[src^="/att/"]')?.getAttribute('src'),
        location: f.contentWindow.location.href,
        onerrorAttrs: d.querySelectorAll('[onerror],[onload]').length,
      };
    })()`);
    check(frameInfo.sandbox === 'allow-same-origin', `iframe sandbox = "${frameInfo.sandbox}" (niente script, niente popup)`);
    check(frameInfo.scripts === 0, 'nessun <script> nel documento');
    check(frameInfo.iframes === 0 && frameInfo.forms === 0, 'nessun iframe/form annidato');
    check(frameInfo.metas === 2, 'solo i due meta nostri (charset + CSP), meta refresh rimosso');
    check(frameInfo.jsHref == null, 'href javascript: rimosso');
    check(frameInfo.onerrorAttrs === 0, 'nessun attributo on*');
    check(frameInfo.okText === 'ciao', 'il contenuto legittimo e\' rimasto');
    check(frameInfo.cidSrc === '/att/logo.png', 'cid: risolto sull\'allegato');
    // Dopo document.open() Chromium da' all'iframe l'URL del documento
    // chiamante (file://...): cio' che conta e' che non sia remoto.
    check(!/^https?:/i.test(frameInfo.location), `l'iframe non ha navigato su un URL remoto (${String(frameInfo.location).slice(0, 40)})`);
    // click sul link esterno: intercettato → openExternal, nessuna navigazione
    await cdp.evaluate("document.querySelector('#e2e-host iframe').contentDocument.getElementById('ext').click(); 'clicked'");
    await sleep(300);
    const opened = await cdp.evaluate('window.__opened');
    check(Array.isArray(opened) && opened[0] === 'https://example.com/x', 'click su link → openExternal, non navigazione');
    check(!/^https?:/i.test(await cdp.evaluate("document.querySelector('#e2e-host iframe').contentWindow.location.href")), 'iframe non navigato dopo il click');

    console.log('\n[integrazione: apertura mail dalla lista]');
    const hasMail = await cdp.evaluate("document.querySelectorAll('.mail-item').length > 0");
    if (hasMail) {
      await cdp.evaluate("document.querySelector('.mail-item').click(); 'c'");
      const end = Date.now() + 15000;
      let body = null;
      while (Date.now() < end) {
        body = await cdp.evaluate(`(() => {
          const b = document.getElementById('mailBody');
          if (!b || !b.childNodes.length) return null;
          const f = b.querySelector('iframe');
          return { iframe: !!f, sandbox: f ? f.getAttribute('sandbox') : null, cls: f ? f.className : null, text: b.textContent.trim().length };
        })()`);
        if (body) break;
        await sleep(500);
      }
      check(!!body, 'la mail si apre nel pannello di dettaglio');
      if (body && body.iframe) {
        check(body.cls === 'mail-html-frame', 'il corpo HTML passa dalla pipeline unica (mail_render.js)');
        check(body.sandbox === 'allow-same-origin', 'iframe della mail vera: sandbox senza script');
      } else if (body) {
        console.log('  – prima mail in testo semplice: nessun iframe (ok)');
      }
    } else {
      console.log('  – nessuna mail nella lista: controllo saltato');
    }

    console.log('\n[binding dei bottoni per modulo]');
    const accountsN = await cdp.evaluate("document.querySelectorAll('#accountSelect option[value]:not([value=\"\"])').length");
    if (accountsN > 0) {
      await cdp.evaluate("document.getElementById('btnShowSent').click(); 's'");
      await sleep(1500);
      check((await cdp.evaluate('currentFolder')) === 'sent', 'btnShowSent → cartella "sent" (renderer_mail)');
      await cdp.evaluate("document.getElementById('btnShowInbox').click(); 'i'");
      await sleep(1500);
      check((await cdp.evaluate('currentFolder')) === 'inbox', 'btnShowInbox → cartella "inbox"');
      // bottoni opzionali (presenti solo in alcune viste): si prova se ci sono
      const has = async (id) => cdp.evaluate(`!!document.getElementById('${id}')`);
      if (await has('btnPriority')) {
        const before = await cdp.evaluate('priorityMode');
        await cdp.evaluate("document.getElementById('btnPriority').click(); 'p'");
        check((await cdp.evaluate('priorityMode')) === !before, 'btnPriority commuta priorityMode');
        await cdp.evaluate("document.getElementById('btnPriority').click(); 'p'");
      }
      if (await has('btnAddAccount') && await has('btnCloseImap')) {
        await cdp.evaluate("document.getElementById('btnAddAccount').click(); 'a'");
        check(!(await cdp.evaluate("document.getElementById('imapOverlay').classList.contains('hidden')")), 'btnAddAccount apre la modale IMAP (renderer_accounts)');
        await cdp.evaluate("document.getElementById('btnCloseImap').click(); 'c'");
        check(await cdp.evaluate("document.getElementById('imapOverlay').classList.contains('hidden')"), 'btnCloseImap la chiude');
      }
      if (await has('btnClearEvent')) {
        await cdp.evaluate("document.getElementById('btnClearEvent').click(); 'e'");
        check((await cdp.evaluate("document.getElementById('eventStatus')?.textContent ?? ''")) === '', 'btnClearEvent azzera lo stato evento (renderer_calendar)');
      }
    } else {
      console.log('  – nessun account: controlli sui binding saltati');
    }

    console.log('\n[onboarding]');
    const ob = await cdp.evaluate("fetch('http://127.0.0.1:8002/onboarding').then(r => r.json()).catch(() => null)");
    if (ob && ob.accounts === 0 && !ob.done) {
      check(!(await cdp.evaluate("document.getElementById('onboardingOverlay').classList.contains('hidden')")), 'guida aperta da sola al primo avvio');
      await cdp.evaluate("document.getElementById('obNext').click(); 'n'");
      await sleep(500);
      check(!(await cdp.evaluate("document.getElementById('obChoices').classList.contains('hidden')")), 'passo account: scelte Microsoft/IMAP visibili');
      await cdp.evaluate("document.getElementById('obNext').click(); 'n'");
      await sleep(300);
      check((await cdp.evaluate("document.getElementById('obAccountStatus').textContent")).length > 0, 'senza account non si avanza');
      check((await cdp.evaluate("document.getElementById('obTitle').textContent")) !== '', 'titolo passo presente');
      await cdp.evaluate("document.getElementById('obClose').click(); 'c'");
      await sleep(2000);
      check(await cdp.evaluate("document.getElementById('onboardingOverlay').classList.contains('hidden')"), 'chiusura senza account: guida nascosta');
      check(await cdp.evaluate("!!document.querySelector('.ob-empty')"), 'dashboard: empty state con CTA');
      const st = await cdp.evaluate("fetch('http://127.0.0.1:8002/onboarding').then(r => r.json())");
      check(st.done === false, 'flag "fatto" non scritto (nessun account)');
    } else {
      console.log('  – backend con account gia\' configurati: controlli primo avvio saltati (usa E2E_FRESH_APPDATA)');
      check(await cdp.evaluate("document.getElementById('onboardingOverlay').classList.contains('hidden')"), 'guida NON aperta con account esistenti');
      await cdp.evaluate("window.openOnboarding(); 'o'");
      await sleep(300);
      check(!(await cdp.evaluate("document.getElementById('onboardingOverlay').classList.contains('hidden')")), 'guida riapribile a comando');
      await cdp.evaluate("setHidden('onboardingOverlay', true); 'h'");
    }
  } catch (e) {
    failures += 1;
    console.log('  ✗ errore fatale:', e.message);
  } finally {
    try { cdp?.close(); } catch (_) { /* gia' chiuso */ }
    try {
      const v = await getJson(`http://127.0.0.1:${PORT}/json/version`);
      const b = new Cdp(v.webSocketDebuggerUrl); await b.open(); await b.call('Browser.close'); b.close();
      await sleep(1500);
    } catch (_) { /* gia' chiuso */ }
    try {
      if (process.platform === 'win32') spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
      else child.kill('SIGTERM');
    } catch (_) { /* gia' morto */ }
    fs.closeSync(log);
  }
  console.log(failures ? `\n${failures} controlli falliti (log: ${logPath})` : '\ntutti i controlli passati');
  process.exit(failures ? 1 : 0);
}

main();
