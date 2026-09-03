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
  // Ogni modulo lega i propri bottoni; qui restano login, office e
  // navigazione verso le finestre native.
  bindMailEvents();
  bindComposeEvents();
  bindCalendarEvents();
  bindAccountEvents();

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

  // Marketing → finestra nativa
  on('btnShowMarketing', 'click', () => {
    window.electronAPI?.openMarketingWindow?.();
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
