// renderer_calendar.js — calendario nella finestra principale: lista eventi,
// popup rapido, editor. Estratto da renderer.js (stesso scope globale:
// selectedEventId resta dichiarato la'). Le parti pure stanno in
// window.CalendarView, coperte da tests/calendar_view.test.js.

const CalendarView = (() => {
  /** Note dell'evento come testo: via i tag, spazi compressi (poi esc()). */
  function notesText(event) {
    const notes = event.body?.content || event.bodyPreview || '';
    return String(notes).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function attendeesText(event) {
    return (event.attendees || []).map(a => a.emailAddress?.address).filter(Boolean).join(', ');
  }

  function eventItemHtml(event) {
    const start = fmtDate(event.start?.dateTime);
    const loc   = event.location?.displayName || '';
    return `
      <div class="event-item" data-id="${esc(event.id)}">
        <div class="event-subject">${esc(event.subject || '(senza titolo)')}</div>
        <div class="event-time">${esc(start)}</div>
        ${loc ? `<div class="event-location">📍 ${esc(loc)}</div>` : ''}
      </div>`;
  }

  /** Contenuto del popup rapido: .modal con header/body/footer della console. */
  function eventPopupHtml(event) {
    const start = fmtDateTime(event.start?.dateTime);
    const end   = fmtDateTime(event.end?.dateTime);
    const loc   = event.location?.displayName || '';
    const notes = notesText(event);
    const attendees = attendeesText(event);
    return `
    <div class="modal" style="max-width:440px">
      <div class="modal-hdr">
        <span class="modal-title">${esc(event.subject || '(senza titolo)')}</span>
        <button class="icon-btn" data-act="close" title="${T('close','Chiudi')}">✕</button>
      </div>
      <div class="modal-body">
        <div class="ob-muted">🕐 ${esc(start)}${end ? ' → ' + esc(end) : ''}</div>
        ${loc ? `<div class="ob-muted">📍 ${esc(loc)}</div>` : ''}
        ${attendees ? `<div class="ob-muted">👥 ${esc(attendees)}</div>` : ''}
        ${notes ? `<div class="ob-p" style="max-height:160px;overflow-y:auto">${esc(notes)}</div>` : ''}
      </div>
      <div class="modal-ftr">
        <span class="ob-spacer"></span>
        <button class="chip-btn" data-act="close">${T('close_upper','CHIUDI')}</button>
        <button class="compose-btn ob-cta-inline" data-act="edit">✏ ${T('cal_edit','MODIFICA')}</button>
      </div>
    </div>`;
  }

  return { notesText, attendeesText, eventItemHtml, eventPopupHtml };
})();
if (typeof window !== 'undefined') window.CalendarView = CalendarView;


async function loadEvents() {
  const days = parseInt(byId('calDays')?.value || '7', 10);
  try {
    const events = await api.getEvents(days);
    renderEvents(events);
    setText('statEvents', Array.isArray(events) ? events.length : 0);
  } catch (e) { console.error('loadEvents:', e); }
}

function renderEvents(events) {
  const list = byId('eventsList');
  if (!list) return;
  if (!Array.isArray(events) || events.length === 0) {
    list.innerHTML = '<div class="list-empty">'+T('no_event_period','Nessun evento nel periodo.')+'</div>';
    return;
  }
  list.innerHTML = events.map(event => CalendarView.eventItemHtml(event)).join('');
  list.querySelectorAll('.event-item').forEach((el, i) => {
    el.addEventListener('click', () => { if (events[i]) selectEvent(events[i]); });
  });
}

function selectEvent(event) {
  selectedEventId = event.id;
  document.querySelectorAll('.event-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.id === event.id);
  });
  _showEventPopup(event);
}

function _showEventPopup(event) {
  document.getElementById('eventQuickPopup')?.remove();
  // Stesso .overlay > .modal delle altre finestre della console (prima era
  // un overlay costruito a mano con una palette sua e var(--mono) inesistente).
  const popup = document.createElement('div');
  popup.id = 'eventQuickPopup';
  popup.className = 'overlay';
  popup.innerHTML = CalendarView.eventPopupHtml(event);
  document.body.appendChild(popup);

  const close = () => popup.remove();
  popup.addEventListener('mousedown', e => { if (e.target === popup) close(); });
  popup.querySelectorAll('[data-act="close"]').forEach(b => b.addEventListener('click', close));
  popup.querySelector('[data-act="edit"]')?.addEventListener('click', () => {
    close();
    _openEventEditor(event);
  });
}

