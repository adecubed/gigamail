/**
 * calendar_notifier.js — Notifiche appuntamenti 20 minuti prima.
 * Importato da main.js e agganciato al polling esistente.
 */

'use strict';

const { Notification } = require('electron');
const http = require('http');

const API_BASE       = `http://127.0.0.1:${parseInt(process.env.ADE_CONSOLE_PORT || '8002', 10)}`;
const NOTIFY_MINUTES = 20;          // minuti prima dell'appuntamento
const WINDOW_MINUTES = 2;           // finestra tolleranza (±1 minuto)
const CHECK_DAYS     = 1;           // quanti giorni di eventi caricare

// Set degli event ID già notificati — resettato ogni 24h
let _notifiedIds = new Set();
let _lastReset   = Date.now();

function _resetIfNeeded() {
  if (Date.now() - _lastReset > 24 * 60 * 60 * 1000) {
    _notifiedIds.clear();
    _lastReset = Date.now();
  }
}

function _apiGet(path) {
  return new Promise((resolve, reject) => {
    http.get(`${API_BASE}${path}`, (res) => {
      let raw = '';
      res.on('data', chunk => raw += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(raw)); }
        catch(e) { reject(e); }
      });
    }).on('error', reject);
  });
}

function _fmtTime(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

/**
 * Controlla gli eventi imminenti e spara notifiche.
 * Chiamare ogni minuto dal poller di main.js.
 * @param {BrowserWindow|null} mainWindow — per il click sulla notifica
 */
async function checkCalendarNotifications(mainWindow) {
  _resetIfNeeded();

  let events;
  try {
    events = await _apiGet(`/calendar?days=${CHECK_DAYS}`);
  } catch(e) {
    // Server non raggiungibile o timeout — silenzioso
    return;
  }

  if (!Array.isArray(events)) return;

  const now = Date.now();
  const targetMs = NOTIFY_MINUTES * 60 * 1000;
  const windowMs = WINDOW_MINUTES  * 60 * 1000;

  for (const ev of events) {
    const id      = ev.id || ev.uid || '';
    const startRaw = ev.start?.dateTime || ev.start?.date || '';
    if (!startRaw || !id) continue;

    // Già notificato
    if (_notifiedIds.has(id)) continue;

    const startMs  = new Date(startRaw).getTime();
    const diffMs   = startMs - now;

    // Dentro la finestra: tra 19 e 21 minuti da adesso
    if (diffMs >= (targetMs - windowMs) && diffMs <= (targetMs + windowMs)) {
      _notifiedIds.add(id);

      if (!Notification.isSupported()) continue;

      const title   = ev.subject || ev.title || 'Appuntamento';
      const timeStr = _fmtTime(startRaw);
      const loc     = ev.location
        ? (typeof ev.location === 'object' ? ev.location.displayName : ev.location)
        : '';

      const body = loc
        ? `Alle ${timeStr} — ${loc}`
        : `Alle ${timeStr}`;

      const notif = new Notification({
        title: `📅 ${title}`,
        body,
        silent: false,
      });

      notif.on('click', () => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.focus();
          // Apre la finestra calendario se disponibile
          mainWindow.webContents.send('open-calendar');
        }
      });

      notif.show();
      console.log(`[CAL NOTIF] "${title}" alle ${timeStr} — notifica inviata`);
    }
  }
}

module.exports = { checkCalendarNotifications };
