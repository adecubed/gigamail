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

function renderReplyAttachments() {
  const box = byId('replyAttachmentsBox');
  if (!box) return;
  if (!replyAttachments.length) { box.innerHTML = ''; return; }
  box.innerHTML = replyAttachments.map((a, i) => `
    <span class="attachment-chip">
      📎 ${esc(a.name)} (${Math.round(a.size/1024)}KB)
      <button onclick="replyAttachments.splice(${i},1);renderReplyAttachments()" 
              style="background:none;border:none;cursor:pointer;color:var(--red);margin-left:4px">✕</button>
    </span>`).join('');
}

// ============================================================
// REPLY MODAL
// ============================================================

function openNativeReplyWindow(to, subject, instruction = '') {
  // Esponi per setSummaryBoxState nei bottoni azione
  window._currentReplyDefaultTo      = to || currentReplyDefaultTo;
  window._currentReplyDefaultSubject = subject || currentReplyDefaultSubject;
  if (window.electronAPI?.openReplyWindow) {
    window.electronAPI.openReplyWindow({
      sender:      to || currentReplyDefaultTo,
      subject:     subject || currentReplyDefaultSubject,
      id:          selectedMailId,
      folder:      selectedMailFolder,
      account_id:  activeAccountId,
      instruction: instruction || '',
      // Passa body già in memoria — evita IMAP lento nel backend
      body_text:   window._currentMailBodyText || '',
    });
  } else {
    openReplyModal(to, subject);
  }
}

// Esposta globale: "giga rispondi dicendo X" apre la finestra risposta con l'istruzione
// passata nel campo instruction (reply_window.html la scrive nel campo #instruction).
window.openReplyWithInstruction = (instruction) => {
  const to = window._currentReplyDefaultTo || currentReplyDefaultTo || '';
  const subject = window._currentReplyDefaultSubject || currentReplyDefaultSubject || '';
  openNativeReplyWindow(to, subject, instruction || '');
};

function openReplyModal(defaultTo, defaultSubject) {
  // Usa il popup glass già nell'HTML invece di crearne uno nuovo
  const modal = byId('replyModal');
  if (!modal) { _openReplyModalLegacy(defaultTo, defaultSubject); return; }

  // Rimuovi allegati suggeriti della risposta precedente
  document.getElementById('suggestedAttachmentsBanner')?.remove();

// Popola i campi
  if (byId('replyToInput'))      byId('replyToInput').value      = defaultTo      || '';
  if (byId('replySubjectInput')) byId('replySubjectInput').value = defaultSubject || '';
  if (byId('replyText'))         byId('replyText').value         = '';
  if (byId('replyAttachmentsBox')) byId('replyAttachmentsBox').innerHTML = '';
  // CC badge per reply-all
  const existingCcBadge = byId('replyCcBadge');
  if (existingCcBadge) existingCcBadge.remove();
  if (currentReplyCc.length) {
    const ccBadge = document.createElement('div');
    ccBadge.id = 'replyCcBadge';
    ccBadge.style.cssText = 'font-size:11px;color:#8A8280;font-family:var(--mono,monospace);padding:4px 0 2px;';
    ccBadge.textContent = 'CC: ' + currentReplyCc.join(', ');
    byId('replyToInput')?.parentElement?.insertAdjacentElement('afterend', ccBadge);
  }

  // Mostra il popup — posizionato a destra del centro schermo
  modal.classList.remove('hidden');
  modal.style.left = 'calc(50% + 20px)';
  modal.style.top  = '80px';
  modal.style.transform = 'none';

  // Bind bottoni se non già bindati
  if (!modal._bound) {
    modal._bound = true;
    byId('btnCloseReply')?.addEventListener('click', closeReplyModal);
    byId('btnGenerateReply')?.addEventListener('click', generateReply);
    byId('btnSendReply')?.addEventListener('click', sendReply);
    byId('btnReplyAttach')?.addEventListener('click', () => byId('replyFileInput')?.click());
    byId('replyFileInput')?.addEventListener('change', async (e) => {
      for (const file of Array.from(e.target.files||[])) {
        const reader = new FileReader();
        reader.onload = ev => {
          const b64 = ev.target.result.split(',')[1];
          replyAttachments.push({ name: file.name, data_b64: b64, type: file.type||'application/octet-stream', size: file.size });
          renderReplyAttachments();
        };
        reader.readAsDataURL(file);
      }
      e.target.value = '';
    });
    byId('replyToInput')?.addEventListener('input', () => handleAddressAutocomplete('replyToInput', 'replyToAutocomplete'));
  }

  byId('replyText')?.focus();
  return;
}

