// calendar_window_page.js — the script of calendar_window.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';

let _activeAccountId = null;

async function _loadActiveAccount() {
  try {
    const r = await fetch(`${API}/calendar/primary`);
    const data = await r.json();
    _activeAccountId = data.account_id || null;
  } catch(e) {}
}
_loadActiveAccount();

window.addEventListener('error', (e) => {
  console.error('[CAL ERROR]', e.message, e.filename, e.lineno);
  const list = document.getElementById('upcomingList');
  // T is declared further down: a handler that runs before it must not touch it.
  const tr = (k, it) => (window.i18n && window.i18n.t) ? window.i18n.t(k, it) : it;
  if (list && list.innerHTML.includes(tr('loading', 'Caricamento…'))) {
    list.innerHTML = `<div class="loading" style="color:#dc2626">${tr('win_js_error', 'Errore JS')}: ${e.message} (${tr('win_line', 'linea')} ${e.lineno})</div>`;
  }
});

let _events = [];
let _currentYear  = new Date().getFullYear();
let _currentMonth = new Date().getMonth(); // 0-based

// Nomi di giorni e mesi nella lingua della UI (Intl), settimana da lunedi'.
const LOCALE = () => (window.i18n && window.i18n.locale) || 'it-IT';
const T = (k, it) => (window.i18n && window.i18n.t) ? window.i18n.t(k, it) : it;
function dayNames() {
  const f = new Intl.DateTimeFormat(LOCALE(), { weekday: 'short' });
  return [1, 2, 3, 4, 5, 6, 7].map(d => {
    const n = f.format(new Date(2024, 0, d)); // 1 gen 2024 = lunedi'
    return n.charAt(0).toUpperCase() + n.slice(1).replace(/\.$/, '');
  });
}
function monthName(m, y) {
  const n = new Intl.DateTimeFormat(LOCALE(), { month: 'long' }).format(new Date(y, m, 1));
  return n.charAt(0).toUpperCase() + n.slice(1);
}

async function loadEvents() {
  const list = document.getElementById('upcomingList');
  if (list) list.innerHTML = `<div class="loading">${T('loading','Caricamento…')}</div>`;
  try {
    const r = await fetch(`${API}/calendar?days=60`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    _events = Array.isArray(data) ? data : (data.value || data.items || []);
  } catch(err) {
    console.error('[CAL] loadEvents error:', err);
    _events = [];
    if (list) list.innerHTML = `<div class="loading">${T('error','Errore')}: ${esc(err.message)}</div>`;
  }
  renderUpcoming();
  renderCalendar();
}

function fmtDateTime(dt) {
  if (!dt) return '';
  try {
    const d = new Date(dt);
    return d.toLocaleDateString(LOCALE(),{day:'2-digit',month:'short'}) + ' ' +
           d.toLocaleTimeString(LOCALE(),{hour:'2-digit',minute:'2-digit'});
  } catch { return dt; }
}

function fmtDateLocal(dt) {
  if (!dt) return '';
  try {
    const raw = String(dt);
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(raw) && !/[zZ]|[+-]\d{2}:\d{2}$/.test(raw)) {
      return raw.slice(0, 16);
    }
    const d = new Date(raw);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return '';
  }
}