function _openEventEditor(event) {
  if (byId('eventId'))        byId('eventId').value        = event.id || '';
  if (byId('eventSubject'))   byId('eventSubject').value   = event.subject || '';
  if (byId('eventStart'))     byId('eventStart').value     = fmtDateTime(event.start?.dateTime);
  if (byId('eventEnd'))       byId('eventEnd').value       = fmtDateTime(event.end?.dateTime);
  if (byId('eventLocation'))  byId('eventLocation').value  = event.location?.displayName || '';
  if (byId('eventBody'))      byId('eventBody').value      = event.body?.content || event.bodyPreview || '';
  if (byId('eventAttendees')) byId('eventAttendees').value =
    (event.attendees || []).map(a => a.emailAddress?.address).filter(Boolean).join(', ');
  byId('btnDeleteEvent')?.classList.remove('hidden');
  // Scrolla al form evento
  byId('eventSubject')?.scrollIntoView({behavior:'smooth', block:'center'});
  byId('eventSubject')?.focus();
}

// ── Binding della vista calendario e dell'editor evento ──────────────────────
function bindCalendarEvents() {
  // Calendario → finestra nativa
  on('btnShowCalendar', 'click', () => {
    window.electronAPI?.openCalendarWindow?.();
  });
  on('calDays',       'change', loadEvents);
  on('btnRefreshCal', 'click',  loadEvents);

  on('btnClearEvent', 'click', () => {
    selectedEventId = null;
    ['eventId','eventSubject','eventStart','eventEnd','eventLocation','eventAttendees','eventBody']
      .forEach(id => { if (byId(id)) byId(id).value = ''; });
    byId('btnDeleteEvent')?.classList.add('hidden');
    setText('eventStatus', '');
  });

  on('btnSaveEvent', 'click', async () => {
    const id        = byId('eventId')?.value || '';
    const subject   = byId('eventSubject')?.value.trim() || '';
    const start     = byId('eventStart')?.value || '';
    const end       = byId('eventEnd')?.value || '';
    const location  = byId('eventLocation')?.value || '';
    const body      = byId('eventBody')?.value || '';
    const attendees = (byId('eventAttendees')?.value || '').split(',').map(s => s.trim()).filter(Boolean);
    if (!subject || !start || !end) { setText('eventStatus', '✕ Compila titolo, inizio e fine'); return; }
    try {
      if (id) { await api.updateEvent(id, {subject, start, end, location, body, attendees}); setText('eventStatus', '✓ Evento aggiornato'); }
      else    { await api.createEvent({subject, start, end, location, body, attendees}); setText('eventStatus', '✓ Evento creato'); }
      await loadEvents();
    } catch (e) { setText('eventStatus', `✕ Errore: ${e}`); }
  });

  on('btnDeleteEvent', 'click', async () => {
    const id = byId('eventId')?.value || '';
    if (!id || !confirm('Eliminare questo evento?')) return;
    try {
      const r = await fetch(`http://127.0.0.1:8002/calendar/${encodeURIComponent(id)}`, { method: 'DELETE' });
      let data = {};
      try { data = await r.json(); } catch {}
      if (!r.ok || data.success === false) {
        const msg = data.error || `HTTP ${r.status}`;
        console.error('[CALENDAR DELETE] fallita:', id, data);
        setText('eventStatus', `✕ Eliminazione fallita: ${msg}`);
        return;
      }
      setText('eventStatus', '✓ Evento eliminato');
      byId('btnClearEvent')?.click();
      await loadEvents();
    }
    catch (e) { setText('eventStatus', `✕ ${e}`); }
  });

  on('btnSpeakToday', 'click', async () => {
    try { const audio = new Audio(api.getCalendarTtsUrl()); await audio.play(); }
    catch (e) { showToast(`Errore TTS: ${e}`); }
  });
}
