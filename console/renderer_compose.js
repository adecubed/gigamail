// renderer_compose.js — composizione: risposta, nuova mail, allegati, autocomplete.
//
// Estratto da renderer.js: stesso scope globale degli altri script classici
// (lo stato — replyAttachments, pendingAttachments, currentDraft, ... — resta
// dichiarato in renderer.js). Le parti PURE stanno in window.ComposeView e
// sono coperte da tests/compose_view.test.js: nomi di allegato, indirizzi e
// nomi dalla rubrica passano tutti da esc().

const ComposeView = (() => {
  /** Chip degli allegati con il bottone di rimozione (onclick e' codice nostro, non dati). */
  function attachmentChipsHtml(atts, removeExpr, chipStyle) {
    return (atts || []).map((a, i) => `
    <span class="attachment-chip"${chipStyle ? ` style="${chipStyle}"` : ''}>
      📎 ${esc(a.name)} (${Math.round((a.size || 0)/1024)}KB)
      <button onclick="${removeExpr(i)}" style="background:none;border:none;cursor:pointer;color:var(--red);margin-left:4px">✕</button>
    </span>`).join('');
  }

  /** Voci del menu autocomplete destinatari. */
  function autocompleteItemsHtml(results) {
    return (results || []).map(r => `
      <div class="autocomplete-item" data-email="${esc(r.email)}">
        ${esc(r.name ? `${r.name} — ` : '')}${esc(r.email)}
      </div>`).join('');
  }

  /** Righe del banner "allegati suggeriti" (path e nome negli attributi). */
  function suggestedAttachmentsHtml(attachments) {
    return (attachments || []).map(a => `
    <div style="display:flex;align-items:center;gap:8px;margin-top:6px;">
      <input type="checkbox" class="suggested-attach-check" data-path="${esc(a.path)}" data-name="${esc(a.name)}" checked
        style="cursor:pointer;accent-color:#2B5CE6;width:14px;height:14px;"/>
      <span style="font-size:11px;font-family:var(--mono);color:#3730A3;flex:1;word-break:break-all;">${esc(a.name)}</span>
      <span style="font-size:9px;color:#8A8280;">score: ${esc(typeof a.score === 'number' ? a.score.toFixed(1) : '')}</span>
    </div>`).join('');
  }

  /** "a@x; b@y, c@z" → ['a@x','b@y','c@z'] */
  function splitAddresses(raw) {
    return String(raw || '').split(/[;,]/).map(s => s.trim()).filter(Boolean);
  }

  /** L'indirizzo che si sta scrivendo: l'ultimo token dopo ; o , */
  function addressToken(value) {
    const parts = String(value || '').split(/[;,]/);
    return (parts[parts.length - 1] || '').trim();
  }

  /** Sostituisce il token in scrittura con il suggerimento scelto. */
  function mergeAddressSuggestion(value, email) {
    const parts = String(value || '').split(/[;,]/);
    if (!parts.length) return email;
    parts[parts.length - 1] = ` ${email}`;
    return parts.map((part) => part.trim()).filter(Boolean).join('; ');
  }

  return { attachmentChipsHtml, autocompleteItemsHtml, suggestedAttachmentsHtml,
           splitAddresses, addressToken, mergeAddressSuggestion };
})();
if (typeof window !== 'undefined') window.ComposeView = ComposeView;

function renderReplyAttachments() {
  const box = byId('replyAttachmentsBox');
  if (!box) return;
  if (!replyAttachments.length) { box.innerHTML = ''; return; }
  box.innerHTML = ComposeView.attachmentChipsHtml(replyAttachments, (i) => `replyAttachments.splice(${i},1);renderReplyAttachments()`);
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

  const items = ComposeView.suggestedAttachmentsHtml(attachments);

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
  box.innerHTML = ComposeView.attachmentChipsHtml(pendingAttachments, (i) => `removePendingAttachment(${i})`, 'cursor:default');
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
  const cc      = ComposeView.splitAddresses(ccRaw);
  const bcc     = ComposeView.splitAddresses(bccRaw);
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
  return ComposeView.addressToken(input?.value);
}

function applyAddressSuggestion(input, email) {
  input.value = ComposeView.mergeAddressSuggestion(input?.value, email);
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
    box.innerHTML = ComposeView.autocompleteItemsHtml(results);
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

// ── Binding del pannello nuova mail ──────────────────────────────────────────
function bindComposeEvents() {
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

  // Click fuori chiude i menu di autocomplete
  document.addEventListener('click', (e) => {
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