function _openReplyModalLegacy(defaultTo, defaultSubject) {
  const existing = byId('replyModal');
  if (existing) existing.remove();

  // Overlay
  const overlay = document.createElement('div');
  overlay.id = 'replyModal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(26,22,20,0.35);';

  // Box
  const box = document.createElement('div');
  box.style.cssText = [
    'background:#FFFFFF',
    'border:1px solid #E2DDD6',
    'border-top:3px solid #2B5CE6',
    'border-radius:4px',
    'width:min(820px,94vw)',
    'max-height:90vh',
    'display:flex',
    'flex-direction:column',
    'box-shadow:0 8px 40px rgba(43,92,230,0.13)',
    'overflow:hidden',
    'pointer-events:all',
  ].join(';');

  // Header
  const header = document.createElement('div');
  header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-bottom:1px solid #E2DDD6;background:#FAF8F5;flex-shrink:0;';
  header.innerHTML = '<span style="font-size:10px;font-weight:600;letter-spacing:2px;color:#8A8280;font-family:var(--mono,monospace)">'+T('new_reply_upper','NUOVA RISPOSTA')+'</span>';
  const btnClose = document.createElement('button');
  btnClose.id = 'btnCloseReplyModal';
  btnClose.textContent = '✕';
  btnClose.style.cssText = 'background:none;border:none;color:#8A8280;font-size:16px;cursor:pointer;padding:2px 6px;line-height:1;';
  header.appendChild(btnClose);
  box.appendChild(header);

  // Campi
  const fields = document.createElement('div');
  fields.style.cssText = 'padding:16px 20px 8px;flex-shrink:0;display:flex;flex-direction:column;gap:10px;background:#FFFFFF;';
  fields.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;position:relative;">
      <label style="font-size:10px;letter-spacing:1.5px;color:#8A8280;width:64px;flex-shrink:0;font-family:var(--mono,monospace);">A</label>
      <input type="text" id="replyToInput" placeholder="destinatario@email.it" autocomplete="off"
        style="flex:1;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;color:#1A1614;font-size:13px;outline:none;font-family:inherit;" />
      <div id="replyToAutocomplete" class="autocomplete-list hidden"></div>
    </div>
    <div style="display:flex;align-items:center;gap:10px;">
      <label style="font-size:10px;letter-spacing:1.5px;color:#8A8280;width:64px;flex-shrink:0;font-family:var(--mono,monospace);">OGGETTO</label>
      <input type="text" id="replySubjectInput" placeholder="${T('reply_subject_ph','Oggetto risposta...')}"
        style="flex:1;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;color:#1A1614;font-size:13px;outline:none;font-family:inherit;" />
    </div>`;
  box.appendChild(fields);

  // Textarea wrapper
  const taWrap = document.createElement('div');
  taWrap.style.cssText = 'flex:1;padding:8px 20px 4px;display:flex;flex-direction:column;min-height:0;background:#FFFFFF;';
  const ta = document.createElement('textarea');
  ta.id = 'replyText';
  ta.placeholder = 'Scrivi cosa vuoi rispondere...';
  ta.style.cssText = [
    'flex:1','width:100%','resize:none',
    'background:#F4F2EE','border:1px solid #E2DDD6','border-radius:2px',
    'padding:12px','color:#1A1614','font-size:13px','line-height:1.7',
    'outline:none','min-height:280px','box-sizing:border-box',
    'font-family:inherit','pointer-events:all',
  ].join(';');
  taWrap.appendChild(ta);
  const attachBox = document.createElement('div');
  attachBox.id = 'replyAttachmentsBox';
  attachBox.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;margin:6px 0;';
  taWrap.appendChild(attachBox);
  box.appendChild(taWrap);

  // Footer azioni
  const footer = document.createElement('div');
  footer.style.cssText = 'display:flex;align-items:center;gap:8px;padding:12px 20px;border-top:1px solid #E2DDD6;background:#FAF8F5;flex-shrink:0;flex-wrap:wrap;';
  footer.innerHTML = `
    <input type="file" id="replyFileInput" multiple style="display:none" />
    <button class="btn-voice" id="btnReplyVoice" title="${T('ade_voice','ADE voice')}">🎙 ADE</button>
    <button class="btn btn-secondary" id="btnReplyAttach">📎</button>
    <button class="btn btn-secondary" id="btnGenerateReply">⚡ GENERA BOZZA</button>
    <div style="flex:1"></div>
    <button class="btn btn-secondary" id="btnHideReply">${T('cancel_upper','ANNULLA')}</button>
    <button class="btn btn-primary" id="btnSendReply">↩ INVIA</button>`;
  box.appendChild(footer);

  overlay.appendChild(box);
  document.body.appendChild(overlay);

  // Popola campi
  ta.value = '';
  if (byId('replyToInput')) byId('replyToInput').value = defaultTo || '';
  if (byId('replySubjectInput')) byId('replySubjectInput').value = defaultSubject || '';

  // Chiudi su click overlay (solo se click diretto sull'overlay, non sul box)
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) closeReplyModal(); });

  btnClose.addEventListener('click', closeReplyModal);
  byId('btnHideReply')?.addEventListener('click', closeReplyModal);

  // ESC
  const onKey = (e) => { if (e.key === 'Escape') { closeReplyModal(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);

  // Allegati
  byId('btnReplyAttach')?.addEventListener('click', () => byId('replyFileInput')?.click());
  byId('replyFileInput')?.addEventListener('change', async (e) => {
    for (const file of Array.from(e.target.files || [])) {
      const data_b64 = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result.split(',')[1]);
        r.onerror = () => rej(new Error('Read failed'));
        r.readAsDataURL(file);
      });
      replyAttachments.push({ name: file.name, data_b64, type: file.type || 'application/octet-stream', size: file.size });
    }
    renderReplyAttachments();
    e.target.value = '';
  });
  byId('btnReplyVoice')?.addEventListener('click', () => byId('btnVoice')?.click());
  byId('btnGenerateReply')?.addEventListener('click', generateReply);
  byId('btnSendReply')?.addEventListener('click', sendReply);
  byId('replyToInput')?.addEventListener('input', () => handleAddressAutocomplete('replyToInput', 'replyToAutocomplete'));
  byId('replyToInput')?.addEventListener('focus', () => handleAddressAutocomplete('replyToInput', 'replyToAutocomplete'));
  byId('replySubjectInput')?.addEventListener('focus', hideAutocompleteBoxes);
  ta.addEventListener('focus', hideAutocompleteBoxes);

  // Focus sul textarea con piccolo delay per sicurezza
  setTimeout(() => ta.focus(), 80);
}

function closeReplyModal() {
  replyAttachments = [];
  currentReplyCc = [];
  const modal = byId('replyModal');
  if (modal) {
    modal.classList.add('hidden');
    if (byId('replyText'))         byId('replyText').value = '';
    if (byId('replyAttachmentsBox')) byId('replyAttachmentsBox').innerHTML = '';
  }
}

async function generateReply() {
  const replyText = byId('replyText');
  if (!replyText || !selectedMailId) return;
  const instruction = replyText.value.trim();

  replyText.value = 'Generazione bozza...';
  try {
    let result;
    if (!instruction) {
      // Nessun input → smart_draft con identity + semantic search
      result = await api.smartDraft(
        selectedMailId,
        activeAccountId,
        selectedMailFolder || getCurrentFolderRequestValue(),
      );
      // Mostra fonte nel placeholder come hint
      const source = result.source === 'storico'
        ? `Bozza da storico (${result.matched_sent} mail precedenti)`
        : 'Bozza dal contenuto della mail';
      replyText.placeholder = source;
      // Pre-compila destinatario e oggetto se vuoti
      if (result.reply_to && byId('replyToInput') && !byId('replyToInput').value) {
        byId('replyToInput').value = result.reply_to;
      }
      if (result.reply_subject && byId('replySubjectInput') && !byId('replySubjectInput').value) {
        byId('replySubjectInput').value = result.reply_subject;
      }
    } else {
      // Ha scritto qualcosa → reply_draft normale
      currentInstruction = instruction;
      result = await api.replyDraft(
        selectedMailId,
        instruction,
        activeAccountId,
        selectedMailFolder || getCurrentFolderRequestValue(),
      );
    }
    replyText.value = result.draft || '';
    currentDraft = result.draft || '';

    // Allegati suggeriti automaticamente dall'identity
    const suggested = result.suggested_attachments || [];
    if (suggested.length > 0) {
      _showSuggestedAttachments(suggested);
    }

  } catch (e) { replyText.value = `Errore: ${e}`; }
}

function _showSuggestedAttachments(attachments) {
  // Mostra banner allegati suggeriti nella reply modal
  const existing = document.getElementById('suggestedAttachmentsBanner');
  if (existing) existing.remove();

  const replyModal = document.querySelector('.reply-modal-body') ||
                     document.getElementById('replyText')?.parentElement;
  if (!replyModal) return;

  const banner = document.createElement('div');
  banner.id = 'suggestedAttachmentsBanner';
  banner.style.cssText = 'background:#EEF2FF;border:1px solid #C7D2FE;border-radius:3px;padding:10px 12px;margin-bottom:10px;';

  const items = attachments.map(a => `
    <div style="display:flex;align-items:center;gap:8px;margin-top:6px;">
      <input type="checkbox" class="suggested-attach-check" data-path="${esc(a.path)}" data-name="${esc(a.name)}" checked
        style="cursor:pointer;accent-color:#2B5CE6;width:14px;height:14px;"/>
      <span style="font-size:11px;font-family:var(--mono);color:#3730A3;flex:1;word-break:break-all;">${esc(a.name)}</span>
      <span style="font-size:9px;color:#8A8280;">score: ${a.score?.toFixed(1)}</span>
    </div>`).join('');

  banner.innerHTML = `
    <div style="font-size:10px;font-weight:600;letter-spacing:1.5px;color:#3730A3;margin-bottom:2px;">
      📎 ALLEGATI SUGGERITI
    </div>
    <div style="font-size:10px;color:#6366F1;">${T('select_attach_auto','Seleziona i file da allegare automaticamente')}</div>
    ${items}
    <div style="margin-top:8px;">
      <button class="btn btn-secondary" id="btnAddSuggestedAttach"
        style="font-size:10px;padding:4px 10px;color:#3730A3;border-color:#C7D2FE;">
        + AGGIUNGI SELEZIONATI
      </button>
    </div>`;

  // Inserisci prima del textarea reply
  const replyTextEl = document.getElementById('replyText');
  if (replyTextEl && replyTextEl.parentElement) {
    replyTextEl.parentElement.insertBefore(banner, replyTextEl);
  }

  document.getElementById('btnAddSuggestedAttach')?.addEventListener('click', async () => {
    const checked = banner.querySelectorAll('.suggested-attach-check:checked');
    checked.forEach(cb => {
      const path = cb.getAttribute('data-path');
      const name = cb.getAttribute('data-name');
      if (path && name) {
        // Aggiunge all'area allegati della reply
        _addAttachmentToReply(path, name);
      }
    });
    banner.remove();
    showToast(`${checked.length} allegato/i aggiunto/i`);
  });
}

async function _addAttachmentToReply(filePath, fileName) {
  try {
    // Legge file locale via endpoint server e aggiunge a replyAttachments
    const fileData = await api.readLocalFile(filePath);
    replyAttachments.push({
      name: fileData.name || fileName,
      data_b64: fileData.data_b64,
      type: fileData.type || 'application/octet-stream',
      size: fileData.size || 0,
    });
    renderReplyAttachments();
  } catch(e) {
    showToast(`Errore allegato ${fileName}: ${e.message}`);
  }
}

async function sendReply() {
  const replyTo = byId('replyToInput');
  const replySubject = byId('replySubjectInput');
  const replyText = byId('replyText');
  if (!replyText || !selectedMailId) { showToast('Errore: nessuna mail selezionata'); return; }
  const to = String(replyTo?.value || '').trim();
  const subject = String(replySubject?.value || '').trim();
  const body = replyText.value.trim();
  if (!to) { showToast('Inserisci il destinatario'); replyTo?.focus(); return; }
  if (!subject) { showToast('Inserisci l\'oggetto'); replySubject?.focus(); return; }
  if (!body) { showToast('Scrivi il corpo della mail'); replyText?.focus(); return; }
  const keepThread =
    to.toLowerCase() === String(currentReplyDefaultTo || '').trim().toLowerCase() &&
    subject === String(currentReplyDefaultSubject || '').trim();
  try {
    const result = await api.sendMail(
      to,
      subject,
      body,
      keepThread ? selectedMailId : null,
      currentDraft,
      currentInstruction,
      activeAccountId,
      replyAttachments,
      currentReplyCc.length ? currentReplyCc : undefined
    );
    closeReplyModal();
    if (result?.success && result?.sent_copy_saved === false) {
      showToast('Mail inviata, ma non sono riuscito a salvarne una copia in Inviate.');
    } else {
      showToast('Mail inviata!');
    }
  } catch (e) { showToast(`Errore invio: ${e}`); }
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
// NUOVA MAIL
// ============================================================

async function generateNewMailDraft() {
  const bodyEl   = byId('newMailBody');
  const statusEl = byId('newMailStatus');
  if (!bodyEl || !statusEl) return;
  const instruction = bodyEl.value.trim();
  if (!instruction) return;
  statusEl.textContent = '⚡ Generazione in corso...';
  try {
    const result = await api.replyDraft('new', instruction, activeAccountId);
    bodyEl.value = result.draft || '';
    statusEl.textContent = '✓ Bozza generata';
  } catch (e) { statusEl.textContent = `✕ Errore: ${e}`; }
}

function renderPendingAttachments() {
  const box = byId('pendingAttachmentsBox');
  if (!box) return;
  if (!pendingAttachments.length) { box.innerHTML = ''; return; }
  box.innerHTML = pendingAttachments.map((a, i) => `
    <span class="attachment-chip" style="cursor:default">
      📎 ${esc(a.name)} (${Math.round(a.size/1024)}KB)
      <button onclick="removePendingAttachment(${i})" style="background:none;border:none;cursor:pointer;color:var(--red);margin-left:4px">✕</button>
    </span>`).join('');
}

function removePendingAttachment(idx) {
  pendingAttachments.splice(idx, 1);
  renderPendingAttachments();
}

async function handleNewMailAttachment() {
  const input = byId('newMailFileInput');
  if (!input?.files?.length) return;
  for (const file of input.files) {
    const data_b64 = await new Promise((res, rej) => {
      const reader = new FileReader();
      reader.onload = () => res(reader.result.split(',')[1]);
      reader.onerror = rej;
      reader.readAsDataURL(file);
    });
    pendingAttachments.push({
      name: file.name,
      data_b64,
      type: file.type || 'application/octet-stream',
      size: file.size,
    });
  }
  input.value = '';
  renderPendingAttachments();
}

async function sendNewMail() {
  const to      = byId('newMailTo')?.value.trim() || '';
  const ccRaw   = byId('newMailCc')?.value.trim() || '';
  const bccRaw  = byId('newMailBcc')?.value.trim() || '';
  const subject = byId('newMailSubject')?.value.trim() || '';
  const body    = byId('newMailBody')?.value.trim() || '';
  const status  = byId('newMailStatus');
  const cc      = ccRaw.split(/[;,]/).map(s => s.trim()).filter(Boolean);
  const bcc     = bccRaw.split(/[;,]/).map(s => s.trim()).filter(Boolean);
  if (!to || !subject || !body) { if (status) status.textContent = '✕ Compila destinatario, oggetto e testo'; return; }
  if (status) status.textContent = '⚡ Invio in corso...';
  try {
    const result = await api.sendMail(
      to,
      subject,
      body,
      null,
      null,
      null,
      activeAccountId,
      pendingAttachments,
      cc,
      bcc
    );
    if (result.success) {
      if (status) {
        status.textContent = result.sent_copy_saved === false
          ? '✓ Mail inviata, ma non salvata in Inviate'
          : '✓ Mail inviata!';
      }
      autosaveSignature = '';
      setTimeout(() => {
        setHidden('newMailPanel', true);
        if (byId('newMailTo'))      byId('newMailTo').value = '';
        if (byId('newMailCc'))      byId('newMailCc').value = '';
        if (byId('newMailBcc'))     byId('newMailBcc').value = '';
        if (byId('newMailSubject')) byId('newMailSubject').value = '';
        if (byId('newMailBody'))    byId('newMailBody').value = '';
        if (status)                 status.textContent = '';
        pendingAttachments = [];
        renderPendingAttachments();
      }, 1200);
    } else if (status) { status.textContent = '✕ Invio fallito'; }
  } catch (e) { if (status) status.textContent = `✕ Errore: ${e}`; }
}

async function autosaveDraft() {
  const panel = byId('newMailPanel');
  if (!panel || panel.classList.contains('hidden')) return;
  const to      = byId('newMailTo')?.value.trim() || '';
  const cc      = byId('newMailCc')?.value.trim() || '';
  const bcc     = byId('newMailBcc')?.value.trim() || '';
  const subject = byId('newMailSubject')?.value.trim() || '';
  const body    = byId('newMailBody')?.value.trim() || '';
  if (!body) return;
  const sig = `${activeAccountId}::${to}::${cc}::${bcc}::${subject}::${body}`;
  if (sig === autosaveSignature) return;
  try { await api.saveDraft(to, subject, body, activeAccountId); autosaveSignature = sig; }
  catch (e) { console.error('autosaveDraft:', e); }
}

// ============================================================
// AUTOCOMPLETE
// ============================================================

function hideAutocompleteBoxes(activeBoxId = null) {
  ['toAutocomplete', 'ccAutocomplete', 'bccAutocomplete', 'replyToAutocomplete'].forEach((id) => {
    if (id === activeBoxId) return;
    const box = byId(id);
    if (!box) return;
    box.classList.add('hidden');
    box.innerHTML = '';
  });
}

function currentAddressToken(input) {
  const raw = String(input?.value || '');
  const parts = raw.split(/[;,]/);
  return (parts[parts.length - 1] || '').trim();
}

function applyAddressSuggestion(input, email) {
  const raw = String(input?.value || '');
  const parts = raw.split(/[;,]/);
  if (!parts.length) {
    input.value = email;
    return;
  }
  parts[parts.length - 1] = ` ${email}`;
  input.value = parts.map((part) => part.trim()).filter(Boolean).join('; ');
  input.focus();
}

async function handleAddressAutocomplete(inputId = 'newMailTo', boxId = 'toAutocomplete') {
  const input = byId(inputId);
  const box   = byId(boxId);
  if (!input || !box) return;
  const q = currentAddressToken(input);
  if (q.length < 1) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  try {
    const results = await api.getAddresses(q, activeAccountId);
    if (!Array.isArray(results) || !results.length) { box.classList.add('hidden'); return; }
    hideAutocompleteBoxes(boxId);
    box.innerHTML = results.map(r => `
      <div class="autocomplete-item" data-email="${esc(r.email)}">
        ${esc(r.name ? `${r.name} — ` : '')}${esc(r.email)}
      </div>`).join('');
    box.classList.remove('hidden');
    box.querySelectorAll('.autocomplete-item').forEach(item => {
      item.addEventListener('click', () => {
        applyAddressSuggestion(input, item.dataset.email || '');
        box.classList.add('hidden'); box.innerHTML = '';
      });
    });
  } catch (e) { console.error('getAddresses:', e); }
}

// Voice command — vedi voice_mail.js

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