// ── GIORNO INTERO ──
// Graph e Google mandano la fine esclusiva (mezzanotte del giorno dopo):
// in griglia e nel modulo si mostra l'ultimo giorno compreso.
const pad2 = n => String(n).padStart(2, '0');
function isoDay(d) { return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`; }
function evDay(node) { return String(node?.dateTime || node?.date || '').slice(0, 10); }
function allDayLastDay(ev) {
  const first = evDay(ev.start);
  const end = evDay(ev.end);
  if (!end) return first;
  const d = new Date(end + 'T12:00:00');
  d.setDate(d.getDate() - 1);
  const last = isoDay(d);
  return last < first ? first : last;
}
function fmtEventWhen(ev) {
  if (!ev.isAllDay) return fmtDateTime(ev.start?.dateTime || ev.start?.date || '');
  const fmt = day => new Date(day + 'T12:00:00').toLocaleDateString(LOCALE(), { day:'2-digit', month:'short' });
  const first = evDay(ev.start), last = allDayLastDay(ev);
  return (last !== first ? `${fmt(first)} – ${fmt(last)}` : fmt(first)) + ' · ' + T('cal_all_day', 'Tutto il giorno');
}

// ── PROSSIMI APPUNTAMENTI con filtro ──
let _upcomingFilter = 'all'; // 'all' | 'today' | 'week'

function renderUpcoming() {
  const now   = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const todayEnd   = new Date(todayStart.getTime() + 24*60*60*1000);
  const weekStart  = todayStart;
  const weekEnd    = new Date(todayStart.getTime() + 7*24*60*60*1000);

  let filtered = _events.filter(e => {
    if (e.isAllDay) {
      const from = new Date(evDay(e.start) + 'T00:00:00');
      const to = new Date(allDayLastDay(e) + 'T23:59:59');
      if (_upcomingFilter === 'today') return from < todayEnd && to >= todayStart;
      if (_upcomingFilter === 'week')  return from < weekEnd  && to >= weekStart;
      return to >= todayStart;
    }
    const dt = new Date(e.start?.dateTime || e.start?.date || 0);
    if (_upcomingFilter === 'today') return dt >= todayStart && dt < todayEnd;
    if (_upcomingFilter === 'week')  return dt >= weekStart  && dt < weekEnd;
    return dt >= todayStart; // 'all': da inizio oggi in poi (oggi + futuri, niente passato)
  });

  filtered = filtered
    .sort((a,b) => new Date(a.start?.dateTime||a.start?.date) - new Date(b.start?.dateTime||b.start?.date))
    .slice(0, _upcomingFilter === 'all' ? 8 : 50);

  const list = document.getElementById('upcomingList');
  if (!filtered.length) {
    list.innerHTML = `<div class="loading">${window.i18n?window.i18n.t("no_upcoming"):"Nessun appuntamento in arrivo"}</div>`;
    return;
  }
  list.innerHTML = filtered.map(e => {
    const where = (typeof e.location === 'object' ? e.location?.displayName : e.location) || '';
    const loc = where ? `${(typeof GMIcons !== 'undefined' ? GMIcons.svg('map', 12) : '')} ${where}` : '';
    return `<div class="upcoming-item" data-id="${esc(e.id||'')}">
      <div class="upcoming-dot"></div>
      <div class="upcoming-info">
        <div class="upcoming-title">${esc(e.subject||e.title||T('win_untitled', '(senza titolo)'))}</div>
        <div class="upcoming-meta">${esc(loc)}</div>
      </div>
      <div class="upcoming-date">${esc(fmtEventWhen(e))}</div>
    </div>`;
  }).join('');

  list.querySelectorAll('.upcoming-item').forEach(el => {
    el.addEventListener('click', () => {
      const ev = _events.find(e => e.id === el.dataset.id);
      if (ev) openEventModal(ev);
    });
    el.addEventListener('contextmenu', (e) => {
      e.preventDefault(); e.stopPropagation();
      showCtxMenu(e.clientX, e.clientY, el.dataset.id);
    });
  });
}

// ── GRIGLIA CALENDARIO ──
function renderCalendar() {
  const label = document.getElementById('calMonthLabel');
  label.textContent = `${monthName(_currentMonth, _currentYear)} ${_currentYear}`;

  const grid = document.getElementById('calGrid');
  grid.innerHTML = '';

  dayNames().forEach(d => {
    const h = document.createElement('div');
    h.className = 'cal-day-header';
    h.textContent = d;
    grid.appendChild(h);
  });

  const firstDay = new Date(_currentYear, _currentMonth, 1);
  let startDow = firstDay.getDay();
  startDow = startDow === 0 ? 6 : startDow - 1;

  const daysInMonth = new Date(_currentYear, _currentMonth + 1, 0).getDate();
  const daysInPrev  = new Date(_currentYear, _currentMonth, 0).getDate();
  const today = new Date();

  for (let i = 0; i < startDow; i++) {
    const day = daysInPrev - startDow + i + 1;
    grid.appendChild(makeCell(day, _currentMonth - 1, true));
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = d === today.getDate() && _currentMonth === today.getMonth() && _currentYear === today.getFullYear();
    grid.appendChild(makeCell(d, _currentMonth, false, isToday));
  }

  const totalCells = startDow + daysInMonth;
  const remaining  = totalCells % 7 === 0 ? 0 : 7 - (totalCells % 7);
  for (let d = 1; d <= remaining; d++) {
    grid.appendChild(makeCell(d, _currentMonth + 1, true));
  }
}

function makeCell(day, month, otherMonth, isToday = false) {
  const realMonth = ((month % 12) + 12) % 12;
  const realYear  = _currentYear + Math.floor(month / 12);
  const cellDate  = new Date(realYear, realMonth, day);

  const key = isoDay(cellDate);
  const dayEvents = _events.filter(e => {
    if (e.isAllDay) return key >= evDay(e.start) && key <= allDayLastDay(e);
    const dt = new Date(e.start?.dateTime || e.start?.date || 0);
    return dt.getFullYear() === realYear && dt.getMonth() === realMonth && dt.getDate() === day;
  }).sort((a, b) => (b.isAllDay ? 1 : 0) - (a.isAllDay ? 1 : 0));

  const cell = document.createElement('div');
  cell.className = 'cal-cell' + (otherMonth ? ' other-month' : '') + (isToday ? ' today' : '');

  const numEl = document.createElement('div');
  numEl.className = 'cal-day-num';
  numEl.textContent = day;
  cell.appendChild(numEl);

  dayEvents.slice(0, 3).forEach(ev => {
    const chip = document.createElement('div');
    chip.className = 'cal-event-chip' + (ev.isAllDay ? ' all-day' : '');
    const time = (!ev.isAllDay && ev.start?.dateTime) ? new Date(ev.start.dateTime).toLocaleTimeString(LOCALE(),{hour:'2-digit',minute:'2-digit'}) : '';
    chip.textContent = (time ? time + ' ' : '') + (ev.subject||ev.title||T('cal_event','Evento'));
    chip.addEventListener('click', (e) => { e.stopPropagation(); openEventModal(ev); });
    chip.addEventListener('contextmenu', (e) => {
      e.preventDefault(); e.stopPropagation();
      showCtxMenu(e.clientX, e.clientY, ev.id);
    });
    cell.appendChild(chip);
  });
  if (dayEvents.length > 3) {
    const more = document.createElement('div');
    more.className = 'cal-more';
    more.textContent = T('win_more_events', '+{n} altri').replace('{n}', dayEvents.length - 3);
    cell.appendChild(more);
  }

  cell.addEventListener('click', () => {
    const dt = new Date(realYear, realMonth, day, 9, 0);
    openEventModal(null, dt);
  });

  return cell;
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── ATTENDEES ──
let _attendees = [];

function renderAttendees() {
  const list = document.getElementById('eventAttendeesList');
  if (!list) return;
  if (!_attendees.length) { list.innerHTML = ''; return; }
  // Niente JS inline con dati dentro: l'indirizzo vive in un data-attribute
  // e il click e' legato qui.
  list.innerHTML = _attendees.map(email =>
    `<div class="attendee-chip">
      ${esc(email)}
      <button class="attendee-chip-x" data-email="${esc(email)}" type="button">✕</button>
    </div>`
  ).join('');
  list.querySelectorAll('.attendee-chip-x').forEach(b =>
    b.addEventListener('click', () => window.removeAttendee(b.dataset.email)));
}

window.removeAttendee = (email) => {
  _attendees = _attendees.filter(e => e !== email);
  renderAttendees();
};

function addAttendeeFromInput() {
  const input = document.getElementById('eventAttendeesInput');
  const val = (input?.value || '').trim().toLowerCase();
  if (!val || !val.includes('@')) return;
  if (!_attendees.includes(val)) {
    _attendees.push(val);
    renderAttendees();
  }
  input.value = '';
  input.focus();
}

function setAllDay(on) {
  document.getElementById('eventAllDay').checked = on;
  const s = document.getElementById('eventStart');
  const e = document.getElementById('eventEnd');
  const sv = s.value, ev = e.value;
  if (on) {
    s.type = 'date'; e.type = 'date';
    s.value = sv.slice(0, 10);
    e.value = (ev || sv).slice(0, 10);
  } else {
    s.type = 'datetime-local'; e.type = 'datetime-local';
    s.value = sv ? (sv.length > 10 ? sv : sv + 'T09:00') : '';
    e.value = ev ? (ev.length > 10 ? ev : ev + 'T10:00') : '';
  }
}
document.getElementById('eventAllDay')?.addEventListener('change', (ev) => setAllDay(ev.target.checked));

document.getElementById('eventStart')?.addEventListener('change', () => {
  const start = document.getElementById('eventStart').value;
  if (!start) return;
  if (document.getElementById('eventAllDay').checked) {
    const end = document.getElementById('eventEnd');
    if (!end.value || end.value < start) end.value = start;
    return;
  }
  const startDt = new Date(start);
  const endDt = new Date(startDt.getTime() + 60 * 60 * 1000);
  const pad = n => String(n).padStart(2, '0');
  const endStr = `${endDt.getFullYear()}-${pad(endDt.getMonth()+1)}-${pad(endDt.getDate())}T${pad(endDt.getHours())}:${pad(endDt.getMinutes())}`;
  document.getElementById('eventEnd').value = endStr;
});
document.getElementById('btnAddAttendee')?.addEventListener('click', addAttendeeFromInput);
document.getElementById('eventAttendeesInput')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    addAttendeeFromInput();
  }
});

// ── MODAL EVENTO ──
function openEventModal(ev = null, defaultDate = null) {
  const modal = document.getElementById('eventModal');
  document.getElementById('eventModalTitle').textContent = ev ? (window.i18n?window.i18n.t('cal_edit_event'):'Modifica evento') : (window.i18n?window.i18n.t('cal_new_event'):'Nuovo evento');
  document.getElementById('eventId').value        = ev?.id || '';
  document.getElementById('eventSubject').value   = ev?.subject || ev?.title || '';
  document.getElementById('eventLocation').value  = (typeof ev?.location === 'object' ? ev?.location?.displayName : ev?.location) || '';
  const _rawBody = ev?.body?.content || ev?.notes || '';
  document.getElementById('eventBody').value = _rawBody.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  document.getElementById('btnDeleteEvent').style.display = ev?.id ? 'block' : 'none';

  setAllDay(!!ev?.isAllDay);
  if (ev?.isAllDay) {
    document.getElementById('eventStart').value = evDay(ev.start);
    document.getElementById('eventEnd').value   = allDayLastDay(ev);
  } else if (ev) {
    document.getElementById('eventStart').value = fmtDateLocal(ev.start?.dateTime || ev.start?.date);
    document.getElementById('eventEnd').value   = fmtDateLocal(ev.end?.dateTime   || ev.end?.date);
  } else if (defaultDate) {
    const end = new Date(defaultDate.getTime() + 60*60*1000);
    document.getElementById('eventStart').value = fmtDateLocal(defaultDate.toISOString());
    document.getElementById('eventEnd').value   = fmtDateLocal(end.toISOString());
  } else {
    document.getElementById('eventStart').value = '';
    document.getElementById('eventEnd').value   = '';
  }

  // Carica attendees esistenti
  _attendees = (ev?.attendees || []).map(a => {
    if (typeof a === 'string') return a;
    return a?.emailAddress?.address || a?.email || '';
  }).filter(Boolean);
  renderAttendees();

  modal.classList.add('visible');
  document.getElementById('eventSubject').focus();
}

function closeEventModal() {
  document.getElementById('eventModal').classList.remove('visible');
  _attendees = [];
  renderAttendees();
}

document.getElementById('btnModalClose')?.addEventListener('click', closeEventModal);
document.getElementById('btnCancelEvent')?.addEventListener('click', closeEventModal);

document.getElementById('btnSaveEvent')?.addEventListener('click', async () => {
  const id       = document.getElementById('eventId').value;
  const subject  = document.getElementById('eventSubject').value.trim();
  const start    = document.getElementById('eventStart').value;
  const end      = document.getElementById('eventEnd').value;
  const location = document.getElementById('eventLocation').value.trim();
  const body     = document.getElementById('eventBody').value.trim();

  if (!subject) { alert(T('win_enter_title', 'Inserisci il titolo')); return; }
  if (!start)   { alert(T('win_enter_start', 'Inserisci la data di inizio')); return; }

  function toLocalISO(dtStr) {
    if (!dtStr) return '';
    const clean = dtStr.replace(/Z$/, '').replace(/[+-]\d{2}:\d{2}$/, '');
    return clean.length === 16 ? clean + ':00' : clean;
  }

  const allDay = document.getElementById('eventAllDay').checked;
  const payload = {
    subject,
    // giorno intero: primo e ultimo giorno, compresi; il backend converte
    start:     allDay ? start : toLocalISO(start),
    end:       allDay ? (end || start) : toLocalISO(end || start),
    all_day:   allDay,
    location:  location || '',
    body:      body || '',
    attendees: _attendees,
  };
  console.log('[CAL] Payload:', JSON.stringify(payload));

  try {
    if (id) {
      const url = `${API}/calendar/${encodeURIComponent(id)}` + (_activeAccountId ? `?account_id=${_activeAccountId}` : '');
      const r = await fetch(url, {
        method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    } else {
      const urlPost = `${API}/calendar` + (_activeAccountId ? `?account_id=${_activeAccountId}` : '');
      const r = await fetch(urlPost, {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    }
    closeEventModal();
    await loadEvents();
  } catch(err) { alert(T('win_save_error', 'Errore salvataggio') + ': ' + err.message); }
});

document.getElementById('btnDeleteEvent')?.addEventListener('click', async () => {
  const id = document.getElementById('eventId').value;
  if (!id || !(await GMDialog.confirm(T('win_event_delete_confirm', 'Eliminare questo evento?'), { danger: true }))) return;
  try {
    const urlDel = `${API}/calendar/${encodeURIComponent(id)}` + (_activeAccountId ? `?account_id=${_activeAccountId}` : '');
    await fetch(urlDel, { method:'DELETE' });
    closeEventModal();
    await loadEvents();
  } catch(err) { alert(T('error', 'Errore') + ': ' + err.message); }
});

// ── FILTRI UPCOMING ──
['btnFilterAll','btnFilterToday','btnFilterWeek'].forEach(id => {
  document.getElementById(id)?.addEventListener('click', () => {
    _upcomingFilter = id === 'btnFilterAll' ? 'all' : id === 'btnFilterToday' ? 'today' : 'week';
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
    if (_upcomingFilter !== 'all') {
      _currentYear  = new Date().getFullYear();
      _currentMonth = new Date().getMonth();
      renderCalendar();
    }
    renderUpcoming();
  });
});

// ── NAVIGAZIONE ──
document.getElementById('btnPrevMonth')?.addEventListener('click', () => {
  _currentMonth--;
  if (_currentMonth < 0) { _currentMonth = 11; _currentYear--; }
  renderCalendar();
});
document.getElementById('btnNextMonth')?.addEventListener('click', () => {
  _currentMonth++;
  if (_currentMonth > 11) { _currentMonth = 0; _currentYear++; }
  renderCalendar();
});
document.getElementById('btnToday')?.addEventListener('click', () => {
  _currentYear  = new Date().getFullYear();
  _currentMonth = new Date().getMonth();
  renderCalendar();
});
document.getElementById('btnAddEvent')?.addEventListener('click', () => openEventModal());
document.getElementById('btnRefreshCal')?.addEventListener('click', () => loadEvents());
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
    e.preventDefault();
    loadEvents();
  }
});

// ── WINDOW CONTROLS ──
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btnClose')?.addEventListener('click',   () => window.calendarWindowAPI?.close());
  document.getElementById('btnMin')?.addEventListener('click',     () => window.calendarWindowAPI?.minimize());
  document.getElementById('btnMax')?.addEventListener('click',     () => window.calendarWindowAPI?.maximize());
  loadEvents();
});

// ── MENU CONTESTO (tasto destro su un evento) ──
let _ctxEventId = null;

function showCtxMenu(x, y, eventId) {
  _ctxEventId = eventId;
  const menu = document.getElementById('ctxMenu');
  menu.classList.add('visible');
  // Posiziona evitando di uscire dallo schermo
  const rect = menu.getBoundingClientRect();
  const px = (x + rect.width  > window.innerWidth)  ? x - rect.width  : x;
  const py = (y + rect.height > window.innerHeight) ? y - rect.height : y;
  menu.style.left = Math.max(4, px) + 'px';
  menu.style.top  = Math.max(4, py) + 'px';
}

function hideCtxMenu() {
  document.getElementById('ctxMenu').classList.remove('visible');
  _ctxEventId = null;
}

async function deleteEventById(id) {
  if (!id) return;
  if (!(await GMDialog.confirm(T('win_event_delete_confirm', 'Eliminare questo evento?'), { danger: true }))) return;
  try {
    const urlDel = `${API}/calendar/${encodeURIComponent(id)}` + (_activeAccountId ? `?account_id=${_activeAccountId}` : '');
    await fetch(urlDel, { method:'DELETE' });
    await loadEvents();
  } catch(err) { alert(T('win_delete_error', 'Errore eliminazione') + ': ' + err.message); }
}

function followUpEvent(ev) {
  if (!ev) return;
  // Nuovo evento a +7 giorni rispetto all'originale, stessa ora
  const baseStr = ev.start?.dateTime || ev.start?.date;
  const base = baseStr ? new Date(baseStr) : new Date();
  const followDate = new Date(base.getTime() + 7*24*60*60*1000);
  openEventModal(null, followDate);
  // Pre-compila titolo e partecipanti
  const subj = ev.subject || ev.title || '';
  document.getElementById('eventSubject').value = subj.startsWith('Follow up') ? subj : `Follow up: ${subj}`;
  _attendees = (ev.attendees || []).map(a =>
    typeof a === 'string' ? a : (a?.emailAddress?.address || a?.email || '')
  ).filter(Boolean);
  renderAttendees();
}

document.getElementById('ctxMenu').addEventListener('click', (e) => {
  const item = e.target.closest('.ctx-item');
  if (!item) return;
  const action = item.dataset.action;
  const id = _ctxEventId;                          // cattura prima di nascondere
  const ev = _events.find(x => x.id === id);
  hideCtxMenu();
  if (action === 'edit')          { if (ev) openEventModal(ev); }
  else if (action === 'delete')   { deleteEventById(id); }
  else if (action === 'followup') { if (ev) followUpEvent(ev); }
});

// chiudi il menu su click fuori / scroll / esc
document.addEventListener('click', (e) => {
  if (!e.target.closest('#ctxMenu')) hideCtxMenu();
});
document.addEventListener('scroll', hideCtxMenu, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideCtxMenu(); });
