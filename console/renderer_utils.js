function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key) : it; }
// renderer_utils.js — Utility, toast, folder, dashboard, DOM helpers
// Caricato prima di renderer.js in index_v2.html

// TOAST
// ============================================================

function showToast(message, type = 'info', duration = 3500) {
  let container = document.getElementById('ade-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'ade-toast-container';
    document.body.appendChild(container);
  }

  const icons = { success: '✓', error: '✕', warning: '⚠', info: '◉' };
  const labels = { success: 'OK', error: 'ERRORE', warning: 'ATTENZIONE', info: 'ADE MAIL' };

  const toast = document.createElement('div');
  toast.className = `ade-toast toast-${type}`;
  toast.innerHTML = `
    <div class="ade-toast-icon">${icons[type] || '◉'}</div>
    <div class="ade-toast-body">
      <div class="ade-toast-label">${labels[type] || 'ADE MAIL'}</div>
      <div class="ade-toast-msg">${esc(message)}</div>
    </div>`;

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));

  setTimeout(() => {
    toast.classList.add('hide');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
  }, duration);
}

// ============================================================
// NOTIFICA NUOVA MAIL IN-APP (con bottone CREA BOZZA)
// ============================================================

function showMailAlert(mailData) {
  // mailData: { id, subject, sender, senderName, folder, account_id }
  const existing = document.getElementById('ade-mail-alert');
  if (existing) existing.remove();

  const container = document.createElement('div');
  container.id = 'ade-mail-alert';
  container.style.cssText = [
    'position:fixed',
    'bottom:20px',
    'right:20px',
    'z-index:99999',
    'background:#FFFFFF',
    'border:1px solid #E2DDD6',
    'border-left:4px solid #2B5CE6',
    'border-radius:4px',
    'box-shadow:0 4px 24px rgba(43,92,230,0.18)',
    'width:340px',
    'font-family:var(--mono,monospace)',
    'overflow:hidden',
    'animation:slideInRight 0.25s ease',
  ].join(';');

  const senderLabel = mailData.senderName || mailData.sender || 'Mittente sconosciuto';
  const subjectLabel = mailData.subject || '(nessun oggetto)';

  container.innerHTML = `
    <style>
      @keyframes slideInRight {
        from { transform: translateX(110%); opacity: 0; }
        to   { transform: translateX(0);   opacity: 1; }
      }
    </style>
    <div style="padding:12px 14px 10px;display:flex;flex-direction:column;gap:6px;">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <span style="font-size:9px;font-weight:700;letter-spacing:2px;color:#2B5CE6;">${T('new_mail_badge','NUOVA MAIL')}</span>
        <button id="btnCloseMailAlert" style="background:none;border:none;cursor:pointer;color:#8A8280;font-size:14px;line-height:1;padding:0 2px;">✕</button>
      </div>
      <div style="font-size:12px;font-weight:600;color:#1A1614;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
           title="${esc(senderLabel)}">${esc(senderLabel)}</div>
      <div style="font-size:11px;color:#4A4340;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
           title="${esc(subjectLabel)}">${esc(subjectLabel)}</div>
      <div style="display:flex;gap:8px;margin-top:4px;">
        <button id="btnMailAlertDraft" style="flex:1;background:#2B5CE6;border:none;border-radius:2px;color:#fff;font-size:10px;font-weight:700;letter-spacing:1.5px;padding:7px 10px;cursor:pointer;">
          &#9889; CREA BOZZA
        </button>
        <button id="btnMailAlertOpen" style="flex:1;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;color:#1A1614;font-size:10px;font-weight:700;letter-spacing:1.5px;padding:7px 10px;cursor:pointer;">
          APRI
        </button>
      </div>
    </div>`;

  document.body.appendChild(container);

  // Auto-chiudi dopo 12 secondi
  const autoClose = setTimeout(() => {
    container.style.opacity = '0';
    container.style.transition = 'opacity 0.3s';
    setTimeout(() => container.remove(), 300);
  }, 12000);

  const close = () => {
    clearTimeout(autoClose);
    container.remove();
  };

  document.getElementById('btnCloseMailAlert')?.addEventListener('click', close);

  // APRI — apre la mail nel pannello
  document.getElementById('btnMailAlertOpen')?.addEventListener('click', async () => {
    close();
    if (mailData.account_id && mailData.account_id !== activeAccountId) {
      try {
        await api.switchAccount(mailData.account_id);
        activeAccountId = mailData.account_id;
      } catch(e) {}
    }
    openMail(String(mailData.id), mailData.folder || null);
  });

  // CREA BOZZA — apre popup reply già compilato con AI
  document.getElementById('btnMailAlertDraft')?.addEventListener('click', async () => {
    close();
    try {
      // Switca account se necessario
      if (mailData.account_id && mailData.account_id !== activeAccountId) {
        await api.switchAccount(mailData.account_id);
        activeAccountId = mailData.account_id;
      }
      // Seleziona la mail
      selectedMailId = String(mailData.id);
      selectedMailFolder = mailData.folder || null;
      // Apri reply modal con generazione automatica
      const defaultTo = mailData.sender || '';
      const defaultSubject = (mailData.subject || '').match(/^re:/i)
        ? mailData.subject
        : `Re: ${mailData.subject || ''}`;
      currentReplyDefaultTo = defaultTo;
      currentReplyDefaultSubject = defaultSubject;
      openReplyModal(defaultTo, defaultSubject);
      // Genera bozza automaticamente dopo 300ms (modal deve essere aperto)
      setTimeout(async () => {
        await generateDraft();
      }, 300);
    } catch(e) {
      showToast('Errore apertura bozza: ' + e.message, 'error');
    }
  });
}

