const { app, BrowserWindow, session, shell, Notification, ipcMain, Menu, dialog } = require('electron');
const path = require('path');
const { autoUpdater } = require('electron-updater');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const crypto = require('crypto');
const Database = require('better-sqlite3');
const { restartReason, pidFromNetstat, pidFromLsof } = require('./backend_reuse');
const appPaths = require('./app_paths');
const { mt, setLang } = require('./main_i18n');
const { isExecutableName } = require('./attachment_guard');

let mainWindow;
// Finestre di composizione come figlie della principale: Windows le tiene
// sopra il genitore, cosi' una risposta aperta da una finestra massimizzata
// non finisce dietro (prima capitava, e andava ripescata dalla barra).
const childParent = () => (mainWindow && !mainWindow.isDestroyed() ? mainWindow : undefined);
let serverProcess;
let notifPoller = null;
let lastUnreadCounts = {};

// Token di sessione per il backend console: generato qui, passato al processo
// Python via env, allegato a OGNI richiesta verso il backend (sia dal main
// che dalle finestre, via onBeforeSendHeaders). Persistito nella cartella
// dati (%APPDATA%/ADE su Windows, ~/.ade su macOS: app_paths.js) così un
// backend già attivo da un avvio precedente resta raggiungibile.
const API_PORT = parseInt(process.env.ADE_CONSOLE_PORT || '8002', 10);
const API = `http://127.0.0.1:${API_PORT}`;

function loadOrCreateToken() {
  const dir = appPaths.dataRoot();
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const tokenPath = path.join(dir, '.console_token');
  try {
    const existing = fs.readFileSync(tokenPath, 'utf-8').trim();
    if (existing) return existing;
  } catch (e) {}
  const token = crypto.randomBytes(24).toString('hex');
  fs.writeFileSync(tokenPath, token, { mode: 0o600 });
  return token;
}
const API_TOKEN = loadOrCreateToken();
// Click secret: proves a request comes from a window of this console, so a
// send clicked here needs no Windows Hello. Made at every launch, kept in
// memory only, handed to the backend on stdin and added only to requests of
// our own windows. The token file above is readable by any process of the
// user, an agent included; this secret is not (http_api/console_click.py).
const HUMAN_SECRET = crypto.randomBytes(32).toString('hex');

// ── Uscite verso il sistema ────────────────────────────────────────────────
// Solo http/https/mailto possono lasciare l'app. Qualunque altro schema
// chiesto da una pagina — file:, ms-*, javascript: — resta dentro: una
// pagina compromessa da una mail non deve poter far partire un eseguibile
// (shell.openExternal su file:// lo farebbe).
const SAFE_EXTERNAL = /^(https?:|mailto:)/i;
function openExternalSafe(url) {
  const u = String(url || '').trim();
  if (!SAFE_EXTERNAL.test(u)) {
    console.warn('[GIGAMAIL] openExternal rifiutato:', u.slice(0, 120));
    return false;
  }
  shell.openExternal(u);
  return true;
}

// Ogni finestra, nessuna esclusa: niente popup, niente navigazione fuori
// dai file locali; i link esterni sicuri vanno al browser di sistema.
function hardenWindow(win) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith('file://')) return;
    event.preventDefault();
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(url)) return; // backend: non e' un link
    openExternalSafe(url);
  });
}

// ── Menu contesto copia/taglia/incolla per tutti i campi di testo ──
// Si applica a ogni finestra (presente e futura). Dove un HTML ha già un
// contextmenu custom con preventDefault (masker, allegati), quello vince.
app.on('web-contents-created', (_e, contents) => {
  contents.on('context-menu', (event, params) => {
    const { isEditable, selectionText, editFlags } = params;
    const hasSelection = selectionText && selectionText.trim().length > 0;

    // Mostra il menu nativo solo dove ha senso: campo editabile o testo selezionato
    if (!isEditable && !hasSelection) return;

    const template = [];
    if (isEditable) {
      template.push({ role: 'cut', enabled: editFlags.canCut, label: mt('menu_cut') });
    }
    template.push({ role: 'copy', enabled: editFlags.canCopy || hasSelection, label: mt('menu_copy') });
    if (isEditable) {
      template.push({ role: 'paste', enabled: editFlags.canPaste, label: mt('menu_paste') });
      template.push({ type: 'separator' });
      template.push({ role: 'selectAll', label: mt('menu_select_all') });
    }

    if (template.length) {
      const menu = Menu.buildFromTemplate(template);
      menu.popup({ window: BrowserWindow.fromWebContents(contents) });
    }
  });
});

// ── FOLLOWUP DB ───────────────────────────────────────────────────────────────
const FOLLOWUP_DB_PATH = path.join(appPaths.dataRoot(), 'mail', 'followups.db');

