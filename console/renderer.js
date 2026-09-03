function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key) : it; }
const api = window.ademail || {};

/** Rimuove ':uid' appiccicato al nome cartella IMAP (es. INBOX.SPAM:1 → INBOX.SPAM) */
function cleanFolder(folder) {
  if (!folder) return folder;
  return folder.includes(':') ? folder.split(':')[0] : folder;
}

let selectedMailId = null;
let selectedMailFolder = null;  // cartella della mail attualmente aperta
let selectedEventId = null;
let priorityMode = false;
let activeAccountId = null;
let currentDraft = '';
let currentInstruction = '';
let currentFolder = 'inbox';
let currentFolderLabel = 'inbox';
let autosaveSignature = '';
let pendingAttachments  = []; // [{name, data_b64, type, size}]
let replyAttachments   = []; // allegati per il box risposta
let currentReplyDefaultTo = '';
let currentReplyDefaultSubject = '';
let currentReplyCc = [];
let currentMailList    = []; // lista mail corrente per navigazione vocale
let currentMailIndex   = -1; // indice mail aperta
const mailSummaryCache = new Map();
const dismissedSuggestions = new Set();
let bootstrappedMail = false;
let mailFolderCache = [];
let folderKeywordsDirty = false;
let customFolderNewCounts = new Map();
let customFolderCountsRequestId = 0;


// ============================================================

async function checkAuth() {
  const started = performance.now();
  try {
    const status = await api.getStatus();
    const dot      = byId('authDot');
    const label    = byId('authLabel');
    const btnLogin  = byId('btnLogin');
    const btnLogout = byId('btnLogout');
    // /auth/status guarda solo il token Microsoft: un'installazione con
    // soli account IMAP e' comunque "connessa" e deve caricare gli account.
    let hasAccounts = false;
    try {
      const accs = await api.getAccounts();
      hasAccounts = Array.isArray(accs) && accs.length > 0;
    } catch (_) { /* backend non pronto: si riprova al prossimo giro */ }

    if (status.logged_in || hasAccounts) {
      if (dot)   dot.className = 'status-dot online';
      if (label) label.textContent = 'CONNESSO';
      btnLogin?.classList.add('hidden');
      btnLogout?.classList.remove('hidden');
      await loadAccounts();
      if (!bootstrappedMail) {
        await refreshCurrentFolder();
        loadEvents().catch(e => console.error('loadEvents bootstrap:', e));
        bootstrappedMail = true;
        resetMailDetail();
      }
    } else {
      if (dot)   dot.className = 'status-dot offline';
      if (label) label.textContent = 'NON CONNESSO';
      btnLogin?.classList.remove('hidden');
      btnLogout?.classList.add('hidden');
      bootstrappedMail = false;
      resetMailDetail();
    }
  } catch (e) {
    console.error('checkAuth:', e);
    setText('authLabel', 'OFFLINE');
  } finally {
    console.log(`[ADE MAIL UI TIMING] checkAuth=${Math.round(performance.now() - started)}ms`);
  }
}

// ============================================================
// TABS
// ============================================================

function bindTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(panel => {
        panel.classList.add('hidden');
        panel.classList.remove('active');
        panel.style.display = 'none';
      });
      tab.classList.add('active');
      const panel = byId(`tab-${tab.dataset.tab}`);
      if (panel) {
        panel.classList.remove('hidden');
        panel.classList.add('active');
        panel.style.display = 'flex';
      }
    });
  });
}