// ============================================================
// UTILITY
// ============================================================

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function linkifyText(text) {
  const escaped = esc(text);
  return escaped.replace(
    /(https?:\/\/[^\s<]+)/gi,
    (url) => `<a href="${url}" class="mail-link" target="_blank" rel="noopener noreferrer">${url}</a>`
  );
}

function formatMailBodyHtml(text) {
  const raw = String(text ?? '').replace(/\r\n/g, '\n').trim();
  if (!raw) return '';

  function parseLine(line) {
    // Markdown links [text](url)
    line = line.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, u) =>
      `<a href="${u}" style="color:#185FA5;text-decoration:underline;" onclick="event.preventDefault();window.electronAPI?.openExternal?.('${u}')">${t}</a>`
    );
    // Bold **text** or __text__
    line = line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    line = line.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    // Italic *text* or _text_
    line = line.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    line = line.replace(/_([^_]+)_/g, '<em>$1</em>');
    // Strikethrough ~~text~~
    line = line.replace(/~~([^~]+)~~/g, '<s>$1</s>');
    // Remaining URLs
    line = linkifyText(line);
    return line;
  }

  const blocks = raw.split(/\n{2,}/).map(block => block.trim()).filter(Boolean);
  return blocks.map(block => {
    // Heading # ## ###
    if (/^#{1,3} /.test(block)) {
      const level = block.match(/^(#{1,3}) /)[1].length;
      const text = parseLine(block.replace(/^#{1,3} /, ''));
      const size = level === 1 ? '18px' : level === 2 ? '15px' : '13px';
      return `<p class="mail-paragraph" style="font-size:${size};font-weight:600;margin-bottom:8px;">${text}</p>`;
    }
    // Horizontal rule ---
    if (/^[-*_]{3,}$/.test(block)) {
      return '<hr style="border:none;border-top:1px solid rgba(0,0,0,0.1);margin:10px 0;"/>';
    }
    // List items * - •
    const listLines = block.split('\n');
    const isList = listLines.every(l => /^[*\-•] /.test(l.trim()) || l.trim() === '');
    if (isList) {
      const items = listLines.filter(l => /^[*\-•] /.test(l.trim()))
        .map(l => `<li style="margin-bottom:3px;">${parseLine(l.trim().replace(/^[*\-•] /, ''))}</li>`).join('');
      return `<ul style="padding-left:18px;margin-bottom:10px;">${items}</ul>`;
    }
    // Normal paragraph
    const lines = block.split('\n').map(l => l.trimEnd()).filter(l => l.length > 0);
    const html = lines.map(parseLine).join('<br>');
    return `<p class="mail-paragraph">${html}</p>`;
  }).join('');
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('it-IT', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch { return '—'; }
}

function fmtDateTime(iso) {
  if (!iso) return '';
  return String(iso).slice(0, 16);
}

function byId(id) { return document.getElementById(id); }

function suggestKeywordsFromFolderName(name) {
  const raw = String(name || '').toLowerCase();
  const normalized = raw
    .replace(/[/\\|]+/g, ' ')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!normalized) return [];

  const baseTokens = normalized
    .split(' ')
    .map(part => part.trim())
    .filter(part => part.length >= 3);

  const extras = [];
  if (normalized.includes('immob')) extras.push('appartamento', 'rogito', 'visita');
  if (normalized.includes('client')) extras.push('preventivo', 'contratto');
  if (normalized.includes('idealista')) extras.push('appartamento', 'visita', 'immobile');
  if (normalized.includes('spam')) extras.push('newsletter', 'promo');
  if (normalized.includes('news')) extras.push('newsletter');
  if (normalized.includes('fattur')) extras.push('fattura', 'pagamento');
  if (normalized.includes('legal')) extras.push('contratto', 'documenti');

  return [...new Set([...baseTokens, ...extras])].slice(0, 8);
}

function normalizeFolderName(folder) {
  return String(folder?.displayName || folder?.name || folder?.id || '').trim();
}

function normalizeFolderToken(value) {
  return String(value || '').toLowerCase().replace(/[\s_-]+/g, '');
}

function isBuiltInFolder(folder) {
  const id = normalizeFolderToken(folder?.id || '');
  const name = normalizeFolderToken(normalizeFolderName(folder));
  const flags = String(folder?.flags || '').toLowerCase();
  return [
    'inbox',
    'sent',
    'sentitems',
    'drafts',
    'draft',
    'junk',
    'junkemail',
    'spam',
    'trash',
    'deleted',
    'deleteditems',
    'archive',
    'outbox',
    'conversationhistory',
    'syncissues',
    'serverfailures',
    'localfailures',
    'rssfeeds',
  ].some(token => id === token || name === token || flags.includes(`\\${token}`));
}

function getCustomFolders() {
  return (Array.isArray(mailFolderCache) ? mailFolderCache : []).filter(folder => !isBuiltInFolder(folder));
}

function formatFolderNewCount(count) {
  const safe = Number(count || 0);
  if (!safe) return '';
  return safe > 99 ? '99+' : String(safe);
}

function isRecentUnreadMail(message, nowTs = Date.now()) {
  if (!message || message.isRead) return false;
  const rawDate = message.receivedDateTime || message.sentDateTime || message.createdDateTime;
  if (!rawDate) return false;
  const ts = Date.parse(rawDate);
  if (!Number.isFinite(ts)) return false;
  const fiveDaysMs = 5 * 24 * 60 * 60 * 1000;
  return (nowTs - ts) <= fiveDaysMs;
}

function renderCustomFolders() {
  const box = byId('customFoldersList');
  if (!box) return;
  const folders = getCustomFolders();
  if (!folders.length) {
    box.innerHTML = '<div class="list-empty">'+T('no_personal_folder','Nessuna cartella personale.')+'</div>';
    return;
  }
  // In testa: la via di ritorno. Dentro una cartella personalizzata l'unica
  // strada verso la posta in arrivo era l'icona nella sidebar, che non si
  // legge come "indietro".
  const homeChip = `
      <span class="custom-folder-row">
        <button class="custom-folder-chip custom-folder-home ${currentFolder === 'inbox' ? 'active' : ''}" data-home="1">
          <span class="custom-folder-chip-label">📥 ${T('inbox','Posta in arrivo')}</span>
        </button>
      </span>`;
  box.innerHTML = homeChip + folders.map(folder => {
    const id = String(folder.id || normalizeFolderName(folder));
    const label = normalizeFolderName(folder) || id;
    const active = currentFolder === `custom:${id}` ? 'active' : '';
    const newCount = formatFolderNewCount(customFolderNewCounts.get(id) || 0);
    return `
      <span class="custom-folder-row">
        <button class="custom-folder-chip ${active}" data-folder-id="${esc(id)}" data-folder-label="${esc(label)}">
          <span class="custom-folder-chip-label">${esc(label)}</span>
          ${newCount ? `<span class="custom-folder-badge" title="${T('recent_unread_5d','Mail recenti non lette negli ultimi 5 giorni')}">${esc(newCount)}</span>` : ''}
        </button>
        <button class="custom-folder-identity" data-folder-id="${esc(id)}" data-folder-label="${esc(label)}" title="${T('config_folder_identity','Configura identity cartella')}" style="background:none;border:none;cursor:pointer;padding:2px 4px;color:#8A8280;font-size:11px;opacity:0.7;">⚙</button>
        <button class="custom-folder-delete" data-folder-delete-id="${esc(id)}" data-folder-delete-label="${esc(label)}" title="${T('delete_folder','Elimina cartella')}">×</button>
      </span>`;
  }).join('');
  box.querySelectorAll('.custom-folder-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.home) { openFolder('inbox', 'btnShowInbox'); return; }
      const folderId = btn.getAttribute('data-folder-id') || '';
      const label = btn.getAttribute('data-folder-label') || folderId;
      // ri-click sulla cartella gia' aperta = torna alla posta in arrivo
      if (currentFolder === `custom:${folderId}`) { openFolder('inbox', 'btnShowInbox'); return; }
      openCustomFolder(folderId, label);
    });
  });
  box.querySelectorAll('.custom-folder-identity').forEach(btn => {
    btn.addEventListener('click', async (event) => {
      event.stopPropagation();
      const folderId = btn.getAttribute('data-folder-id') || '';
      const label = btn.getAttribute('data-folder-label') || folderId;
      if (!folderId || !activeAccountId) return;
      openFolderIdentityModal(activeAccountId, folderId, label);
    });
  });
  box.querySelectorAll('.custom-folder-delete').forEach(btn => {
    btn.addEventListener('click', async (event) => {
      event.stopPropagation();
      const folderId = btn.getAttribute('data-folder-delete-id') || '';
      const label = btn.getAttribute('data-folder-delete-label') || folderId;
      if (!folderId) return;
      if (!confirm(`Eliminare la cartella "${label}"?`)) return;
      try {
        await api.deleteMailFolder(folderId, activeAccountId);
        if (currentFolder === `custom:${folderId}`) {
          currentFolder = 'inbox';
          currentFolderLabel = 'inbox';
          setFolderActive('btnShowInbox');
          resetMailDetail();
          await refreshCurrentFolder();
        }
        await loadMailFolders(false);
      } catch (e) {
        showToast(`Errore eliminazione cartella: ${e}`);
      }
    });
  });
}