function getFollowupDb() {
  const dir = path.dirname(FOLLOWUP_DB_PATH);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const db = new Database(FOLLOWUP_DB_PATH);
  db.exec(`
    CREATE TABLE IF NOT EXISTS followups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_id TEXT,
      account_id INTEGER,
      subject TEXT,
      to_addr TEXT,
      deadline INTEGER,
      done INTEGER DEFAULT 0,
      created INTEGER DEFAULT (strftime('%s','now'))
    )
  `);
  return db;
}

// ── HTTP helper ───────────────────────────────────────────────────────────────
function apiGet(urlPath) {
  return new Promise((resolve, reject) => {
    const req = http.get(`${API}${urlPath}`, { timeout: 8000, headers: { 'X-ADE-Token': API_TOKEN } }, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch(e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// ── NOTIFICHE NUOVA MAIL ──────────────────────────────────────────────────────
async function checkNewMail() {
  try {
    const accounts = await apiGet('/accounts');
    if (!Array.isArray(accounts)) return;
    for (const acc of accounts) {
      const aid = acc.id;
      try {
        const data = await apiGet(`/mail/unread_count?account_id=${aid}`);
        const count = data?.count ?? 0;
        const prev = lastUnreadCounts[aid];

        if (prev !== undefined && count > prev) {
          const newCount = count - prev;
          showMailNotification(acc.name || acc.email || `Account ${aid}`, newCount);
          try {
            const mails = await apiGet(`/mail?top=${newCount + 5}&skip=0&account_id=${aid}`);
            const newMails = Array.isArray(mails) ? mails.filter(m => !m.isRead) : [];
            for (const mail of newMails.slice(0, newCount)) {
              mainWindow?.webContents.send('new-mail', {
                id: mail.id || mail.uid,
                subject: mail.subject || '',
                sender: mail.from?.emailAddress?.address || '',
                senderName: mail.from?.emailAddress?.name || '',
                folder: 'INBOX',
                account_id: aid,
              });
            }
          } catch(e) {}
        }
        lastUnreadCounts[aid] = count;
      } catch(e) {}
    }
  } catch(e) {}
}

function showMailNotification(accountName, count) {
  if (!Notification.isSupported()) return;
  const notif = new Notification({
    title: `GigaMail — ${accountName}`,
    body: mt(count === 1 ? 'new_mail_one' : 'new_mail_many', { count }),
    silent: false,
  });
  notif.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  notif.show();
}

// ── NOTIFICHE FOLLOW-UP ───────────────────────────────────────────────────────
async function checkFollowups() {
  try {
    const db = getFollowupDb();
    const now = Math.floor(Date.now() / 1000);
    const due = db.prepare(
      'SELECT * FROM followups WHERE done=0 AND deadline <= ? ORDER BY deadline ASC LIMIT 5'
    ).all(now);
    db.close();
    for (const item of due) {
      if (!Notification.isSupported()) continue;
      const notif = new Notification({
        title: mt('followup_title'),
        body: `${item.subject || mt('no_subject')} → ${item.to_addr || ''}`,
        silent: false,
      });
      notif.on('click', () => {
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.focus();
        }
      });
      notif.show();
    }
  } catch(e) { console.error('[FOLLOWUP]', e.message); }
}

// ── POLLING ───────────────────────────────────────────────────────────────────
function startPolling() {
  if (notifPoller) return;
  setTimeout(async () => {
    await checkNewMail();
    await checkFollowups();
    notifPoller = setInterval(async () => {
      await checkNewMail();
      await checkFollowups();
    }, 60 * 1000);
  }, 15000);
}

function stopPolling() {
  if (notifPoller) { clearInterval(notifPoller); notifPoller = null; }
}

// ── SERVER PYTHON ─────────────────────────────────────────────────────────────
function getResourcesPath() {
  if (app.isPackaged) return path.join(process.resourcesPath);
  return path.join(__dirname, '..');
}

// Come la vede Python (Path.resolve): link e giunzioni risolti, o un
// percorso uguale sembrerebbe diverso e il backend verrebbe rifatto a
// ogni avvio.
function realDir(dir) {
  try { return fs.realpathSync.native(dir); } catch (_) { return path.resolve(dir); }
}

function startPythonServer() {
  const resourcesPath = getResourcesPath();
  // Packaged: python embedded in resources. Dev: venv del repo gigamail
  // (console/ sta accanto a src/ e .venv/). Il percorso cambia per
  // piattaforma: app_paths.js.
  const pythonPath = appPaths.pythonPath({
    packaged: app.isPackaged, resourcesPath, devRoot: path.join(__dirname, '..'),
  });
  const srcDir = app.isPackaged
    ? path.join(resourcesPath, 'gigamail', 'src')
    : path.join(__dirname, '..', 'src');

  // Riusa un backend sulla porta SOLO se e' davvero il nostro: 200 +
  // service "gigamail-console". Qualunque altra cosa in ascolto (una
  // vecchia "ADE Mail" installata, un altro servizio) ha gia' fatto
  // parlare la finestra nuova con un backend vecchio, in silenzio.
  const startBackend = () => {
    console.log('[GIGAMAIL] Avvio backend console...');
    // Da sorgente serve il venv del repo: senza, spawn falliva con un
    // "Uncaught Exception" del main process che non diceva cosa fare.
    if (!app.isPackaged && !fs.existsSync(pythonPath)) {
      const root = path.join(__dirname, '..');
      const pip = process.platform === 'win32' ? '.venv\\Scripts\\pip' : '.venv/bin/pip';
      dialog.showErrorBox('GigaMail: Python environment missing',
        `Running from the sources needs the repo virtualenv, not found at:\n${pythonPath}\n\n`
        + `Create it once, from ${root}:\n\n`
        + `  python -m venv .venv\n  ${pip} install -e ".[console,all]"\n\nthen run npm start again.`);
      return;
    }
    serverProcess = spawn(pythonPath, [
      '-s',   // mai il site-packages utente: solo cio' che l'installer porta
      '-X', 'utf8', '-c', 'from gigamail.http_api import main; main()',
    ], {
      windowsHide: true,
      detached: true,   // il backend sopravvive alla chiusura dell'app
      env: {
        ...process.env,
        PYTHONPATH: srcDir,
        PYTHONNOUSERSITE: '1',
        ADE_CONSOLE_TOKEN: API_TOKEN,
        ADE_CONSOLE_PORT: String(API_PORT),
        ADE_CONSOLE_HUMAN_STDIN: '1',   // the click secret comes on stdin, below
        // ...and here too: on Windows the venv's python.exe is a launcher that
        // starts the real interpreter, and the stdin line did not always reach
        // it (Approve kept asking Windows Hello). The backend deletes this
        // variable as soon as it reads it, before it starts any agent.
        ADE_CONSOLE_HUMAN: HUMAN_SECRET,
      },
    });
    try { serverProcess.stdin.end(HUMAN_SECRET + String.fromCharCode(10)); }
    catch (e) { console.error('[GIGAMAIL] click secret not passed: every send will ask Windows Hello', e.message); }
    serverProcess.stdout?.on('data', (d) => console.log('[SERVER]', d.toString().trim()));
    serverProcess.stderr?.on('data', (d) => console.error('[SERVER ERR]', d.toString().trim()));
    serverProcess.on('exit', (code) => console.log('[SERVER] exit', code));
    serverProcess.on('error', (e) => console.error('[SERVER] not started:', e.message));
    serverProcess.unref(); // non tenere vivo Electron per via del figlio
  };

  // Resolves once it is decided which backend the window will talk to: the
  // one found (current), or a new one being started. The caller waits for
  // /health only after this, or it would see the old backend answer and
  // open the window on a process about to be replaced.
  return new Promise((resolve) => {
    const start = () => { startBackend(); resolve(); };
    const req = http.get(`${API}/health`, { headers: { 'X-ADE-Token': API_TOKEN } }, (res) => {
      let body = '';
      res.on('data', (d) => { body += d; });
      res.on('end', async () => {
        let health = null;
        try { health = JSON.parse(body); } catch (_) { /* non JSON: non e' il nostro */ }
        const ours = res.statusCode === 200 && health && health.service === 'gigamail-console';
        if (!ours) {
          console.error(`[GIGAMAIL] Sulla porta ${API_PORT} risponde qualcosa che NON e' `
            + `GigaMail (HTTP ${res.statusCode}). Chiudi quel programma (es. una `
            + `vecchia "ADE Mail") e riavvia: non mi aggancio a un backend sconosciuto.`);
          // Proviamo comunque a partire: se la porta e' davvero occupata il bind
          // fallisce e lo vedrai nei log, invece di una UI che parla con un altro.
          start();
          return;
        }
        const why = restartReason(health, app.getVersion(), realDir(srcDir))
          || (await backendKnowsClicks() ? '' : "it does not know this console's click secret");
        if (!why) {
          console.log(`[GIGAMAIL] Backend console gia' attivo su porta ${API_PORT}`);
          resolve();
          return;
        }
        // An outdated backend left running by a previous start (an update,
        // new code): replace it, once. If it cannot be stopped the console
        // keeps the one that answers rather than not opening at all.
        console.log(`[GIGAMAIL] Backend on port ${API_PORT} is outdated (${why}): replacing it`);
        if (await stopBackend(health.pid)) start();
        else {
          console.error('[GIGAMAIL] Outdated backend not stopped: using it as it is');
          resolve();
        }
      });
    });
    req.on('error', start);
    req.setTimeout(5000, () => req.destroy(new Error('timeout')));
    req.end();
  });
}

/** Whether the backend on the port knows this launch's click secret. A
 *  backend left running by an earlier launch does not: kept, it would ask
 *  Windows Hello for every send. Any doubt (old backend, no answer) is no. */
function backendKnowsClicks() {
  return new Promise((resolve) => {
    const req = http.get(`${API}/console/human`,
      { timeout: 5000, headers: { 'X-ADE-Token': API_TOKEN, 'X-ADE-Human': HUMAN_SECRET } }, (res) => {
        let body = '';
        res.on('data', (d) => { body += d; });
        res.on('end', () => { try { resolve(res.statusCode === 200 && JSON.parse(body).known === true); } catch (_) { resolve(false); } });
      });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

/** PID of the process listening on the backend port; 0 if not found. */
function backendPid() {
  try {
    if (process.platform === 'win32') {
      return pidFromNetstat(execFileSync('netstat', ['-ano', '-p', 'TCP'],
        { encoding: 'utf-8', windowsHide: true }), API_PORT);
    }
    return pidFromLsof(execFileSync('lsof', ['-nP', `-iTCP:${API_PORT}`, '-sTCP:LISTEN', '-t'],
      { encoding: 'utf-8' }));
  } catch (_) { return 0; }
}

/** Stop the backend that answered /health as ours, and wait for the port
 *  to go quiet. `pid` comes from /health; older backends do not send it and
 *  are found by port. Resolves false if it is still answering. */
async function stopBackend(pid) {
  const target = parseInt(pid, 10) || backendPid();
  if (!target) return false;
  try { process.kill(target); } catch (_) { /* already gone, or not ours to kill */ }
  if (process.platform === 'win32') {
    // and its children: the venv's python.exe launcher starts the real one
    try { execFileSync('taskkill', ['/PID', String(target), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); } catch (_) { /* gone */ }
  }
  for (let i = 0; i < 25; i++) {
    // Only a refused connection means the port is free. A slow answer (a
    // timeout) is a backend still alive: counting it as stopped started the
    // new backend on a busy port, and the window stayed on the old one.
    const alive = await new Promise((resolve) => {
      const req = http.get(`${API}/health`, { timeout: 1500, headers: { 'X-ADE-Token': API_TOKEN } },
        (res) => { res.resume(); resolve(true); });
      req.on('error', (e) => resolve(e && e.code !== 'ECONNREFUSED'));
      req.on('timeout', () => { req.destroy(new Error('timeout')); });
    });
    if (!alive) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

// ── WINDOW ────────────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    frame: false,
    backgroundColor: '#E8EEF4',
    title: 'GigaMail',
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index_v2.html'));

  hardenWindow(mainWindow);

  // Only where the app is signed (app_paths.autoUpdateSupported):
  // electron-updater refuses an unsigned app on macOS.
  if (app.isPackaged && appPaths.autoUpdateSupported()) {
    setTimeout(() => autoUpdater.checkForUpdatesAndNotify(), 3000);
  }
}

// Attende che il backend risponda a /health prima di aprire la finestra:
// il processo Python impiega qualche secondo a partire e la UI non fa retry
// sul primo caricamento account.
function waitForBackend(maxMs = 20000) {
  const started = Date.now();
  return new Promise((resolve) => {
    const tryOnce = () => {
      const req = http.get(`${API}/health`, { timeout: 1000, headers: { 'X-ADE-Token': API_TOKEN } }, (res) => {
        if (res.statusCode === 200) { resolve(true); return; }
        res.resume();
        retry();
      });
      req.on('error', retry);
      req.on('timeout', () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() - started > maxMs) { resolve(false); return; }
      setTimeout(tryOnce, 500);
    };
    tryOnce();
  });
}

// Icona da sorgente: l'app installata la prende dall'exe / dal bundle, ma
// con `npm start` Windows e macOS mostravano quella di Electron.
const DEV_ICON = app.isPackaged ? null : path.join(__dirname, '..', 'docs', 'brand',
  process.platform === 'win32' ? 'gigamail.ico' : 'gigamail-logo-256.png');
if (DEV_ICON) {
  app.on('browser-window-created', (_e, win) => { try { win.setIcon(DEV_ICON); } catch {} });
}

// ── APP ───────────────────────────────────────────────────────────────────────
// ── gigamail:// links: toast buttons, the CLI's forward, the agent's links ──
// One instance: a second launch (Windows opens the protocol handler as a
// new process) hands its argv to this one and exits. The CLI, registered
// on the scheme in HKLM for the toasts, forwards the URL to the bridge
// below when the console runs, and starts it with --open-url when not.
const OpenUrl = require('./open_url');
let pendingUrl = OpenUrl.fromArgv(process.argv);
const BRIDGE_TOKEN = crypto.randomBytes(24).toString('hex');
let bridgeServer = null;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_event, argv) => {
    const url = OpenUrl.fromArgv(argv);
    if (url) handleOpenUrl(url);
    else if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });
  app.on('open-url', (event, url) => { event.preventDefault(); handleOpenUrl(url); });
  try {
    if (app.isPackaged) app.setAsDefaultProtocolClient('gigamail');
    else app.setAsDefaultProtocolClient('gigamail', process.execPath, [path.resolve(process.argv[1] || '.')]);
  } catch (_) { /* best effort: HKLM, written by desktop-setup, is what the toasts read */ }
}

function handleOpenUrl(url) {
  const req = OpenUrl.parse(url);
  if (!req) return;
  if (!mainWindow) { pendingUrl = url; return; }   // handled once the window exists
  if (req.kind === 'approval') openApprovalWindow(req.id, req.action);
  else if (req.kind === 'reply') openReplyAlertWindow(req.key);
  else if (req.kind === 'mail') {
    mainWindow.webContents.send('open-mail', { id: req.id, folder: req.folder || null, account_id: req.account_id || null });
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
}

// Where the CLI reaches this console: console.json next to the backend's
// data, with the bridge's port and token and how to start the app.
function startBridge() {
  bridgeServer = http.createServer((req, res) => {
    if (req.method !== 'POST' || req.url !== '/open-url' || req.headers['x-gigamail-bridge'] !== BRIDGE_TOKEN) {
      res.writeHead(404); res.end(); return;
    }
    let body = '';
    req.on('data', (c) => { body += c; if (body.length > 4096) req.destroy(); });
    req.on('end', () => {
      let url = '';
      try { url = String(JSON.parse(body).url || ''); } catch (_) { url = ''; }
      if (!OpenUrl.parse(url)) { res.writeHead(400); res.end(); return; }
      handleOpenUrl(url);
      res.writeHead(204); res.end();
    });
  });
  bridgeServer.listen(0, '127.0.0.1', () => {
    const info = {
      port: bridgeServer.address().port, token: BRIDGE_TOKEN, pid: process.pid,
      exe: process.execPath, args: app.isPackaged ? [] : [path.resolve(process.argv[1] || '.')],
    };
    try { fs.writeFileSync(path.join(appPaths.dataRoot(), 'console.json'), JSON.stringify(info), { mode: 0o600 }); }
    catch (e) { console.error('[GIGAMAIL] console.json not written: toast buttons fall back to the terminal', e.message); }
  });
}

function popupWindow(width, height, preload, file, title) {
  const main = mainWindow?.getBounds() || { x: 100, y: 100, width: 1280, height: 820 };
  const win = new BrowserWindow({
    x: main.x + Math.floor((main.width - width) / 2),
    y: main.y + Math.floor((main.height - height) / 2),
    width, height, minWidth: 420, minHeight: 360,
    frame: false, transparent: false, backgroundColor: '#EBF2FA', resizable: true,
    title, parent: childParent(), show: false,
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],
      preload: path.join(__dirname, preload),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, file));
  hardenWindow(win);
  win.once('ready-to-show', () => { win.show(); win.focus(); });
  return win;
}

const approvalWindows = new Map();   // request_id -> window: one per request
function openApprovalWindow(requestId, action) {
  const open = approvalWindows.get(requestId);
  if (open && !open.isDestroyed()) {
    open.webContents.send('load-approval', { request_id: requestId, action });
    open.focus();
    return;
  }
  const win = popupWindow(620, 640, 'preload_approval.js', 'approval_window.html', mt('title_approval'));
  approvalWindows.set(requestId, win);
  win.on('closed', () => { if (approvalWindows.get(requestId) === win) approvalWindows.delete(requestId); });
  win.webContents.once('did-finish-load', () => win.webContents.send('load-approval', { request_id: requestId, action }));
}

function openReplyAlertWindow(key) {
  const win = popupWindow(560, 520, 'preload_reply_alert.js', 'reply_alert_window.html', mt('title_reply'));
  win.webContents.once('did-finish-load', () => win.webContents.send('load-reply-alert', { key }));
}

ipcMain.on('approval-window-close', (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('approval-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('approval-window-open-pending', () => {
  if (!mainWindow) return;
  mainWindow.webContents.send('show-pending-view');
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
});

app.whenReady().then(async () => {
  if (DEV_ICON && process.platform === 'darwin' && app.dock) {
    try { app.dock.setIcon(path.join(__dirname, '..', 'docs', 'brand', 'gigamail-logo-1024.png')); } catch {}
  }
  const backendChosen = startPythonServer();

  // Whitelist esplicita: solo il microfono serve alle pagine (dettatura in
  // voice_mail.js). Le notifiche desktop partono dal main process e non
  // passano da qui; tutto il resto (geolocation, clipboard-read, ...) è negato.
  const ALLOWED_PERMISSIONS = new Set(['media', 'audioCapture']);
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission));
  });

  // Header token su OGNI richiesta delle finestre verso il backend console:
  // nessuna modifica necessaria alle fetch dei renderer.
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const u = details.url;
    if (u.startsWith(`http://127.0.0.1:${API_PORT}/`) || u.startsWith(`http://localhost:${API_PORT}/`)) {
      details.requestHeaders['X-ADE-Token'] = API_TOKEN;
      // only pages of the console itself (file://) carry the click secret
      const wc = details.webContents;
      if (wc && !wc.isDestroyed() && String(wc.getURL()).startsWith('file:')) {
        details.requestHeaders['X-ADE-Human'] = HUMAN_SECRET;
      }
    }
    callback({ requestHeaders: details.requestHeaders });
  });

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    // Solo per le risposte del backend locale: se un allegato HTML venisse
    // aperto come documento, script-src 'none' gli impedisce di eseguire
    // codice. Le finestre file:// hanno la loro meta-CSP nell'HTML e le
    // risorse remote (font, API) tengono i loro header: onHeadersReceived
    // intercetta anche file:// e una CSP aggiunta qui si sommerebbe in
    // intersezione con quella dei meta tag, bloccando gli script locali.
    const isBackend = details.url.startsWith(`http://127.0.0.1:${API_PORT}/`)
                   || details.url.startsWith(`http://localhost:${API_PORT}/`);
    if (!isBackend) { callback({}); return; }
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; script-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; object-src 'self'",
        ],
      },
    });
  });

  await backendChosen;
  const backendReady = await waitForBackend();
  if (!backendReady) console.error('[GIGAMAIL] Backend non raggiungibile entro 20s — apro comunque la finestra');
  createWindow();
  startPolling();
  startBridge();
  if (pendingUrl) {
    const url = pendingUrl; pendingUrl = '';
    mainWindow.webContents.once('did-finish-load', () => setTimeout(() => handleOpenUrl(url), 300));
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopPolling();
  // The bridge goes; how to start the app stays, so a toast button pressed
  // while the console is closed (the CLI reads this file) can open it.
  try {
    bridgeServer?.close();
    const info = { exe: process.execPath, args: app.isPackaged ? [] : [path.resolve(process.argv[1] || '.')] };
    fs.writeFileSync(path.join(appPaths.dataRoot(), 'console.json'), JSON.stringify(info), { mode: 0o600 });
  } catch (_) { /* best effort */ }
  // Il backend NON viene killato: resta in background cosi' il prossimo
  // avvio dell'app e' istantaneo (il check /health pre-spawn lo riusa).
  if (process.platform !== 'darwin') app.quit();
});