// ============================================================
// CALENDARIO
// ============================================================

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
  list.innerHTML = events.map(event => {
    const start = fmtDate(event.start?.dateTime);
    const loc   = event.location?.displayName || '';
    return `
      <div class="event-item" data-id="${esc(event.id)}">
        <div class="event-subject">${esc(event.subject || '(senza titolo)')}</div>
        <div class="event-time">${esc(start)}</div>
        ${loc ? `<div class="event-location">📍 ${esc(loc)}</div>` : ''}
      </div>`;
  }).join('');
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
  const existing = document.getElementById('eventQuickPopup');
  if (existing) existing.remove();

  const start = fmtDateTime(event.start?.dateTime);
  const end   = fmtDateTime(event.end?.dateTime);
  const loc   = event.location?.displayName || '';
  const notes = event.body?.content || event.bodyPreview || '';
  const notesClean = notes.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  const attendeesList = (event.attendees || [])
    .map(a => a.emailAddress?.address).filter(Boolean).join(', ');

  const popup = document.createElement('div');
  popup.id = 'eventQuickPopup';
  popup.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(26,22,20,0.35);';
  popup.innerHTML = `
    <div style="background:#FFFFFF;border:1px solid #E2DDD6;border-top:3px solid #2B5CE6;border-radius:4px;width:min(420px,92vw);box-shadow:0 8px 32px rgba(43,92,230,0.15);overflow:hidden;">
      <div style="padding:14px 18px 10px;border-bottom:1px solid #E2DDD6;background:#FAF8F5;">
        <div style="font-size:15px;font-weight:600;color:#1A1614;margin-bottom:4px;">${esc(event.subject||'')}</div>
        <div style="font-size:12px;color:#8A8280;font-family:var(--mono)">🕐 ${esc(start)}${end ? ' → ' + esc(end) : ''}</div>
        ${loc ? `<div style="font-size:12px;color:#8A8280;margin-top:2px;">📍 ${esc(loc)}</div>` : ''}
        ${attendeesList ? `<div style="font-size:12px;color:#8A8280;margin-top:2px;">👥 ${esc(attendeesList)}</div>` : ''}
      </div>
      ${notesClean ? `<div style="padding:12px 18px;font-size:13px;color:#4A4340;line-height:1.6;max-height:120px;overflow-y:auto;">${esc(notesClean)}</div>` : ''}
      <div style="padding:10px 18px;border-top:1px solid #E2DDD6;background:#FAF8F5;display:flex;gap:8px;justify-content:flex-end;">
        <button id="btnPopupClose" class="btn btn-secondary">${T('close_upper','CHIUDI')}</button>
        <button id="btnPopupEdit" class="btn btn-primary" style="background:#2B5CE6;border-color:#2B5CE6;">✏ MODIFICA</button>
      </div>
    </div>`;

  document.body.appendChild(popup);

  const close = () => popup.remove();
  popup.addEventListener('mousedown', e => { if (e.target === popup) close(); });
  document.getElementById('btnPopupClose')?.addEventListener('click', close);
  document.getElementById('btnPopupEdit')?.addEventListener('click', () => {
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

// ============================================================
// ACCOUNTS
// ============================================================

async function loadAccounts() {
  const started = performance.now();
  try {
    const accounts = await api.getAccounts();
    const select = byId('accountSelect');
    if (!select) return;
    select.innerHTML = Array.isArray(accounts) && accounts.length
      ? accounts.map(a => `<option value="${a.id}" ${a.active ? 'selected' : ''}>${esc(a.name)} (${esc(a.type)})</option>`).join('')
      : '<option value="">'+T('no_account','Nessun account')+'</option>';
    const active = Array.isArray(accounts) ? (accounts.find(a => a.active) || accounts[0]) : null;
    activeAccountId = active?.id ?? null;
    mailFolderCache = [];
    renderCustomFolders();
    if (activeAccountId) {
      loadMailFolders(false).catch(e => console.error('loadMailFolders:', e));
    }
    console.log(`[ADE MAIL UI TIMING] loadAccounts=${Math.round(performance.now() - started)}ms count=${Array.isArray(accounts) ? accounts.length : 0}`);
  } catch (e) { console.error('loadAccounts:', e); }
}

async function saveImapAccount() {
  const name     = byId('imapName')?.value.trim() || '';
  const email    = byId('imapEmail')?.value.trim() || '';
  const password = byId('imapPassword')?.value.trim() || '';
  const provider = byId('imapProvider')?.value || 'aruba';
  const imapHost = byId('imapHost')?.value.trim() || null;
  const smtpHost = byId('smtpHost')?.value.trim() || null;
  const status   = byId('imapStatus');
  if (!name || !email || !password) { if (status) status.textContent = '✕ Compila nome, email e password'; return; }
  if (status) status.textContent = '⚡ Connessione in corso...';
  try {
    const result = await api.addImapAccount(name, email, password, provider, imapHost, null, smtpHost, null);
    if (result.success) {
      if (status) status.textContent = '✓ Account aggiunto';
      activeAccountId = result.account_id;
      setTimeout(async () => {
        setHidden('imapOverlay', true);
        await loadAccounts();
        await refreshCurrentFolder();
      }, 800);
    } else if (status) {
      status.textContent = `✕ Errore: ${result.detail || 'connessione fallita'}`;
    }
  } catch (e) { if (status) status.textContent = `✕ ${String(e).slice(0, 80)}`; }
}

// ============================================================
// OFFICE UPLOAD
// ============================================================

let uploadedText = '';

function bindUpload() {
  on('btnPickFile', 'click', () => byId('officeFileInput')?.click());

  byId('officeFileInput')?.addEventListener('change', async (e) => {
    const file   = e.target.files[0];
    if (!file) return;
    const status = byId('uploadStatus');
    const nameEl = byId('uploadFileName');
    if (nameEl) nameEl.textContent = file.name;
    if (status) status.textContent = '⚡ Estrazione in corso...';
    try {
      const r = await api.uploadFile(file);
      uploadedText = r.text;
      if (status) status.textContent = `✓ ${r.chars} caratteri (${r.type})`;
    } catch (e) { if (status) status.textContent = `✕ ${String(e).slice(0, 60)}`; }
  });

  on('btnExtractToExcel', 'click', () => {
    if (!uploadedText) { showToast('Prima carica un file'); return; }
    if (byId('xlData')) byId('xlData').value = uploadedText;
    byId('xlInstruction')?.focus();
  });

  on('btnExtractToWord', 'click', () => {
    if (!uploadedText) { showToast('Prima carica un file'); return; }
    if (byId('wordSource')) byId('wordSource').value = uploadedText;
    byId('wordInstruction')?.focus();
  });
}

// ============================================================
// BIND STATIC EVENTS
// ============================================================

function bindStaticEvents() {
  on('btnLogin',          'click', () => setHidden('loginOverlay', false));
  on('btnCloseLogin',     'click', () => setHidden('loginOverlay', true));

  on('btnLogout', 'click', async () => {
    try { await api.logout(); await checkAuth(); } catch (e) { console.error('logout:', e); }
  });

  on('btnStartLogin', 'click', async () => {
    try {
      const data  = await api.startLogin();
      const uri   = data.verification_uri || 'https://microsoft.com/devicelogin';
      const urlEl = byId('loginUrl');
      if (urlEl) { urlEl.textContent = uri; urlEl.href = uri; }
      setText('loginCode', data.user_code || '');
      setHidden('loginStep1', true); setHidden('loginStep2', false);
    } catch (e) { showToast(`Errore avvio login: ${e}`); }
  });

  on('btnCompleteLogin', 'click', async () => {
    try {
      const result = await api.completeLogin();
      if (result.success) {
        setHidden('loginOverlay', true);
        setHidden('loginStep1', false); setHidden('loginStep2', true);
        await loadAccounts(); await checkAuth();
      } else { showToast('Login non completato. Riprova.'); }
    } catch (e) { showToast(`Errore: ${e}`); }
  });

  on('btnRefreshMail', 'click', async () => {
    try {
      await fetch('http://127.0.0.1:8002/cache/clear', { method: 'POST' });
      showToast('🔄 Cache identity svuotata');
    } catch(e) {}
    await refreshCurrentFolder();
  });

  on('btnPriority', 'click', () => {
    priorityMode = !priorityMode;
    byId('btnPriority')?.classList.toggle('active', priorityMode);
    if (currentFolder === 'inbox') refreshCurrentFolder();
  });

  on('btnSearchMail', 'click', async () => {
    const q = byId('mailSearch')?.value.trim() || '';
    if (!q) { await refreshCurrentFolder(); return; }
    try {
      const results = await api.searchMail(q, activeAccountId);
      console.log('[SEARCH DEBUG] type:', typeof results, 'isArray:', Array.isArray(results), 'value:', JSON.stringify(results)?.slice(0, 200));
      renderMailList(results);
      setText('statMail', Array.isArray(results) ? results.length : 0);
    } catch (e) { console.error('searchMail:', e); }
  });
  on('mailSearch', 'keydown', (e) => { if (e.key === 'Enter') byId('btnSearchMail')?.click(); });

  // Folder menu
  on('btnMore', 'click', (e) => { e.stopPropagation(); byId('moreDropdown')?.classList.toggle('hidden'); });

  on('btnShowInbox', 'click', async () => {
    await openFolder('inbox', 'btnShowInbox');
  });
  on('btnShowSent', 'click', async () => {
    await openFolder('sent', 'btnShowSent');
  });
  on('btnShowDrafts', 'click', async () => {
    await openFolder('drafts', 'btnShowDrafts');
  });
  on('btnShowSpam', 'click', async () => {
    await openFolder('spam', 'btnShowSpam');
  });
  on('btnShowDeleted', 'click', async () => {
    await openFolder('deleted', 'btnShowDeleted');
  });

  // Calendario → finestra nativa
  on('btnShowCalendar', 'click', () => {
    window.electronAPI?.openCalendarWindow?.();
  });

  // Marketing → finestra nativa
  on('btnShowMarketing', 'click', () => {
    window.electronAPI?.openMarketingWindow?.();
  });

  // Voce in sidebar — gestita da voice_mail.js/bindVoice()

  // Nuova mail
  on('btnNewMail', 'click', () => {
    if (window.electronAPI?.openNewMailWindow) {
      window.electronAPI.openNewMailWindow({ account_id: activeAccountId });
    } else {
      setHidden('newMailPanel', false);
    }
  });


  on('btnCloseNewMail',    'click', () => setHidden('newMailPanel', true));
  on('btnGenerateNewMail', 'click', generateNewMailDraft);
  on('btnSendNewMail',     'click', sendNewMail);
  on('newMailTo',          'input', () => handleAddressAutocomplete('newMailTo', 'toAutocomplete'));
  on('newMailCc',          'input', () => handleAddressAutocomplete('newMailCc', 'ccAutocomplete'));
  on('newMailBcc',         'input', () => handleAddressAutocomplete('newMailBcc', 'bccAutocomplete'));
  on('btnAttachFile',      'click', () => byId('newMailFileInput')?.click());
  byId('newMailFileInput')?.addEventListener('change', handleNewMailAttachment);

  // Calendario
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

  // Office
  on('btnCreateExcel', 'click', async () => {
    const instruction = byId('xlInstruction')?.value.trim() || '';
    const data        = byId('xlData')?.value.trim() || '';
    const filename    = byId('xlFilename')?.value.trim() || null;
    const status      = byId('xlStatus');
    const result      = byId('xlResult');
    if (!instruction && !data) { if (status) status.textContent = '✕ Inserisci istruzione o dati'; return; }
    if (status) status.textContent = '⚡ Generazione in corso...';
    result?.classList.add('hidden');
    try {
      const res = await api.createExcel(data, instruction, filename);
      if (status) status.textContent = '✓ File creato';
      if (result) { result.textContent = `📁 ${res.filename}\n${res.path}`; result.classList.remove('hidden'); }
    } catch (e) { if (status) status.textContent = `✕ Errore: ${e}`; }
  });

  on('btnCreateWord', 'click', async () => {
    const instruction = byId('wordInstruction')?.value.trim() || '';
    const source      = byId('wordSource')?.value.trim() || '';
    const title       = byId('wordTitle')?.value.trim() || '';
    const filename    = byId('wordFilename')?.value.trim() || null;
    const status      = byId('wordStatus');
    const result      = byId('wordResult');
    if (!instruction) { if (status) status.textContent = '✕ Inserisci istruzione'; return; }
    if (status) status.textContent = '⚡ Generazione in corso...';
    result?.classList.add('hidden');
    try {
      const res = await api.createWord(instruction, source, filename, title);
      if (status) status.textContent = '✓ File creato';
      if (result) { result.textContent = `📁 ${res.filename}\n${res.path}`; result.classList.remove('hidden'); }
    } catch (e) { if (status) status.textContent = `✕ Errore: ${e}`; }
  });

  // Account
  on('accountSelect', 'change', async (e) => {
    const id = parseInt(e.target.value, 10);
    if (!id) return;
    try {
      await api.switchAccount(id);
      activeAccountId = id;
      customFolderCountsRequestId += 1;
      customFolderNewCounts = new Map();
      mailFolderCache = [];
      currentFolder = 'inbox';
      currentFolderLabel = 'inbox';
      renderCustomFolders();
      selectedMailId = null;
      currentMailIndex = -1;
      currentMailList = [];
      updateVoiceContext?.(null, -1);
      document.querySelectorAll('.mail-item').forEach(el => el.classList.remove('selected'));
      resetMailDetail();
      await loadMailFolders(false);
      await refreshCurrentFolder();
      await loadEvents();
    }
    catch (e) { console.error('switchAccount:', e); }
  });

  on('btnAddAccount',   'click', () => setHidden('imapOverlay', false));
  on('btnCloseImap',    'click', () => setHidden('imapOverlay', true));

  // Bottone 👤 ID per configurare identity account
  const _acSel = byId('accountSelect');
  const _btnIdExisting = byId('btnIdentityAccount');
  if (_btnIdExisting && _acSel) {
    _btnIdExisting.addEventListener('click', () => {
      const selId = parseInt(_acSel.value, 10);
      const selName = _acSel.options[_acSel.selectedIndex]?.text || '';
      if (selId) openIdentityModal(selId, selName);
    });
  }
  on('btnCreateFolder', 'click', openCreateFolderPanel);
  on('btnAddFolder',    'click', openCreateFolderPanel);
  on('btnCloseFolderPanel', 'click', () => setHidden('folderPanel', true));
  on('btnSaveFolder', 'click', saveFolder);
  on('folderNameInput', 'input', () => refreshFolderKeywordSuggestion());
  on('folderKeywordsInput', 'input', () => { folderKeywordsDirty = true; });
  on('btnRefreshCustomFolders', 'click', async () => {
    await refreshCurrentFolder();
    showToast('📬 Aggiornato');
  });
  on('btnCloseMoveMailPanel', 'click', () => setHidden('moveMailPanel', true));
  on('btnRefreshFolders', 'click', () => loadMailFolders(false));
  on('btnConfirmMoveMail', 'click', moveSelectedMail);
  on('imapProvider',    'change', (e) => {
    const custom = byId('imapCustomFields');
    if (custom) custom.style.display = e.target.value === 'custom' ? 'block' : 'none';
  });
  on('btnAddMicrosoft', 'click', () => { setHidden('imapOverlay', true); setHidden('loginOverlay', false); });

  on('btnAddGmail', 'click', () => {
    // Precompila campi IMAP per Gmail
    const prov = document.getElementById('imapProvider');
    if (prov) { prov.value = 'gmail'; prov.dispatchEvent(new Event('change')); }
    const host = document.getElementById('imapHost');
    const sport = document.getElementById('smtpHost');
    // Mostra hint password app
    const status = document.getElementById('imapStatus');
    if (status) status.innerHTML = '<span style="color:rgba(180,40,30,0.8)">Gmail richiede una <a href="https://myaccount.google.com/apppasswords" target="_blank" style="color:var(--accent)">password per le app</a> (non la password Google normale)</span>';
    const nameEl = document.getElementById('imapName');
    if (nameEl && !nameEl.value) nameEl.placeholder = 'Es: Gmail Lavoro';
    const emailEl = document.getElementById('imapEmail');
    if (emailEl) emailEl.focus();
  });
  on('btnSaveImap',     'click', saveImapAccount);

  // Click fuori chiude dropdown
  document.addEventListener('click', (e) => {
    const more    = byId('moreDropdown');
    const btnMore = byId('btnMore');
    if (more && !more.contains(e.target) && btnMore && !btnMore.contains(e.target)) {
      more.classList.add('hidden');
    }
    [
      ['newMailTo', 'toAutocomplete'],
      ['newMailCc', 'ccAutocomplete'],
      ['newMailBcc', 'bccAutocomplete'],
    ].forEach(([inputId, boxId]) => {
      const input = byId(inputId);
      const box = byId(boxId);
      if (box && input && !box.contains(e.target) && !input.contains(e.target)) {
        box.classList.add('hidden');
      }
    });
  });
}

// ============================================================
// INIT
// ============================================================


// ============================================================
// BULK MAIL
// ============================================================

let _bulkRecipients = [];
let _bulkPollingInterval = null;

async function init() {
  // Listener notifica follow-up da Electron — apre mail
  if (window.electronAPI?.onOpenMail) {
    window.electronAPI.onOpenMail(({ id, folder, account_id }) => {
      if (account_id && account_id !== activeAccountId) {
        api.switchAccount(account_id).then(() => {
          activeAccountId = account_id;
          openMail(String(id), folder || null);
        }).catch(() => openMail(String(id), folder || null));
      } else {
        openMail(String(id), folder || null);
      }
    });
  }

  // Listener nuova mail da Electron — mostra banner in-app con CREA BOZZA
  if (window.electronAPI?.onNewMail) {
    window.electronAPI.onNewMail((mailData) => {
      showMailAlert(mailData);
    });
  }

  // Listener reply aperta da finestra mail nativa
  if (window.electronAPI?.onOpenReplyFor) {
    window.electronAPI.onOpenReplyFor((data) => {
      selectedMailId     = String(data.id);
      selectedMailFolder = data.folder || null;
      if (data.account_id && data.account_id !== activeAccountId) {
        api.switchAccount(data.account_id).then(() => {
          activeAccountId = data.account_id;
        }).catch(() => {});
      }
      replyAttachments = [];
      const subject = data.subject || '';
      currentReplyDefaultTo      = data.sender || '';
      currentReplyDefaultSubject = /^re:/i.test(subject) ? subject : `Re: ${subject}`;
      openNativeReplyWindow(currentReplyDefaultTo, currentReplyDefaultSubject);

      // Posiziona il reply a fianco destro della finestra mail
      // usando i bounds passati da main.js
      if (data._mailWinX !== undefined) {
        const modal = byId('replyModal');
        if (modal) {
          const w = data._mailWinW || 680;
          const h = data._mailWinH || 700;
          const x = data._mailWinX + w + 10; // destra della mail + gap
          const y = data._mailWinY;
          // Converti coordinate schermo → coordinate dentro la console
          const appRect = document.getElementById('appShell')?.getBoundingClientRect() || {left:0,top:0};
          const winLeft = window.screenX || window.screenLeft || 0;
          const winTop  = window.screenY || window.screenTop  || 0;
          modal.style.left      = (x - winLeft) + 'px';
          modal.style.top       = (y - winTop - 30) + 'px'; // -30 per titlebar
          modal.style.width     = w + 'px';
          modal.style.height    = h + 'px';
          modal.style.transform = 'none';
        }
      }
    });
  }

  bindTabs();
  bindStaticEvents();
  bindUpload();
  bindVoice();
  bindKeyboardNav();
  initBulkTab();
  setFolderActive('btnShowInbox');
  checkAuth().catch(e => console.error('init checkAuth:', e));
}


// ── ELIMINA ACCOUNT (tasto destro su select account) ──────────────────────────
async function deleteCurrentAccount(accountId) {
  if (!accountId) return;
  const sel = byId('accountSelect');
  const label = sel?.selectedOptions?.[0]?.textContent || `account ${accountId}`;
  const ok = confirm(
    `Eliminare "${label}"?\n\n` +
    `Verranno rimossi l'account e tutte le sue mail indicizzate localmente.\n` +
    `Le mail sui server (Microsoft/IMAP) NON vengono toccate.`
  );
  if (!ok) return;

  try {
    const r = await fetch(`http://127.0.0.1:8002/accounts/${accountId}`, { method: 'DELETE' });
    if (!r.ok) {
      const err = await r.text();
      alert(`Errore eliminazione: ${err.slice(0, 200)}`);
      return;
    }
    const data = await r.json();
    const n = (data.data_deleted && data.data_deleted.threads) || 0;
    console.log('[DELETE ACCOUNT]', data);
    if (n > 0) console.log(`Account eliminato. ${n} mail indicizzate rimosse.`);
    activeAccountId = null;
    await loadAccounts();
    await refreshCurrentFolder().catch(() => {});
  } catch (e) {
    console.error('deleteCurrentAccount:', e);
    alert(`Errore: ${String(e).slice(0, 200)}`);
  }
}

// Menu contestuale (tasto destro) sulla select degli account
(() => {
  const sel = byId('accountSelect');
  if (!sel || sel.dataset.ctxBound) return;
  sel.dataset.ctxBound = '1';
  sel.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    document.getElementById('accountCtxMenu')?.remove();

    const menu = document.createElement('div');
    menu.id = 'accountCtxMenu';
    menu.style.cssText =
      'position:fixed;z-index:99999;background:#fff;border:1px solid #ccc;' +
      'border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.18);padding:4px 0;' +
      'font-size:13px;min-width:170px';
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';

    const item = document.createElement('div');
    item.textContent = (typeof T === 'function' ? T('delete_account', 'Elimina account') : 'Elimina account');
    item.style.cssText = 'padding:7px 14px;cursor:pointer;color:#c0392b';
    item.onmouseenter = () => { item.style.background = '#f5f5f5'; };
    item.onmouseleave = () => { item.style.background = ''; };
    item.onclick = () => {
      menu.remove();
      deleteCurrentAccount(sel.value || activeAccountId);
    };
    menu.appendChild(item);
    document.body.appendChild(menu);

    const close = () => { menu.remove(); document.removeEventListener('click', close); };
    setTimeout(() => document.addEventListener('click', close), 0);
  });
})();