async function refreshCustomFolderNewCounts() {
  const requestId = ++customFolderCountsRequestId;
  const accountId = activeAccountId;
  const folders = getCustomFolders();
  if (!folders.length || !accountId) {
    customFolderNewCounts = new Map();
    renderCustomFolders();
    return;
  }

  const nowTs = Date.now();
  const nextCounts = new Map();
  await Promise.all(
    folders.map(async (folder) => {
      const id = String(folder.id || normalizeFolderName(folder) || '').trim();
      if (!id) return;
      try {
        const mails = await api.getFolderMail(id, 100, accountId);
        const count = Array.isArray(mails)
          ? mails.filter(message => isRecentUnreadMail(message, nowTs)).length
          : 0;
        nextCounts.set(id, count);
      } catch (e) {
        console.error(`refreshCustomFolderNewCounts ${id}:`, e);
        nextCounts.set(id, 0);
      }
    })
  );
  if (requestId !== customFolderCountsRequestId || accountId !== activeAccountId) {
    return;
  }
  customFolderNewCounts = nextCounts;
  renderCustomFolders();
}

function getMoveTargetFolderId() {
  return byId('moveFolderSelect')?.value || '';
}

function renderFolderOptions(folders) {
  const select = byId('moveFolderSelect');
  if (!select) return;
  const items = Array.isArray(folders) ? folders : [];
  mailFolderCache = items;
  if (!items.length) {
    select.innerHTML = '<option value="">'+T('no_folder_avail','Nessuna cartella disponibile')+'</option>';
    renderCustomFolders();
    return;
  }
  select.innerHTML = items.map(folder => {
    const id = String(folder.id || normalizeFolderName(folder));
    const label = normalizeFolderName(folder) || id;
    return `<option value="${esc(id)}">${esc(label)}</option>`;
  }).join('');
  renderCustomFolders();
}