// Tranne quando sta per partire l'installer dell'aggiornamento: il backend
// tiene aperti python.exe e le sue DLL in resources/python, l'installer non
// li puo' sovrascrivere e lascia la cartella a meta' (la 0.6.1 ripartiva
// senza il modulo gigamail). Prima di passare la mano all'installer il
// backend va terminato, in modo sincrono: dopo before-quit non c'e' tempo.
let updateDownloaded = false;
function stopBackendSync() {
  const pid = backendPid();
  if (!pid) return;
  if (process.platform === 'win32') {
    try { execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); } catch (_) { /* gone */ }
  } else {
    try { process.kill(pid); } catch (_) { /* gone */ }
  }
}
app.on('before-quit', () => { if (updateDownloaded) stopBackendSync(); });

ipcMain.on('mail-opened',  () => {});
ipcMain.on('window-close',    () => mainWindow?.close());
ipcMain.on('window-minimize', () => mainWindow?.minimize());
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});

// ── FOLLOWUP IPC ──────────────────────────────────────────────────────────────
ipcMain.handle('followup-save', (event, { message_id, account_id, subject, to_addr, hours }) => {
  try {
    const db = getFollowupDb();
    const deadline = Math.floor(Date.now() / 1000) + (hours * 3600);
    db.prepare(
      'INSERT INTO followups (message_id, account_id, subject, to_addr, deadline) VALUES (?,?,?,?,?)'
    ).run(message_id || '', account_id || 0, subject || '', to_addr || '', deadline);
    db.close();
    return { ok: true };
  } catch(e) { return { ok: false, error: e.message }; }
});

