// new_mail_window_page.js — the script of new_mail_window.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
const SEND_DELAY = 5000;
let accountId = null;
let attachments = [];
let followupHours = 0;
let sendTimer = null;
let sendRafId = null;
let instructionContext = '';

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it; }

// ── BOZZA: salvata in GigaMail mentre si scrive ───────────────────────────────
// In locale due secondi dopo l'ultimo tasto. Nella cartella Bozze della
// casella (per ritrovarla su Outlook o sul telefono) alla chiusura e al
// massimo una volta al minuto: una copia IMAP costa secondi, non millisecondi.
// Stesso id per tutta la vita della finestra: il backend aggiorna, non
// accumula copie. All'invio riuscito la bozza sparisce, anche dalla casella.
// Gli allegati non si salvano (troppo pesanti).
const DRAFT_FIELDS = ['mailTo', 'mailCc', 'mailBcc', 'mailSubject', 'mailBody'];
const DRAFT_DELAY  = 2000;
const SYNC_EVERY   = 60000;
let draftId    = null;
let draftSig   = '';      // versione salvata in locale
let syncedSig  = '';      // versione chiesta per la casella
let lastSyncAt = Date.now();
let draftTimer = null;
let draftsOff  = false;   // backend senza /mail/draft/save: non insistere
let mailSent   = false;

function draftValues() {
  const v = (id) => document.getElementById(id).value;
  return { to: v('mailTo').trim(), cc: v('mailCc').trim(), bcc: v('mailBcc').trim(),
           subject: v('mailSubject').trim(), body: v('mailBody') };
}