async function loadMailFolders(selectFirst = false) {
  const status = byId('moveMailStatus');
  if (status) status.textContent = 'Caricamento cartelle...';
  try {
    const folders = await api.getMailFolders(activeAccountId);
    renderFolderOptions(folders);
    refreshCustomFolderNewCounts().catch(e => console.error('refreshCustomFolderNewCounts:', e));
    if (selectFirst && byId('moveFolderSelect') && byId('moveFolderSelect').options.length) {
      byId('moveFolderSelect').selectedIndex = 0;
    }
    if (status) status.textContent = '';
    return folders;
  } catch (e) {
    renderCustomFolders();
    if (status) status.textContent = `Errore cartelle: ${e}`;
    throw e;
  }
}

async function openCreateFolderPanel() {
  setHidden('folderPanel', false);
  setText('folderStatus', '');
  const panel = byId('folderPanel');
  const card = panel?.querySelector?.('.login-card');
  const input = byId('folderNameInput');
  const keywordsInput = byId('folderKeywordsInput');
  folderKeywordsDirty = false;
  if (panel) {
    panel.style.pointerEvents = 'auto';
  }
  if (card) {
    card.style.pointerEvents = 'auto';
  }
  if (input) {
    input.value = '';
  }
  if (keywordsInput) {
    keywordsInput.value = '';
  }
  setTimeout(() => {
    const target = keywordsInput || input;
    target?.focus?.();
    target?.click?.();
    target?.setSelectionRange?.(target.value.length, target.value.length);
  }, 30);
}

function refreshFolderKeywordSuggestion() {
  const input = byId('folderNameInput');
  const keywordsInput = byId('folderKeywordsInput');
  if (!input || !keywordsInput || folderKeywordsDirty) return;
  const suggested = suggestKeywordsFromFolderName(input.value);
  keywordsInput.value = suggested.join(', ');
}

async function saveFolder() {
  const input = byId('folderNameInput');
  const keywordsInput = byId('folderKeywordsInput');
  const status = byId('folderStatus');
  const name = input?.value.trim() || '';
  const keywords = String(keywordsInput?.value || '')
    .split(/[,;\n]+/)
    .map(item => item.trim())
    .filter(Boolean);
  if (!name) {
    if (status) status.textContent = 'Inserisci un nome cartella.';
    return;
  }
  if (status) status.textContent = 'Creazione in corso...';
  try {
    const result = await api.createMailFolder(name, keywords, activeAccountId);
    const suffix = keywords.length ? ` | keywords: ${keywords.join(', ')}` : '';
    if (status) status.textContent = `Cartella creata: ${result.displayName || result.name || name}${suffix}`;
    await loadMailFolders(true);
    renderCustomFolders();
    setTimeout(() => setHidden('folderPanel', true), 500);
  } catch (e) {
    if (status) status.textContent = `Errore creazione: ${e}`;
  }
}

async function openMoveMailPanel(mailId) {
  if (!mailId) return;
  selectedMailId = mailId;
  setHidden('moveMailPanel', false);
  setText('moveMailStatus', '');
  try {
    await loadMailFolders(true);
  } catch {}
}

async function moveSelectedMail() {
  const folderId = getMoveTargetFolderId();
  const status = byId('moveMailStatus');
  if (!selectedMailId) {
    if (status) status.textContent = 'Nessuna mail selezionata.';
    return;
  }
  if (!folderId) {
    if (status) status.textContent = 'Seleziona una cartella di destinazione.';
    return;
  }
  if (status) status.textContent = 'Spostamento in corso...';
  try {
    await api.moveMailToFolder(selectedMailId, folderId, activeAccountId, currentFolder);
    document.querySelector(`[data-id="${selectedMailId}"]`)?.remove();
    resetMailDetail();
    setHidden('moveMailPanel', true);
    await refreshCurrentFolder();
  } catch (e) {
    if (status) status.textContent = `Errore spostamento: ${e}`;
  }
}

function setVoicePlaybackActive(active) {
  document.dispatchEvent(new CustomEvent('ade-voice-playback', { detail: { active: Boolean(active) } }));
}