ipcMain.handle('followup-count', () => {
  try {
    const db = getFollowupDb();
    const now = Math.floor(Date.now() / 1000);
    const row = db.prepare('SELECT COUNT(*) as n FROM followups WHERE done=0 AND deadline <= ?').get(now);
    db.close();
    return { count: row?.n || 0 };
  } catch(e) { return { count: 0 }; }
});

ipcMain.handle('followup-done', (event, { id }) => {
  try {
    const db = getFollowupDb();
    db.prepare('UPDATE followups SET done=1 WHERE id=?').run(id);
    db.close();
    return { ok: true };
  } catch(e) { return { ok: false }; }
});

ipcMain.handle('followup-list-pending', () => {
  try {
    const db = getFollowupDb();
    const now = Math.floor(Date.now() / 1000);
    const rows = db.prepare('SELECT * FROM followups WHERE done=0 ORDER BY deadline ASC').all();
    db.close();
    return rows.map(r => ({ ...r, overdue: r.deadline <= now }));
  } catch(e) { return []; }
});

// ── COMPACT MODE ──────────────────────────────────────────────────────────────
let isCompact = false;
let savedBounds = null;
const COMPACT_WIDTH = 350;

// Documenti per le regole di risposta (0.2.1): file picker nativo, il
// renderer riceve solo i percorsi assoluti scelti dall'utente.
ipcMain.handle('pick-files', async () => {
  const r = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: mt('files_documents'), extensions: ['pdf', 'docx', 'xlsx', 'txt', 'md', 'csv'] },
              { name: mt('files_all'), extensions: ['*'] }],
  });
  return r.canceled ? [] : r.filePaths;
});

