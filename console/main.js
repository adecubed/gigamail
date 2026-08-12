const { app, BrowserWindow, session, shell, Notification, ipcMain, Menu, dialog } = require('electron');
const path = require('path');
const { autoUpdater } = require('electron-updater');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const Database = require('better-sqlite3');

let mainWindow;
let serverProcess;
let notifPoller = null;
let lastUnreadCounts = {};
let lastFollowupCheck = 0;

const API = 'http://127.0.0.1:8002';

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
      template.push({ role: 'cut', enabled: editFlags.canCut, label: 'Taglia' });
    }
    template.push({ role: 'copy', enabled: editFlags.canCopy || hasSelection, label: 'Copia' });
    if (isEditable) {
      template.push({ role: 'paste', enabled: editFlags.canPaste, label: 'Incolla' });
      template.push({ type: 'separator' });
      template.push({ role: 'selectAll', label: 'Seleziona tutto' });
    }

    if (template.length) {
      const menu = Menu.buildFromTemplate(template);
      menu.popup({ window: BrowserWindow.fromWebContents(contents) });
    }
  });
});

// ── FOLLOWUP DB ───────────────────────────────────────────────────────────────
const FOLLOWUP_DB_PATH = path.join(
  process.env.APPDATA || require('os').homedir(),
  'ADE', 'mail', 'followups.db'
);

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
    const req = http.get(`${API}${urlPath}`, { timeout: 8000 }, (res) => {
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
    title: `ADE Mail — ${accountName}`,
    body: `${count} nuov${count === 1 ? 'a mail' : 'e mail'}`,
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
        title: 'Follow-up necessario',
        body: `${item.subject || 'Mail senza oggetto'} → ${item.to_addr || ''}`,
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

function startPythonServer() {
  const resourcesPath = getResourcesPath();
  const pythonPath = app.isPackaged
    ? path.join(resourcesPath, 'python', 'python.exe')
    : 'python';
  const serverDir = app.isPackaged
    ? path.join(resourcesPath, 'ade_mail')
    : path.join(resourcesPath, 'ade_mail');

  const req = http.get('http://127.0.0.1:8002/health', (res) => {
    console.log('[ADE MAIL] Server già attivo su porta 8002');
  });
req.on('error', () => {
    console.log('[ADE MAIL] Avvio server Python...');
    serverProcess = spawn(pythonPath, [
      'server.py',
    ], {
      cwd: serverDir,
      windowsHide: true,
      detached: true,   // il backend sopravvive alla chiusura dell'app
      env: { ...process.env, PYTHONPATH: serverDir },
    });
    serverProcess.stdout?.on('data', (d) => console.log('[SERVER]', d.toString().trim()));
    serverProcess.stderr?.on('data', (d) => console.error('[SERVER ERR]', d.toString().trim()));
    serverProcess.on('exit', (code) => console.log('[SERVER] exit', code));
    serverProcess.unref(); // non tenere vivo Electron per via del figlio
  });
  req.setTimeout(1000);
  req.end();
}

// ── WINDOW ────────────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    frame: false,
    backgroundColor: '#E8EEF4',
    title: 'ADE Mail',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index_v2.html'));

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http') || url.startsWith('mailto')) shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith('file://')) return;
    if (url.startsWith('http://localhost') || url.startsWith('https://localhost')) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    shell.openExternal(url);
  });

  if (app.isPackaged) {
    setTimeout(() => autoUpdater.checkForUpdatesAndNotify(), 3000);
  }
}