async function ensureMailSummary(id, accountId, detailRoot = null, folder = null) {
  const box = detailRoot?.querySelector?.('#mailSummaryBox') || byId('mailSummaryBox');
  if (!box) return '';

  const cacheKey = `${accountId || 'default'}::${folder || 'default-folder'}::${id}`;
  const cached = mailSummaryCache.get(cacheKey);
  if (cached) {
    setSummaryBoxState(box, cached, false);
    return cached;
  }

  setSummaryBoxState(box, 'Caricamento riassunto...', true);
  try {
    const sumData = await api.getSummary(id, accountId, folder);
    const summary = sumData?.summary || 'Riassunto non disponibile.';
    const actions = sumData?.actions || [];
    mailSummaryCache.set(cacheKey, summary);
    setSummaryBoxState(box, summary, false, actions);
    return summary;
  } catch {
    setSummaryBoxState(box, 'Riassunto non disponibile.', false);
    return '';
  }
}

function setSummaryBoxState(target, text, isLoading = false, actions = []) {
  if (!target) return;
  target.classList.toggle('loading', Boolean(isLoading));
  if (isLoading) {
    target.textContent = `📋 ${text}`;
    return;
  }

  // Renderizza testo formattato (bold, bullet) + bottoni azione
  const formatted = (text || '')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');

  let actionsHtml = '';
  if (actions && actions.length) {
    actionsHtml = `<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:5px;">` +
      actions.map((a, i) =>
        `<button class="summary-action-btn" data-action="${esc(a)}" style="
          padding:4px 10px;border-radius:14px;font-size:10.5px;font-family:var(--font,sans-serif);
          background:rgba(255,255,255,0.7);border:1.5px solid rgba(0,0,0,0.55);
          color:rgba(0,0,0,0.7);cursor:pointer;transition:all 0.15s;
          box-shadow:0 2px 8px rgba(0,0,0,0.2);">⚡ ${esc(a)}</button>`
      ).join('') +
    `</div>`;
  }

  target.innerHTML = `<span style="font-weight:700;letter-spacing:.5px;opacity:.6;font-size:10px">📋 ANALISI</span><br>${formatted}${actionsHtml}`;

  // Click su bottone azione → apre reply window con quell'istruzione
  target.querySelectorAll('.summary-action-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      if (!action) return;
      // Precompila istruzione nella reply window e apre
      currentReplyDefaultTo      = window._currentReplyDefaultTo || '';
      currentReplyDefaultSubject = window._currentReplyDefaultSubject || '';
      if (typeof openNativeReplyWindow === 'function') {
        openNativeReplyWindow(currentReplyDefaultTo, currentReplyDefaultSubject, action);
      }
    });
  });
}

async function loadFolderSuggestion(id, detailRoot = null) {
  const box = detailRoot?.querySelector?.('#mailSuggestionBox') || byId('mailSuggestionBox');
  if (!box || !id) return;
  const dismissKey = `${activeAccountId || 'default'}::${id}`;
  if (dismissedSuggestions.has(dismissKey)) {
    box.classList.add('hidden');
    return;
  }
  try {
    const result = await api.getFolderSuggestion(id, activeAccountId, getCurrentFolderRequestValue());
    const suggestion = result?.suggestion || null;
    if (!suggestion?.folder_id || !suggestion?.displayName) {
      box.classList.add('hidden');
      return;
    }
    box.classList.remove('hidden');
    box.innerHTML = `
      <div class="mail-suggestion-title">${T('folder_suggestion','SUGGERIMENTO CARTELLA')}</div>
      <div>Potresti spostarla in <strong>${esc(suggestion.displayName)}</strong>.<br>Segnali: ${esc(suggestion.reason || 'storico')}.</div>
      <div class="mail-suggestion-actions">
        <button class="btn btn-secondary" id="btnAcceptSuggestion">${T('yes_move','SÌ, SPOSTA')}</button>
        <button class="btn btn-secondary" id="btnDismissSuggestion">${T('no','NO')}</button>
      </div>`;
    byId('btnAcceptSuggestion')?.addEventListener('click', async () => {
      try {
        await api.moveMailToFolder(id, suggestion.folder_id, activeAccountId, currentFolder);
        document.querySelector(`[data-id="${id}"]`)?.remove();
        resetMailDetail();
        await refreshCurrentFolder();
        await loadMailFolders(false);
      } catch (e) {
        showToast(`Errore spostamento suggerito: ${e}`);
      }
    });
    byId('btnDismissSuggestion')?.addEventListener('click', () => {
      dismissedSuggestions.add(dismissKey);
      box.classList.add('hidden');
    });
  } catch (e) {
    console.error('folderSuggestion:', e);
    box.classList.add('hidden');
  }
}

function on(id, eventName, handler) {
  const el = byId(id);
  if (el) el.addEventListener(eventName, handler);
}

function setHidden(id, hidden) {
  const el = byId(id);
  if (el) el.classList.toggle('hidden', hidden);
}

function setText(id, text) {
  const el = byId(id);
  if (el) el.textContent = text;
}

function focusMailItemByIndex(index) {
  if (!Array.isArray(currentMailList) || !currentMailList.length) return;
  const clamped = Math.max(0, Math.min(index, currentMailList.length - 1));
  const msg = currentMailList[clamped];
  if (!msg?.id) return;
  currentMailIndex = clamped;
  openMail(String(msg.id));
  const selected = document.querySelector(`.mail-item[data-id="${CSS.escape(String(msg.id))}"]`);
  selected?.scrollIntoView?.({ block: 'nearest' });
}