ipcMain.handle('toggle-compact', () => {
  if (!mainWindow) return { compact: isCompact };
  if (!isCompact) {
    savedBounds = mainWindow.getBounds();
    mainWindow.setAlwaysOnTop(true);
    mainWindow.setBounds({ x: savedBounds.x, y: savedBounds.y, width: COMPACT_WIDTH, height: savedBounds.height }, true);
    isCompact = true;
  } else {
    mainWindow.setAlwaysOnTop(false);
    mainWindow.setBounds(savedBounds, true);
    isCompact = false;
  }
  return { compact: isCompact };
});


// ── FINESTRE MAIL FIGLIE ──────────────────────────────────────────────────────
const mailWindows = new Map(); // id -> BrowserWindow

// The main window tells which language it applied: notifications, menus and
// dialogs shown from here follow it.
ipcMain.on('set-lang', (_event, lang) => { setLang(lang); });

ipcMain.on('open-mail-window', (event, data) => {
  const key = `${data.account_id}:${data.id}`;

  if (mailWindows.has(key)) {
    const w = mailWindows.get(key);
    if (!w.isDestroyed()) { w.focus(); return; }
  }

  const win = new BrowserWindow({
    width: 680,
    height: 700,
    minWidth: 480,
    minHeight: 400,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    title: 'GigaMail',
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_mail.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'mail_window.html'));

  hardenWindow(win);

  win.webContents.once('did-finish-load', () => {
    win.webContents.send('load-mail', data);
  });

  win.on('closed', () => mailWindows.delete(key));
  mailWindows.set(key, win);
});