async function waitForBackend(timeoutMs = 30000, intervalMs = 200) {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    try {
      const r = await fetch('http://127.0.0.1:8002/health', { cache: 'no-store' });
      if (r.ok) return true;
    } catch (_) { /* porta non ancora aperta: backend in avvio */ }
    await new Promise(res => setTimeout(res, intervalMs));
  }
  return false;
}

async function bootstrap() {
  const ready = await waitForBackend();
  if (!ready) {
    setText('authLabel', 'BACKEND NON RAGGIUNGIBILE');
    console.error('[ADE MAIL] backend 8002 non risponde entro il timeout');
    return;
  }
  await init();
  if (window.startOnboardingIfNeeded) window.startOnboardingIfNeeded();
  setInterval(checkAuth, 30000);
  setInterval(autosaveDraft, 30000);
}

bootstrap();

// ── DOCK BACK (mail_window → pannello destro) ─────────────────────────────────
if (window.electronAPI?.onDockMailBack) {
  window.electronAPI.onDockMailBack((data) => {
    if (!data?.id) return;
    if (data.account_id) activeAccountId = data.account_id;
    window._currentMailId     = data.id;
    window._currentMailFolder = data.folder || null;
    window._activeAccountId   = data.account_id || activeAccountId;
    openMail(data.id, data.folder || null);
  });
}