function bindKeyboardNav() {
  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const tag = target?.tagName?.toLowerCase?.() || '';
    const isEditable =
      target?.isContentEditable ||
      tag === 'input' ||
      tag === 'textarea' ||
      tag === 'select';
    if (isEditable) return;
    if (!Array.isArray(currentMailList) || currentMailList.length === 0) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusMailItemByIndex(currentMailIndex < 0 ? 0 : currentMailIndex + 1);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusMailItemByIndex(currentMailIndex <= 0 ? 0 : currentMailIndex - 1);
      return;
    }

    if (event.key === 'Enter') {
      if (currentMailIndex < 0) return;
      event.preventDefault();
      focusMailItemByIndex(currentMailIndex);
    }
  });
}

function resetMailDetail() {
  const detail = byId('mailDetail');
  if (!detail) return;
  // Rimuovi allegati suggeriti della mail precedente
  document.getElementById('suggestedAttachmentsBanner')?.remove();
  detail.className = 'main-area';
  detail.style.cssText = '';
  detail.innerHTML = '<div id="ade-dashboard" style="padding:10px;display:flex;flex-direction:column;gap:10px;width:100%;height:100%;overflow-y:auto;box-sizing:border-box;"></div>';
  renderDashboard();
}

async function renderDashboard() {
  const dash = byId('ade-dashboard');
  if (!dash) return;

  const DOT_COLORS = ['#185FA5','#A32D2D','#1A7F4B','#7C3AED','#B45309'];
  const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';

  function card(content) {
    return `<div style="background:white;border:1.5px solid rgba(0,0,0,0.75);border-radius:14px;box-shadow:0 4px 14px rgba(0,0,0,0.12);padding:12px 14px;">${content}</div>`;
  }
  function secLabel(t) {
    return `<div style="font-size:9px;font-weight:500;letter-spacing:1.4px;text-transform:uppercase;color:rgba(0,0,0,0.4);margin-bottom:4px;">${t}</div>`;
  }

  // Scheletro immediato
  dash.innerHTML = secLabel(T('account_label','Account')) +
    `<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;" id="dash-accounts">` +
    card('<div style="font-size:11px;color:rgba(0,0,0,0.3);text-align:center;padding:12px 0;">Caricamento…</div>') +
    card('<div style="font-size:11px;color:rgba(0,0,0,0.3);text-align:center;padding:12px 0;">Caricamento…</div>') +
    `</div>` +
    secLabel(T('calendar','Calendario')) +
    `<div id="dash-calendar">` +
    card('<div style="font-size:11px;color:rgba(0,0,0,0.3);text-align:center;padding:8px 0;">Caricamento…</div>') +
    `</div>`;

  // Carica account
  try {
    const accounts = await api.getAccounts();
    const today = new Date();
    today.setHours(0,0,0,0);

    const accCards = await Promise.all((accounts||[]).map(async (acc, i) => {
      const dotColor = DOT_COLORS[i % DOT_COLORS.length];
      let unread = 0, sentToday = 0, lastMail = '';
      try {
        const u = await fetch(`${API}/mail/unread_count?account_id=${acc.id}`).then(r=>r.json());
        unread = u?.count ?? 0;
      } catch {}
      try {
        const sent = await api.getSentMail(20, acc.id);
        const arr = Array.isArray(sent) ? sent : [];
        sentToday = arr.filter(m => {
          const d = new Date(m.sentDateTime||m.receivedDateTime||0);
          return d >= today;
        }).length;
      } catch {}
      try {
        const inbox = await fetch(`${API}/mail?top=1&account_id=${acc.id}`).then(r=>r.json());
        const first = Array.isArray(inbox) ? inbox[0] : null;
        if (first) lastMail = (first.from?.emailAddress?.name||'') + ' — ' + (first.subject||'');
      } catch {}

      const name = acc.name || acc.displayName || acc.email?.split('@')[0] || 'Account';
      const email = acc.email || '';
      const provider = email.includes('microsoft')||email.includes('outlook')||email.includes('hotmail') ? 'Microsoft' :
                       email.includes('gmail') ? 'Gmail' : name;

      return `<div style="background:white;border:1.5px solid rgba(0,0,0,0.75);border-radius:14px;box-shadow:0 4px 14px rgba(0,0,0,0.12);padding:12px 14px;cursor:pointer;transition:box-shadow 0.15s;min-width:0;overflow:hidden;"
        onmouseover="this.style.boxShadow='0 6px 20px rgba(0,0,0,0.22)'"
        onmouseout="this.style.boxShadow='0 4px 14px rgba(0,0,0,0.12)'"
        onclick="window._switchAccount && window._switchAccount(${acc.id}, '${provider}')">
        <div style="display:flex;align-items:center;gap:7px;margin-bottom:5px;">
          <div style="width:9px;height:9px;border-radius:50%;background:${dotColor};border:1.5px solid rgba(0,0,0,0.2);flex-shrink:0;"></div>
          <div style="font-size:12px;font-weight:500;color:rgba(0,0,0,0.82);flex:1;">${provider}</div>
        </div>
        <div style="font-size:10px;color:rgba(0,0,0,0.4);margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${email}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:7px;">
          <div style="background:rgba(0,0,0,0.04);border-radius:8px;padding:7px 9px;">
            <div style="font-size:20px;font-weight:500;line-height:1;color:${unread>0?'#993556':'rgba(0,0,0,0.82)'};">${unread}</div>
            <div style="font-size:9px;color:rgba(0,0,0,0.4);margin-top:2px;">${T('unread','Non lette')}</div>
          </div>
          <div style="background:rgba(0,0,0,0.04);border-radius:8px;padding:7px 9px;">
            <div style="font-size:20px;font-weight:500;line-height:1;color:rgba(0,0,0,0.82);">${sentToday}</div>
            <div style="font-size:9px;color:rgba(0,0,0,0.4);margin-top:2px;">${T('sent_today','Inviate oggi')}</div>
          </div>
        </div>
        ${lastMail ? `<div style="font-size:10px;color:rgba(0,0,0,0.4);background:rgba(0,0,0,0.04);border-radius:7px;padding:5px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">↙ ${lastMail}</div>` : ''}
        <div style="font-size:10px;color:rgba(0,0,0,0.4);text-align:right;margin-top:6px;">${T('goto_account',"Vai all'account →")}</div>
      </div>`;
    }));

    const accGrid = byId('dash-accounts');
    if (accGrid) {
      accGrid.innerHTML = accCards.length ? accCards.join('') : card(`
        <div class="ob-empty">
          <div class="ob-empty-title">${T('ob_empty_title','Nessun account collegato')}</div>
          <div class="ob-empty-body">${T('ob_empty_body','Collega una casella per iniziare.')}</div>
          <button class="compose-btn ob-cta-inline" onclick="window.openOnboarding&&window.openOnboarding()">${T('ob_empty_cta','Configura GigaMail')}</button>
        </div>`).replace('<div style="background:white', '<div style="grid-column:1/-1;background:white');
    }
  } catch(e) {
    const accGrid = byId('dash-accounts');
    if (accGrid) accGrid.innerHTML = card(`<div style="font-size:11px;color:rgba(0,0,0,0.3);text-align:center;">${T('account_load_error','Errore caricamento account')}</div>`);
  }

  // Carica calendario
  try {
    const now = new Date();
    const events = await api.getEvents(30);
    const upcoming = (Array.isArray(events) ? events : [])
      .filter(e => new Date(e.start?.dateTime||e.start?.date||0) >= now)
      .sort((a,b) => new Date(a.start?.dateTime||a.start?.date) - new Date(b.start?.dateTime||b.start?.date))
      .slice(0,4);

    function fmtEvDate(dt) {
      if (!dt) return '';
      try {
        const d = new Date(dt);
        return d.toLocaleDateString('it-IT',{day:'2-digit',month:'short'}) + ' ' +
               d.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});
      } catch { return ''; }
    }

    const evRows = upcoming.length ? upcoming.map(e =>
      `<div onclick="window.electronAPI?.openCalendarWindow?.()" style="display:flex;align-items:center;gap:8px;padding:6px 9px;background:rgba(0,0,0,0.04);border-radius:8px;cursor:pointer;transition:background 0.15s;" onmouseover="this.style.background='rgba(0,0,0,0.08)'" onmouseout="this.style.background='rgba(0,0,0,0.04)'">
        <div style="width:7px;height:7px;border-radius:50%;background:linear-gradient(135deg,#eeb9dd,#b0c7f4);border:1px solid rgba(0,0,0,0.2);flex-shrink:0;"></div>
        <div style="font-size:11px;color:rgba(0,0,0,0.82);flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${e.subject||e.title||'Evento'}</div>
        <div style="font-size:10px;color:rgba(0,0,0,0.4);white-space:nowrap;">${fmtEvDate(e.start?.dateTime||e.start?.date)}</div>
      </div>`
    ).join('') : '<div style="font-size:11px;color:rgba(0,0,0,0.3);text-align:center;padding:8px 0;">'+T('no_upcoming','Nessun appuntamento in arrivo')+'</div>';

    const calDiv = byId('dash-calendar');
    if (calDiv) calDiv.innerHTML = card(`
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:9px;">
        <div style="width:24px;height:24px;border-radius:7px;background:linear-gradient(135deg,#eeb9dd,#b0c7f4);border:1.5px solid rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;">📅</div>
        <div style="font-size:12px;font-weight:500;color:rgba(0,0,0,0.82);flex:1;">${T('cal_upcoming','Prossimi appuntamenti')}</div>
        <div style="font-size:10px;color:rgba(0,0,0,0.4);">${now.toLocaleDateString('it-IT',{day:'numeric',month:'long',year:'numeric'})}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:5px;">${evRows}</div>
      <div style="font-size:10px;color:rgba(0,0,0,0.4);text-align:right;margin-top:8px;cursor:pointer;"
        onclick="window.electronAPI?.openCalendarWindow?.()">${T('open_calendar','Apri calendario →')}</div>
    `);
  } catch {
    const calDiv = byId('dash-calendar');
    if (calDiv) calDiv.innerHTML = card('<div style="font-size:11px;color:rgba(0,0,0,0.3);text-align:center;">'+T('no_calendar','Nessun calendario configurato')+'</div>');
  }
}