async function saveDraftNow({ sync = false } = {}) {
  if (draftTimer) { clearTimeout(draftTimer); draftTimer = null; }
  if (draftsOff || mailSent) return;
  const d = draftValues();
  if (!d.to && !d.subject && !d.body.trim()) return;
  const sig = JSON.stringify([accountId, d]);
  const needSync = (sync || Date.now() - lastSyncAt > SYNC_EVERY) && sig !== syncedSig;
  if (sig === draftSig && !needSync) return;
  try {
    const r = await fetch(`${API}/mail/draft/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: draftId, ...d, account_id: accountId, sync: needSync }),
    });
    if (r.status === 404 || r.status === 405) { draftsOff = true; return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    draftId  = data.id || draftId;
    draftSig = sig;
    if (needSync) { syncedSig = sig; lastSyncAt = Date.now(); }
    // Non copre messaggi piu' importanti ("Invio annullato", errori).
    const st = document.getElementById('status');
    const label = T('draft_saved', 'Bozza salvata');
    if (!st.textContent || st.textContent === label) st.textContent = label;
  } catch (e) { console.error('saveDraft:', e); }
}

function scheduleDraftSave() {
  if (draftTimer) clearTimeout(draftTimer);
  draftTimer = setTimeout(saveDraftNow, DRAFT_DELAY);
}
DRAFT_FIELDS.forEach(id => document.getElementById(id).addEventListener('input', scheduleDraftSave));

async function loadDraft(id) {
  try {
    const r = await fetch(`${API}/mail/draft/local/${encodeURIComponent(id)}`);
    if (!r.ok) return;
    const d = await r.json();
    document.getElementById('mailTo').value      = d.to || '';
    document.getElementById('mailCc').value      = d.cc || '';
    document.getElementById('mailBcc').value     = d.bcc || '';
    document.getElementById('mailSubject').value = d.subject || '';
    document.getElementById('mailBody').value    = d.body || '';
    draftId  = d.draft_id;
    draftSig = JSON.stringify([accountId, draftValues()]);
    if (d.in_mailbox) syncedSig = draftSig;
  } catch (e) { console.error('loadDraft:', e); }
}

async function closeWindow() {
  await saveDraftNow({ sync: true });
  window.newMailWindowAPI?.close();
}

if (window.newMailWindowAPI) {
  window.newMailWindowAPI.onLoadNewMail(async (data) => {
    accountId = data.account_id || null;
    if (data.to)      document.getElementById('mailTo').value      = data.to;
    if (data.subject) document.getElementById('mailSubject').value = data.subject;
    if (data.body)    document.getElementById('mailBody').value    = data.body;
    if (data.draft_id) await loadDraft(data.draft_id);
    document.getElementById('mailTo').focus();
  });
}

document.getElementById('btnClose').addEventListener('click', closeWindow);
document.getElementById('btnMin').addEventListener('click',   () => window.newMailWindowAPI?.minimize());
document.getElementById('btnMax').addEventListener('click',   () => window.newMailWindowAPI?.maximize());

// ── ALLEGATI ──────────────────────────────────────────────────────────────────
document.getElementById('btnAttach').addEventListener('click', () => document.getElementById('fileInput').click());
document.getElementById('fileInput').addEventListener('change', (e) => {
  for (const file of Array.from(e.target.files||[])) addFileAsAttachment(file);
  e.target.value = '';
});

function isImage(file) { return file.type.startsWith('image/'); }

function addFileAsAttachment(file) {
  const reader = new FileReader();
  reader.onload = ev => {
    attachments.push({
      name: file.name,
      data_b64: ev.target.result.split(',')[1],
      type: file.type || 'application/octet-stream',
      size: file.size,
      isImage: isImage(file),
      dataUrl: isImage(file) ? ev.target.result : null,
    });
    renderAttachments();
  };
  reader.readAsDataURL(file);
}

function renderAttachments() {
  const box = document.getElementById('attachmentsBox');
  box.innerHTML = attachments.map((a,i) => {
    const preview = a.isImage && a.dataUrl
      ? `<img src="${a.dataUrl}" alt="${esc(a.name)}"/>`
      : (typeof GMIcons !== 'undefined' ? GMIcons.svg('paperclip', 13) : '');
    return `<span class="attach-chip">
      ${preview} ${esc(a.name)} (${Math.round(a.size/1024)}KB)
      <button class="attach-chip-rm" data-index="${i}">✕</button>
    </span>`;
  }).join('');
  box.querySelectorAll('.attach-chip-rm').forEach((b) => b.addEventListener('click', () => {
    attachments.splice(Number(b.dataset.index), 1);
    renderAttachments();
  }));
}

// ── DRAG & DROP SUL CORPO ──────────────────────────────────────────────────────
const bodyWrap = document.getElementById('bodyAreaWrap');
const bodyOverlay = document.getElementById('bodyDropOverlay');

bodyWrap.addEventListener('dragover', (e) => {
  e.preventDefault();
  bodyOverlay.classList.add('visible');
});
bodyWrap.addEventListener('dragleave', (e) => {
  if (!bodyWrap.contains(e.relatedTarget)) bodyOverlay.classList.remove('visible');
});
bodyWrap.addEventListener('drop', (e) => {
  e.preventDefault();
  bodyOverlay.classList.remove('visible');
  for (const file of Array.from(e.dataTransfer.files || [])) addFileAsAttachment(file);
});

// ── CTRL+V — INCOLLA IMMAGINI DAGLI APPUNTI ───────────────────────────────────
document.getElementById('mailBody').addEventListener('paste', (e) => {
  const items = e.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const file = item.getAsFile();
      if (file) {
        const ext = item.type.split('/')[1] || 'png';
        const named = new File([file], `screenshot_${Date.now()}.${ext}`, { type: item.type });
        addFileAsAttachment(named);
      }
    }
  }
});

// ── DRAG & DROP SULL'ISTRUZIONE AI ────────────────────────────────────────────
const instrEl  = document.getElementById('instruction');
const ctxBadge = document.getElementById('ctxBadge');

instrEl.addEventListener('dragover', (e) => { e.preventDefault(); instrEl.classList.add('drag-over'); });
instrEl.addEventListener('dragleave', () => instrEl.classList.remove('drag-over'));
instrEl.addEventListener('drop', async (e) => {
  e.preventDefault();
  instrEl.classList.remove('drag-over');
  const file = e.dataTransfer.files?.[0];
  if (!file) return;
  instrEl.placeholder = T('cmp_extracting_text', 'Estrazione testo…');
  try {
    const formData = new FormData();
    formData.append('file', file);
    const r = await fetch(`${API}/office/upload`, { method: 'POST', body: formData });
    const data = await r.json();
    instructionContext = data.text || '';
    ctxBadge.innerHTML = `${(typeof GMIcons !== 'undefined' ? GMIcons.svg('file-text', 12) : '')} ${esc(file.name)}`;
    ctxBadge.classList.add('visible');
    instrEl.placeholder = T('ai_instruction_drag_ph', 'Istruzione AI — trascina file per contesto…');
  } catch(err) {
    instrEl.placeholder = T('cmp_extract_error_retry', 'Errore estrazione — riprova');
  }
});
ctxBadge.addEventListener('click', () => {
  instructionContext = '';
  ctxBadge.classList.remove('visible');
  ctxBadge.textContent = '';
});

// ── FOLLOW-UP ─────────────────────────────────────────────────────────────────
const btnFollowup      = document.getElementById('btnFollowup');
const followupDropdown = document.getElementById('followupDropdown');
btnFollowup.addEventListener('click', (e) => {
  e.stopPropagation();
  followupDropdown.style.display = followupDropdown.style.display === 'none' ? 'block' : 'none';
});
document.querySelectorAll('.fu-opt').forEach(opt => {
  opt.addEventListener('click', () => {
    followupHours = parseInt(opt.dataset.h);
    followupDropdown.style.display = 'none';
    if (followupHours > 0) { btnFollowup.innerHTML = `${(typeof GMIcons !== 'undefined' ? GMIcons.svg('pin', 14) : '')} ${followupHours}h`; btnFollowup.classList.add('active'); }
    else { btnFollowup.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('pin', 16) : ''); btnFollowup.classList.remove('active'); }
  });
});
document.addEventListener('click', () => { followupDropdown.style.display = 'none'; });

// ── AUTOCOMPLETE ──────────────────────────────────────────────────────────────
const mailToInput = document.getElementById('mailTo');
const mailToBox   = document.getElementById('mailToAutocomplete');
async function fetchAddresses(q) {
  try { return await (await fetch(`${API}/addresses?q=${encodeURIComponent(q)}`)).json(); } catch { return []; }
}
function currentToken(input) {
  const parts = (input.value||'').split(/[;,]/);
  return (parts[parts.length-1]||'').trim();
}
function applyAddress(email) {
  const parts = (mailToInput.value||'').split(/[;,]/);
  parts[parts.length-1] = ' '+email;
  mailToInput.value = parts.map(p=>p.trim()).filter(Boolean).join('; ');
  mailToBox.classList.add('hidden'); mailToBox.innerHTML = ''; mailToInput.focus();
}
mailToInput.addEventListener('input', async () => {
  const q = currentToken(mailToInput);
  if (!q.length) { mailToBox.classList.add('hidden'); return; }
  const results = await fetchAddresses(q);
  if (!results.length) { mailToBox.classList.add('hidden'); return; }
  mailToBox.innerHTML = results.map(r =>
    `<div class="autocomplete-item" data-email="${esc(r.email)}">${esc(r.name?r.name+' — ':'')}${esc(r.email)}</div>`
  ).join('');
  mailToBox.classList.remove('hidden');
  mailToBox.querySelectorAll('.autocomplete-item').forEach(item => {
    item.addEventListener('mousedown', (e) => { e.preventDefault(); applyAddress(item.dataset.email); });
  });
});
mailToInput.addEventListener('focus', () => { if (currentToken(mailToInput).length) mailToInput.dispatchEvent(new Event('input')); });
document.addEventListener('click', (e) => {
  if (!mailToBox.contains(e.target) && e.target !== mailToInput) mailToBox.classList.add('hidden');
});

// ── GENERA ────────────────────────────────────────────────────────────────────
document.getElementById('btnGenerate').addEventListener('click', async () => {
  const btn = document.getElementById('btnGenerate');
  const ta  = document.getElementById('mailBody');
  const st  = document.getElementById('status');
  btn.disabled = true; btn.textContent = '…'; ta.value = T('cmp_generating', 'Generazione…'); st.textContent = '';
  try {
    const baseInstruction = instrEl.value.trim();
    const instruction = instructionContext
      ? `${baseInstruction}\n\n[CONTESTO FILE]\n${instructionContext.slice(0, 3000)}`
      : baseInstruction;
    const to      = document.getElementById('mailTo').value.trim();
    const subject = document.getElementById('mailSubject').value.trim();
    let url = `${API}/mail/generate_draft`;
    if (accountId) url += `?account_id=${accountId}`;
    const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({instruction,to,subject}) });
    const data = await r.json();
    if (!r.ok) throw (data.detail || `HTTP ${r.status}`);
    ta.value = data.draft || data.text || '';
    scheduleDraftSave();
  } catch(e) { ta.value = ''; st.textContent = `${T('cmp_generate_error', 'Errore generazione')}: ${e}`; }
  btn.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('zap', 14) : '') + ' ' + T('generate', 'GENERA'); btn.disabled = false;
});

// ── INVIA con delay 5s ────────────────────────────────────────────────────────
function resetSendBtn() {
  const label  = document.getElementById('sendLabel');
  const circle = document.getElementById('sendCircle');
  const btn    = document.getElementById('btnSend');
  if (sendTimer) { clearTimeout(sendTimer); sendTimer = null; }
  if (sendRafId) { cancelAnimationFrame(sendRafId); sendRafId = null; }
  btn.disabled = false; label.textContent = T('send', 'Invia ↑');
  circle.style.setProperty('--pct', '0%');
}

async function execSend() {
  const btn    = document.getElementById('btnSend');
  const label  = document.getElementById('sendLabel');
  const circle = document.getElementById('sendCircle');
  const st     = document.getElementById('status');
  const to      = document.getElementById('mailTo').value.trim();
  const subject = document.getElementById('mailSubject').value.trim();
  const body    = document.getElementById('mailBody').value;
  const cc      = document.getElementById('mailCc').value.trim();
  const bcc     = document.getElementById('mailBcc').value.trim();
  btn.disabled = true; label.textContent = T('cmp_sending_btn', 'Invio…');
  circle.style.setProperty('--pct', '100%');
  try {
    let url = `${API}/mail/send`;
    if (accountId) url += `?account_id=${accountId}`;
    const attachmentsClean = attachments.map(({dataUrl, isImage, ...rest}) => rest);
    const response = await fetch(url, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({to, subject, body, cc:cc?[cc]:[], bcc:bcc?[bcc]:[], attachments:attachmentsClean})
    });
    let result = {};
    try { result = await response.json(); } catch {}
    if (!response.ok || result?.success !== true) {
      const detail = Array.isArray(result?.detail)
        ? result.detail.map(d => d?.msg || JSON.stringify(d)).join('; ')
        : result?.detail;
      throw new Error(detail || result?.error || `${T('cmp_send_unconfirmed', 'Invio non confermato')} (HTTP ${response.status})`);
    }
    if (result.dryrun) {
      st.textContent = T('cmp_dryrun_no_send', 'Simulazione: nessuna mail inviata.');
      resetSendBtn();
      return;
    }
    mailSent = true;
    if (draftTimer) { clearTimeout(draftTimer); draftTimer = null; }
    if (draftId) {
      fetch(`${API}/mail/draft/local/${encodeURIComponent(draftId)}`, { method: 'DELETE' })
        .catch(e => console.error('deleteDraft:', e));
    }
    if (followupHours > 0) {
      try {
        await window.newMailWindowAPI?.followupSave({ message_id:null, account_id:accountId, subject, to_addr:to, hours:followupHours });
      } catch (e) { console.warn('followupSave:', e); }
    }
    st.textContent = T('cmp_sent_check', 'Inviata ✓');
    setTimeout(() => window.newMailWindowAPI?.close(), 800);
  } catch(e) {
    st.textContent = T('cmp_send_error', 'Errore invio') + (e && e.message ? `: ${e.message}` : '');
    resetSendBtn();
  }
}

document.getElementById('btnSend').addEventListener('click', () => {
  const to   = document.getElementById('mailTo').value.trim();
  const body = document.getElementById('mailBody').value;
  const st   = document.getElementById('status');
  if (sendTimer) { resetSendBtn(); st.textContent = T('cmp_send_cancelled', 'Invio annullato'); return; }
  if (!to || !body) { st.textContent = T('cmp_fill_to_body', 'Compila A e il testo'); return; }
  const label  = document.getElementById('sendLabel');
  const circle = document.getElementById('sendCircle');
  label.textContent = '✕ ' + T('cancel', 'Annulla');
  circle.style.setProperty('--pct', '0%');
  st.textContent = '';
  const startTs = performance.now();
  function tick() {
    const pct = Math.min(((performance.now() - startTs) / SEND_DELAY) * 100, 100);
    circle.style.setProperty('--pct', pct.toFixed(1) + '%');
    if (pct < 100) sendRafId = requestAnimationFrame(tick);
  }
  sendRafId = requestAnimationFrame(tick);
  sendTimer = setTimeout(() => { sendTimer = null; execSend(); }, SEND_DELAY);
});

// ══════════════════════════════════════════════════════════════
// MASKER — privacy dati sensibili
// ══════════════════════════════════════════════════════════════
let maskMapping = {};

async function maskAll() {
  const ta = document.getElementById('mailBody');
  const text = ta.value;
  if (!text.trim()) return;
  try {
    const r = await fetch(`${API}/mask`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, account_id: accountId })
    });
    const d = await r.json();
    if (!d.mapping || Object.keys(d.mapping).length === 0) {
      showMaskToast(T('cmp_mask_none_found', 'Nessun dato sensibile rilevato.'));
      return;
    }
    ta.value = d.masked;
    Object.assign(maskMapping, d.mapping);
    const n = Object.keys(d.mapping).length;
    showMaskToast(n === 1
      ? T('cmp_mask_masked_one', 'Mascherato 1 elemento.')
      : T('cmp_mask_masked_many', 'Mascherati {n} elementi.').replace('{n}', n));
  } catch (e) {
    alert(T('cmp_mask_error', 'Errore mascheramento') + ': ' + e.message);
  }
}

// Dialog custom per l'etichetta (Electron blocca prompt())
function askLabel(selected, suggested) {
  return new Promise((resolve) => {
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;';
    ov.innerHTML = `
      <div style="background:#fff;border:1px solid rgba(0,0,0,0.14);border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,0.4);width:min(360px,90vw);padding:16px;font-family:inherit">
        <div style="font-size:13px;margin-bottom:4px">${escMaskNM(T('cmp_mask', 'Maschera'))} <b>${escMaskNM(selected)}</b></div>
        <div style="font-size:11px;color:rgba(0,0,0,0.6);margin-bottom:8px">${escMaskNM(T('cmp_mask_label_editable', 'Etichetta (modificabile):'))}</div>
        <input id="maskLabelInput" type="text" value="${escMaskNM(suggested)}" style="width:100%;padding:8px 10px;border:1.5px solid rgba(0,0,0,0.4);border-radius:8px;font-size:13px;font-family:inherit;outline:none;box-sizing:border-box"/>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button id="maskLabelCancel" style="padding:7px 14px;border:1px solid rgba(0,0,0,0.2);background:#fff;border-radius:8px;cursor:pointer;font-size:12px">${escMaskNM(T('cancel', 'Annulla'))}</button>
          <button id="maskLabelOk" style="padding:7px 14px;border:none;background:#f3e6f0;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600">${escMaskNM(T('cmp_mask', 'Maschera'))}</button>
        </div>
      </div>`;
    document.body.appendChild(ov);
    const input = ov.querySelector('#maskLabelInput');
    input.focus(); input.select();
    const done = (val) => { ov.remove(); resolve(val); };
    ov.querySelector('#maskLabelOk').addEventListener('click', () => done(input.value));
    ov.querySelector('#maskLabelCancel').addEventListener('click', () => done(null));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') done(input.value);
      if (e.key === 'Escape') done(null);
    });
    ov.addEventListener('click', (e) => { if (e.target === ov) done(null); });
  });
}
function escMaskNM(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

async function maskSelection() {
  const ta = document.getElementById('mailBody');
  const s = ta.selectionStart, e = ta.selectionEnd;
  if (s === e) { showMaskToast(T('cmp_mask_select_first', 'Seleziona prima il testo da mascherare.')); return; }
  const selected = ta.value.substring(s, e).trim();
  if (!selected) return;

  let suggested = 'MASK';
  try {
    const r = await fetch(`${API}/mask/suggest?selection=${encodeURIComponent(selected)}`);
    const d = await r.json();
    suggested = d.label_type || 'MASK';
  } catch {}

  const label = await askLabel(selected, suggested);
  if (label === null) return;
  const labelClean = (label.trim() || 'MASK').toUpperCase().replace(/[^A-Z0-9_]/g, '_');

  try {
    await fetch(`${API}/masks`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, value: selected, label_type: labelClean })
    });
  } catch (err) {
    console.warn('[MASK] salvataggio regola fallito:', err);
  }

  const existing = Object.keys(maskMapping).filter(p => p.startsWith(`[${labelClean}_`)).length;
  const ph = `[${labelClean}_${existing + 1}]`;
  maskMapping[ph] = selected;
  ta.value = ta.value.split(selected).join(ph);
  showMaskToast(`"${selected}" → ${ph} (${T('cmp_mask_rule_saved', 'regola salvata')})`);
}

let _maskToastT = null;
function showMaskToast(msg) {
  let t = document.getElementById('maskToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'maskToast';
    t.style.cssText = 'position:fixed;bottom:70px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.82);color:#fff;padding:8px 16px;border-radius:8px;font-size:12px;z-index:99999;pointer-events:none;transition:opacity 0.2s;';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = '1';
  clearTimeout(_maskToastT);
  _maskToastT = setTimeout(() => { t.style.opacity = '0'; }, 2200);
}

function showMaskCtxMenu(x, y) {
  hideMaskCtxMenu();
  // Rileva se la selezione è un placeholder [X_N] già mascherato
  const ta = document.getElementById('mailBody');
  const selTxt = ta.value.substring(ta.selectionStart, ta.selectionEnd).trim();
  const isPlaceholder = /^\[[A-Z0-9_]+\]$/.test(selTxt) && maskMapping[selTxt] !== undefined;

  const m = document.createElement('div');
  m.id = 'maskCtxMenu';
  m.style.cssText = 'position:fixed;z-index:99999;min-width:190px;background:#fff;border:1px solid rgba(0,0,0,0.14);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.07);padding:5px;font-family:inherit;';
  if (isPlaceholder) {
    m.innerHTML =
      '<div class="mask-ctx-item" data-act="unmask" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer">↩️ ' + escMaskNM(T('cmp_unmask_restore', 'Rimuovi maschera (ripristina)')) + '</div>' +
      '<div class="mask-ctx-item" data-act="delrule" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer;color:#dc2626">🗑 ' + escMaskNM(T('cmp_delete_saved_rule', 'Elimina regola salvata')) + '</div>';
  } else {
    m.innerHTML =
      '<div class="mask-ctx-item" data-act="sel" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer">🔒 ' + escMaskNM(T('cmp_mask_selection', 'Maschera selezione')) + '</div>' +
      '<div class="mask-ctx-item" data-act="all" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer">🛡️ ' + escMaskNM(T('cmp_mask_all', 'Maschera tutto')) + '</div>';
  }
  document.body.appendChild(m);
  const rect = m.getBoundingClientRect();
  m.style.left = Math.max(4, (x+rect.width>window.innerWidth)?x-rect.width:x) + 'px';
  m.style.top  = Math.max(4, (y+rect.height>window.innerHeight)?y-rect.height:y) + 'px';
  m.querySelectorAll('.mask-ctx-item').forEach(it => {
    it.addEventListener('mouseenter', () => it.style.background = 'rgba(176,199,244,0.3)');
    it.addEventListener('mouseleave', () => it.style.background = 'transparent');
  });
  m.addEventListener('click', async (ev) => {
    const it = ev.target.closest('.mask-ctx-item'); if (!it) return;
    const act = it.dataset.act; hideMaskCtxMenu();
    if (act === 'sel') maskSelection();
    else if (act === 'all') maskAll();
    else if (act === 'unmask') unmaskPlaceholder(selTxt);
    else if (act === 'delrule') deleteRuleByValue(maskMapping[selTxt], selTxt);
  });
}
function hideMaskCtxMenu() { document.getElementById('maskCtxMenu')?.remove(); }

// Smaschera: rimette il valore originale al posto del placeholder
function unmaskPlaceholder(ph) {
  const orig = maskMapping[ph];
  if (orig === undefined) return;
  const ta = document.getElementById('mailBody');
  ta.value = ta.value.split(ph).join(orig);
  delete maskMapping[ph];
  showMaskToast(T('cmp_mask_removed', 'Maschera rimossa: {ph} → testo originale').replace('{ph}', ph));
}

// Elimina la regola salvata dal DB (cerca per valore) + smaschera nel testo
async function deleteRuleByValue(value, ph) {
  if (!value) return;
  if (!(await GMDialog.confirm(T('cmp_delete_rule_confirm', 'Eliminare questa regola salvata? Non verrà più mascherata in automatico.'), { danger: true }))) return;
  try {
    const aid = accountId;
    const r = await fetch(`${API}/masks` + (aid ? `?account_id=${aid}` : ''));
    const d = await r.json();
    const rule = (d.masks || []).find(mk => mk.value === value);
    if (rule && rule.id != null) {
      await fetch(`${API}/masks/${rule.id}` + (aid ? `?account_id=${aid}` : ''), { method: 'DELETE' });
    }
  } catch (e) { console.warn('[MASK] delete rule fail', e); }
  if (ph) unmaskPlaceholder(ph);
  showMaskToast(T('cmp_rule_deleted', 'Regola eliminata'));
}

document.getElementById('btnMask')?.addEventListener('click', maskAll);
document.getElementById('mailBody')?.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  showMaskCtxMenu(e.clientX, e.clientY);
});
document.addEventListener('click', (e) => { if (!e.target.closest('#maskCtxMenu')) hideMaskCtxMenu(); });