// ── BRIDGE API (per popup_bridge.js) ─────────────────────────────────────────
let _detailToken = 0;
window.loadMailDetail = (id, folder, accountId) => {
  if (accountId) activeAccountId = accountId;
  window._currentMailId     = id;
  window._currentMailFolder = folder;
  window._activeAccountId   = accountId || activeAccountId;
  const token = ++_detailToken;
  setTimeout(() => { if (token === _detailToken) openMail(id, folder); }, 0);
};
window.cancelMailDetail = () => { _detailToken++; };
window.resetMailDetail  = resetMailDetail;

// ── DA FARE (dashboard) ───────────────────────────────────────────────────────

function todoLoad() {
  try { return JSON.parse(localStorage.getItem('ade_todo') || '[]'); } catch { return []; }
}
function todoSave(items) {
  localStorage.setItem('ade_todo', JSON.stringify(items));
}

function renderTodo() {
  const wrap = byId('dash-todo');
  if (!wrap) return;

  const items = todoLoad();

  const FILE_ICONS = { pdf:'📄', doc:'📝', docx:'📝', xls:'📊', xlsx:'📊', ppt:'📋', pptx:'📋', zip:'🗜', txt:'📃' };
  function fileIcon(name) {
    const ext = (name||'').split('.').pop().toLowerCase();
    return FILE_ICONS[ext] || '📎';
  }

  // Card container
  const cardStyle = `background:white;border:1.5px solid rgba(0,0,0,0.75);border-radius:14px;box-shadow:0 4px 14px rgba(0,0,0,0.12);padding:12px 14px;`;

  // Input area
  const inputHtml = `
    <div id="todo-drop-area" style="position:relative;">
      <div id="todo-drop-overlay" style="display:none;position:absolute;inset:0;border-radius:10px;background:linear-gradient(135deg,rgba(238,185,221,0.9),rgba(176,199,244,0.9));border:2px dashed rgba(0,0,0,0.4);z-index:10;align-items:center;justify-content:center;font-size:13px;font-weight:500;color:rgba(0,0,0,0.6);">📎 Rilascia il file</div>
      <div style="display:flex;gap:8px;align-items:center;">
        <input id="todo-input" type="text" placeholder="${T('add_note_ph','Aggiungi nota… o trascina un file')}"
          style="flex:1;border:1.5px solid rgba(0,0,0,0.75);border-radius:8px;padding:7px 10px;font-size:12px;font-family:inherit;outline:none;background:white;box-shadow:0 2px 8px rgba(0,0,0,0.08);"
          onkeydown="if(event.key==='Enter')window._todoAdd()"/>
        <button onclick="window._todoAdd()" style="padding:6px 12px;border-radius:8px;border:1.5px solid rgba(0,0,0,0.75);background:linear-gradient(135deg,#eeb9dd,#b0c7f4);font-size:11px;font-weight:600;font-family:inherit;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.12);">+</button>
      </div>
    </div>`;

  // Items list
  const pending = items.filter(i => !i.done);
  const done    = items.filter(i => i.done);

  function itemHtml(item) {
    const isFile = item.type === 'file';
    const icon   = isFile ? fileIcon(item.text) : '📝';
    return `<div style="display:flex;align-items:center;gap:8px;padding:7px 9px;background:${item.done?'rgba(0,0,0,0.03)':'rgba(0,0,0,0.04)'};border-radius:8px;border:0.5px solid rgba(0,0,0,0.08);${item.done?'opacity:0.5':''}">
      <span style="font-size:13px;flex-shrink:0;">${icon}</span>
      <span style="flex:1;font-size:11px;color:rgba(0,0,0,0.8);${item.done?'text-decoration:line-through;color:rgba(0,0,0,0.4)':''};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${item.text}</span>
      <button onclick="window._todoToggle('${item.id}')" style="background:none;border:none;cursor:pointer;font-size:13px;flex-shrink:0;opacity:0.5;" title="${item.done?T('reactivate','Riattiva'):T('done','Fatto')}">${item.done?'↩':'✓'}</button>
      <button onclick="window._todoDelete('${item.id}')" style="background:none;border:none;cursor:pointer;font-size:12px;flex-shrink:0;opacity:0.35;" title="${T('delete','Elimina')}">✕</button>
    </div>`;
  }

  const listHtml = pending.length || done.length ? `
    <div style="display:flex;flex-direction:column;gap:4px;margin-top:8px;">
      ${pending.map(itemHtml).join('')}
      ${done.length ? `<div style="font-size:9px;letter-spacing:1px;text-transform:uppercase;color:rgba(0,0,0,0.3);margin:4px 0 2px;">${T('completed','Completati')}</div>${done.slice(0,3).map(itemHtml).join('')}` : ''}
    </div>` : '';

  wrap.innerHTML = `<div style="${cardStyle}">${inputHtml}${listHtml}</div>`;

  // Drag & drop
  const dropArea = byId('todo-drop-area');
  const dropOverlay = byId('todo-drop-overlay');

  dropArea?.addEventListener('dragover', e => {
    e.preventDefault();
    if (dropOverlay) dropOverlay.style.display = 'flex';
  });
  dropArea?.addEventListener('dragleave', e => {
    if (!dropArea.contains(e.relatedTarget) && dropOverlay) dropOverlay.style.display = 'none';
  });
  dropArea?.addEventListener('drop', e => {
    e.preventDefault();
    if (dropOverlay) dropOverlay.style.display = 'none';
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    const todos = todoLoad();
    files.forEach(f => {
      todos.unshift({ id: Date.now() + Math.random(), text: f.name, type: 'file', done: false, path: f.path || '' });
    });
    todoSave(todos);
    renderTodo();
  });
}

window._todoAdd = function() {
  const input = byId('todo-input');
  const text = input?.value?.trim();
  if (!text) return;
  const todos = todoLoad();
  todos.unshift({ id: Date.now() + Math.random(), text, type: 'note', done: false });
  todoSave(todos);
  if (input) input.value = '';
  renderTodo();
};

window._todoToggle = function(id) {
  const todos = todoLoad();
  const item = todos.find(i => String(i.id) === String(id));
  if (item) item.done = !item.done;
  todoSave(todos);
  renderTodo();
};

window._todoDelete = function(id) {
  const todos = todoLoad().filter(i => String(i.id) !== String(id));
  todoSave(todos);
  renderTodo();
};