// Switch account dalla dashboard
window._switchAccount = async (accountId, providerName) => {
  try {
    activeAccountId = accountId;
    window.activeAccountId = accountId;
    window._activeAccountId = accountId;
    // Pulisci mail corrente per evitare cross-account ID mismatch
    window._currentMailId     = null;
    window._currentMailFolder = null;
    // Aggiorna il select UI
    const sel = document.getElementById('accountSelect');
    if (sel) {
      sel.value = String(accountId);
      sel.dispatchEvent(new Event('change'));
    }
    await openFolder('inbox', 'btnShowInbox');
  } catch(e) { console.error('_switchAccount:', e); }
};

function getCurrentMailFetcher() {
  if (currentFolder === 'sent')   return () => api.getSentMail(30, activeAccountId);
  if (currentFolder === 'drafts') return () => api.getDraftsMail(30, activeAccountId);
  if (currentFolder === 'spam')   return () => api.getSpamMail(30, activeAccountId);
  if (currentFolder === 'deleted') return () => api.getDeletedMail(30, activeAccountId);
  if (currentFolder.startsWith('custom:')) {
    const folderId = currentFolder.slice('custom:'.length);
    return () => api.getFolderMail(folderId, 30, activeAccountId);
  }
  return () => api.getMail(30, 0, priorityMode, activeAccountId);
}