// ── APP ───────────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  startPythonServer();

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(true);
  });

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src * 'unsafe-inline' 'unsafe-eval' data: blob:; img-src * data: blob: cid:",
        ],
      },
    });
  });

  createWindow();
  startPolling();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopPolling();
  // Il backend NON viene killato: resta in background cosi' il prossimo
  // avvio dell'app e' istantaneo (il check /health pre-spawn lo riusa).
  if (process.platform !== 'darwin') app.quit();
});

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
    title: 'ADE Mail',
    webPreferences: {
      preload: path.join(__dirname, 'preload_mail.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'mail_window.html'));

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http') || url.startsWith('mailto')) shell.openExternal(url);
    return { action: 'deny' };
  });

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
    title: 'Nuova risposta',
    webPreferences: {
      preload: path.join(__dirname, 'preload_reply.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'reply_window.html'));
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
    title: 'Nuova mail',
    webPreferences: {
      preload: path.join(__dirname, 'preload_new_mail.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'new_mail_window.html'));
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
    title: 'Nuova risposta',
    webPreferences: {
      preload: path.join(__dirname, 'preload_reply.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'reply_window.html'));
  win.webContents.once('did-finish-load', () => {
    win.webContents.send('load-reply', data);
  });
});
ipcMain.handle('mail-window-open-external', (event, url) => {
  shell.openExternal(url);
});

// ── Allegati mail: apri / salva con nome ──
const os = require('os');

ipcMain.handle('mail-attachment-open', async (_evt, { name, bytes }) => {
  try {
    const safe = (name || 'allegato').replace(/[\\/:*?"<>|]/g, '_');
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
    title: 'ADE Calendario',
    webPreferences: {
      preload: path.join(__dirname, 'preload_calendar.js'),
      contextIsolation: true, nodeIntegration: false,
      webSecurity: false,
    },
  });
  calendarWindow.loadFile(path.join(__dirname, 'calendar_window.html'));
  calendarWindow.on('closed', () => { calendarWindow = null; });
});
ipcMain.on('calendar-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('calendar-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('calendar-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// ── FINESTRA MARKETING ───────────────────────────────────────────────────────
let marketingWindow = null;
ipcMain.on('open-marketing-window', () => {
  if (marketingWindow && !marketingWindow.isDestroyed()) { marketingWindow.focus(); return; }
  marketingWindow = new BrowserWindow({
    width: 1000, height: 680, minWidth: 700, minHeight: 500,
    frame: false, transparent: true, backgroundColor: '#00000000',
    title: 'ADE Marketing',
    webPreferences: {
      preload: path.join(__dirname, 'preload_marketing.js'),
      contextIsolation: true, nodeIntegration: false,
      webSecurity: false,
    },
  });
  marketingWindow.loadFile(path.join(__dirname, 'marketing_window.html'));
  marketingWindow.on('closed', () => { marketingWindow = null; });
});
ipcMain.on('marketing-window-close',    (event) => { BrowserWindow.fromWebContents(event.sender)?.close(); });
ipcMain.on('marketing-window-minimize', (event) => { BrowserWindow.fromWebContents(event.sender)?.minimize(); });
ipcMain.on('marketing-window-maximize', (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w?.isMaximized()) w.unmaximize(); else w?.maximize();
});

// ------ ASK MAIL --------------------------------------------------------

let askWindow = null;
ipcMain.on('open-ask-window', (event, data) => {
  if (askWindow && !askWindow.isDestroyed()) { askWindow.focus(); return; }
  const main = mainWindow?.getBounds() || { x:100, y:100, width:1280, height:820 };
  askWindow = new BrowserWindow({
    width: 760, height: 720, minWidth: 480, minHeight: 500,
    x: main.x + Math.floor((main.width - 760) / 2),
    y: main.y + Math.floor((main.height - 720) / 2),
    frame: false, transparent: true, backgroundColor: '#00000000',
    title: 'Chiedi alle mail',
    webPreferences: {
      preload: path.join(__dirname, 'preload_ask.js'),
      contextIsolation: true, nodeIntegration: false,
      webSecurity: false,
    },
  });
  askWindow.loadFile(path.join(__dirname, 'ask_window.html'));
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
autoUpdater.on('update-downloaded', () => {
  mainWindow?.webContents.send('update-downloaded');
  setTimeout(() => autoUpdater.quitAndInstall(), 5000);
});
autoUpdater.on('error', (err) => console.error('[UPDATER]', err.message));