ipcMain.on('mail-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('mail-window-dock-back', (event, data) => {
  mainWindow?.webContents.send('dock-mail-back', data);
  const win = BrowserWindow.fromWebContents(event.sender);
  setTimeout(() => win?.close(), 300);
});
ipcMain.on('mail-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('mail-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});
ipcMain.on('mail-window-open-reply', (event, data) => {
  const senderWin = BrowserWindow.fromWebContents(event.sender);
  const bounds = senderWin?.getBounds() || { x:200, y:100, width:680, height:700 };

  const win = new BrowserWindow({
    x: bounds.x + bounds.width + 10,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    minWidth: 420,
    minHeight: 400,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    title: mt('title_reply'),
    parent: childParent(),   // resta sopra la principale: non finisce dietro
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_reply.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'reply_window.html'));
  hardenWindow(win);
  win.webContents.once('did-finish-load', () => {
    win.webContents.send('load-reply', data);
  });
});

ipcMain.on('reply-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('reply-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('reply-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// ── FINESTRA NUOVA MAIL ───────────────────────────────────────────────────────
ipcMain.on('open-new-mail-window', (event, data) => {
  const main = mainWindow?.getBounds() || { x:100, y:100, width:1280, height:820 };
  const win = new BrowserWindow({
    x: main.x + Math.floor((main.width - 600) / 2),
    y: main.y + Math.floor((main.height - 700) / 2),
    width: 600, height: 700,
    minWidth: 480, minHeight: 500,
    frame: false, transparent: false, backgroundColor: '#EBF2FA',
    resizable: true,
    title: mt('title_new_mail'),
    parent: childParent(),
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_new_mail.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'new_mail_window.html'));
  hardenWindow(win);
  win.webContents.once('did-finish-load', () => {
    win.webContents.send('load-new-mail', data || {});
  });
});
ipcMain.on('new-mail-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('new-mail-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('new-mail-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// ── FINESTRA RISPOSTA DALLA CONSOLE ──────────────────────────────────────────
ipcMain.on('open-reply-window', (event, data) => {
  const main = mainWindow?.getBounds() || { x:100, y:100, width:1280, height:820 };
  const win = new BrowserWindow({
    x: main.x + Math.floor((main.width - 600) / 2),
    y: main.y + Math.floor((main.height - 700) / 2),
    width: 600, height: 700,
    minWidth: 420, minHeight: 400,
    frame: false, transparent: false, backgroundColor: '#EBF2FA',
    resizable: true,
    title: mt('title_reply'),
    parent: childParent(),   // resta sopra la principale: non finisce dietro
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_reply.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'reply_window.html'));
  hardenWindow(win);
  win.webContents.once('did-finish-load', () => {
    win.webContents.send('load-reply', data);
  });
});
ipcMain.handle('mail-window-open-external', (_event, url) => openExternalSafe(url));
ipcMain.handle('open-external', (_event, url) => openExternalSafe(url));

// ── Allegati mail: apri / salva con nome ──
const os = require('os');

ipcMain.handle('mail-attachment-open', async (_evt, { name, bytes }) => {
  try {
    const safe = (name || 'allegato').replace(/[\\/:*?"<>|]/g, '_');
    // Opening a program means running it: never from here, whichever
    // window asks. "Save as" stays (attachment_guard.js).
    if (isExecutableName(name) || isExecutableName(safe)) {
      return { ok: false, blocked: true, error: mt('attachment_exec_blocked') };
    }
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ade-att-'));
    const filePath = path.join(dir, safe);
    fs.writeFileSync(filePath, Buffer.from(bytes));
    const err = await shell.openPath(filePath);   // '' = ok
    return { ok: !err, error: err || null, path: filePath };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle('mail-attachment-save-as', async (_evt, { name, bytes }) => {
  try {
    const safe = (name || 'allegato').replace(/[\\/:*?"<>|]/g, '_');
    const { canceled, filePath } = await dialog.showSaveDialog({ defaultPath: safe });
    if (canceled || !filePath) return { ok: false, canceled: true };
    fs.writeFileSync(filePath, Buffer.from(bytes));
    return { ok: true, path: filePath };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.on('window-resize', (event, { w, h }) => {
  BrowserWindow.fromWebContents(event.sender)?.setSize(
    Math.max(380, Math.round(w)),
    Math.max(380, Math.round(h))
  );
});

// ── FINESTRA CALENDARIO ──────────────────────────────────────────────────────
let calendarWindow = null;
ipcMain.on('open-calendar-window', () => {
  if (calendarWindow && !calendarWindow.isDestroyed()) { calendarWindow.focus(); return; }
  calendarWindow = new BrowserWindow({
    width: 900, height: 700, minWidth: 700, minHeight: 500,
    frame: false, transparent: true, backgroundColor: '#00000000',
    title: mt('title_calendar'),
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_calendar.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  calendarWindow.loadFile(path.join(__dirname, 'calendar_window.html'));
  hardenWindow(calendarWindow);
  calendarWindow.on('closed', () => { calendarWindow = null; });
});
ipcMain.on('calendar-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('calendar-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('calendar-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// ── FINESTRA MARKETING ───────────────────────────────────────────────────────
// (la personalizzazione AI del bulk verra' delegata all'agente)
let marketingWindow = null;
ipcMain.on('open-marketing-window', () => {
  if (marketingWindow && !marketingWindow.isDestroyed()) { marketingWindow.focus(); return; }
  marketingWindow = new BrowserWindow({
    width: 1000, height: 680, minWidth: 700, minHeight: 500,
    frame: false, transparent: true, backgroundColor: '#00000000',
    title: mt('title_marketing'),
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_marketing.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  marketingWindow.loadFile(path.join(__dirname, 'marketing_window.html'));
  hardenWindow(marketingWindow);
  marketingWindow.on('closed', () => { marketingWindow = null; });
});
ipcMain.on('marketing-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('marketing-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('marketing-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// "Chiedi alle mail": la domanda ora va all'AGENTE (endpoint /mail_ask →
// agent_bridge), non piu' all'LLM interno.

// ------ ASK MAIL (delegato all'agente) ----------------------------------
let askWindow = null;
ipcMain.on('open-ask-window', (event, data) => {
  if (askWindow && !askWindow.isDestroyed()) { askWindow.focus(); return; }
  const main = mainWindow?.getBounds() || { x:100, y:100, width:1280, height:820 };
  askWindow = new BrowserWindow({
    width: 760, height: 720, minWidth: 480, minHeight: 500,
    x: main.x + Math.floor((main.width - 760) / 2),
    y: main.y + Math.floor((main.height - 720) / 2),
    frame: false, transparent: true, backgroundColor: '#00000000',
    title: mt('title_ask'),
    webPreferences: {
      additionalArguments: [`--gigamail-api=${API}`],  // ADE_CONSOLE_PORT fino ai renderer
      preload: path.join(__dirname, 'preload_ask.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  askWindow.loadFile(path.join(__dirname, 'ask_window.html'));
  hardenWindow(askWindow);
  askWindow.webContents.once('did-finish-load', () => {
    askWindow.webContents.send('load-ask', data || {});
  });
  askWindow.on('closed', () => { askWindow = null; });
});
ipcMain.on('ask-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('ask-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('ask-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// ── AUTO-UPDATER ──────────────────────────────────────────────────────────────
autoUpdater.on('update-available', () => mainWindow?.webContents.send('update-available'));
autoUpdater.on('update-downloaded', (info) => {
  updateDownloaded = true;
  // Niente quitAndInstall a tempo: l'utente puo' essere a meta' di una
  // risposta. electron-updater installa da solo alla prossima chiusura
  // (autoInstallOnAppQuit); qui si avvisa e basta.
  mainWindow?.webContents.send('update-downloaded', { version: info?.version });
  if (Notification.isSupported()) {
    new Notification({
      title: 'GigaMail',
      body: mt('update_ready', { version: info?.version || '' }),
      silent: true,
    }).show();
  }
});
autoUpdater.on('error', (err) => console.error('[UPDATER]', err.message));