function setFolderActive(btnId) {
  ['btnShowInbox', 'btnShowSent', 'btnShowDrafts', 'btnShowSpam', 'btnShowDeleted'].forEach(id => byId(id)?.classList.remove('active'));
  byId(btnId)?.classList.add('active');
  document.querySelectorAll('.custom-folder-chip').forEach(el => el.classList.remove('active'));
  document.querySelector('.custom-folder-home')?.classList.toggle('active', btnId === 'btnShowInbox');
}

const FOLDER_TITLE_KEYS = { inbox: 'inbox', sent: 'sent_items', drafts: 'drafts', spam: 'spam', deleted: 'trash' };

/** Titolo del pannello lista: cartella standard (tradotta) o etichetta della
 *  cartella personalizzata. Prima restava "Posta in arrivo" ovunque. */
function setFolderTitle(folder, label) {
  const el = byId('currentFolderLabel');
  if (!el) return;
  const key = FOLDER_TITLE_KEYS[folder];
  if (key) {
    el.setAttribute('data-i18n', key);
    el.textContent = T(key, label || folder);
  } else {
    el.removeAttribute('data-i18n');   // applyLang non deve sovrascriverlo
    el.textContent = label || folder;
  }
}

function renderMailListStatus(message) {
  const list = byId('mailList');
  if (!list) return;
  list.innerHTML = `<div class="list-empty">${esc(message)}</div>`;
}

function getCurrentFolderRequestValue() {
  if (currentFolder?.startsWith('custom:')) {
    return currentFolder.slice('custom:'.length);
  }
  return currentFolder || 'inbox';
}

async function refreshCurrentFolder() {
  const started = performance.now();
  try {
    const mails = await getCurrentMailFetcher()();
    renderMailList(mails);
    refreshCustomFolderNewCounts().catch(e => console.error('refreshCustomFolderNewCounts:', e));
    setText('statMail', Array.isArray(mails) ? mails.length : 0);
    const sampleIds = Array.isArray(mails) ? mails.slice(0, 3).map(m => m?.id).filter(Boolean).join(',') : '';
    const sampleFolders = Array.isArray(mails)
      ? [...new Set(mails.slice(0, 5).map(m => m?.folder).filter(Boolean))].join(',')
      : '';
    console.log(
      `[ADE MAIL UI TIMING] refreshCurrentFolder=${Math.round(performance.now() - started)}ms ` +
      `folder=${currentFolderLabel || currentFolder} count=${Array.isArray(mails) ? mails.length : 0} ` +
      `accountId=${activeAccountId ?? 'none'} sampleIds=${sampleIds || '-'} sampleFolders=${sampleFolders || '-'}`
    );
    return mails;
  } catch (e) {
    console.error('refreshCurrentFolder:', e);
    renderMailListStatus(`Errore apertura cartella ${currentFolder}: ${String(e)}`);
    setText('statMail', '!');
    throw e;
  }
}

async function openFolder(folder, btnId) {
  currentFolder = folder;
  selectedMailFolder = null;
  currentFolderLabel = folder;
  setFolderActive(btnId);
  setFolderTitle(folder);
  setHidden('moreDropdown', true);
  selectedMailId = null;
  updateVoiceContext?.(null, -1);
  currentMailIndex = -1;
  currentMailList = [];
  document.querySelectorAll('.mail-item').forEach(el => el.classList.remove('selected'));
  resetMailDetail();
  renderMailListStatus(`Caricamento ${folder}...`);
  try {
    await refreshCurrentFolder();
  } catch {}
}

async function openCustomFolder(folderId, label) {
  if (!folderId) return;
  currentFolder = `custom:${folderId}`;
  currentFolderLabel = label || folderId;
  setFolderActive('');
  setFolderTitle(currentFolder, currentFolderLabel);
  document.querySelectorAll('.custom-folder-chip').forEach(el => {
    el.classList.toggle('active', (el.getAttribute('data-folder-id') || '') === folderId);
  });
  selectedMailId = null;
  updateVoiceContext?.(null, -1);
  currentMailIndex = -1;
  currentMailList = [];
  document.querySelectorAll('.mail-item').forEach(el => el.classList.remove('selected'));
  resetMailDetail();
  renderMailListStatus(`Caricamento ${currentFolderLabel}...`);
  try {
    await refreshCurrentFolder();
  } catch {}
}

// ============================================================
// AUTH
// ============================================================