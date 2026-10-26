// reply_window_page.js — the script of reply_window.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
const SEND_DELAY = 5000;
let mailData = null;
let attachments = [];
let followupHours = 0;
let sendTimer = null;
let sendRafId = null;
let instructionContext = ''; // testo estratto da file droppato su instruction

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
/** Traduce una chiave, con l'italiano come ripiego naturale. */
function T(chiave, italiano){
  const t = window.i18n && window.i18n.t ? window.i18n.t(chiave) : '';
  return (t && t !== chiave) ? t : italiano;
}

// ── AUTOCOMPLETE replyTo ──────────────────────────────────────────────────────
const replyToInput = document.getElementById('replyTo');
const replyToBox   = document.getElementById('replyToAutocomplete');

replyToInput.addEventListener('input', () => fetchAddressSuggestions(replyToInput.value.trim()));
replyToInput.addEventListener('focus', () => fetchAddressSuggestions(replyToInput.value.trim()));
document.addEventListener('click', (e) => {
  if (!replyToBox.contains(e.target) && e.target !== replyToInput) {
    replyToBox.style.display = 'none';
  }
});

async function fetchAddressSuggestions(q) {
  if (!q || q.length < 1) { replyToBox.style.display = 'none'; return; }
  try {
    const accountId = mailData?.account_id || null;
    const params = new URLSearchParams({ q });
    if (accountId) params.append('account_id', accountId);
    const results = await fetch(`${API}/addresses/search?${params}`).then(r => r.json());
    if (!Array.isArray(results) || !results.length) { replyToBox.style.display = 'none'; return; }
    replyToBox.innerHTML = results.map(r => `
      <div data-email="${esc(r.email)}" style="padding:7px 12px;font-size:11.5px;cursor:pointer;font-family:var(--font);color:rgba(0,0,0,0.75);border-bottom:1px solid rgba(0,0,0,0.05);">
        ${r.name ? `<span style="font-weight:600">${esc(r.name)}</span> — ` : ''}${esc(r.email)}
      </div>`).join('');
    replyToBox.style.display = 'block';
    replyToBox.querySelectorAll('[data-email]').forEach(item => {
      item.addEventListener('mouseenter', () => item.style.background = '#f3e6f0');
      item.addEventListener('mouseleave', () => item.style.background = '');
      item.addEventListener('click', () => {
        replyToInput.value = item.dataset.email;
        replyToBox.style.display = 'none';
      });
    });
  } catch(e) { console.error('autocomplete:', e); }
}

async function applyMailData(data) {
  mailData = data;

  // ── OPZIONE B: rileva i dati sensibili nella mail originale ──
  // NON maschera subito: rileva e salva i candidati. L'utente apre il pannello
  // (click sul badge 🔒), controlla, conferma/toglie, poi GENERA usa il testo
  // mascherato solo per i candidati confermati.
  maskOriginalText = data.body_text || data.bodyPreview || '';
  maskCandidates = [];
  if (maskOriginalText.trim()) {
    try {
      const r = await fetch(`${API}/mask/detect`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: maskOriginalText, account_id: data.account_id || null })
      });
      const d = await r.json();
      // ogni candidato parte CONFERMATO (active=true)
      maskCandidates = (d.candidates || []).map((c, i) => ({
        ...c, index: i, active: true,
      }));
      applyMaskToBody();          // calcola mailData.body_text mascherato
      showMaskBadge(maskCandidates.filter(c => c.active).length);
    } catch (e) {
      console.warn('[MASK] detect fallito:', e);
    }
  }

  // ── MODALITÀ INOLTRO ──────────────────────────────────────
  if (data.mode === 'forward') {
    document.getElementById('replyTo').value      = '';
    document.getElementById('replySubject').value = data.forward_subject || (data.subject ? `Fwd: ${data.subject}` : 'Fwd:');
    document.getElementById('replyText').value    = data.forward_body || '';
    const titleEl = document.querySelector('.tb-title') || document.querySelector('.popup-tb-title');
    if (titleEl) titleEl.textContent = T('forward_cap', 'Inoltra');

    // Scarica e ri-allega gli allegati della mail originale
    const fwdNames = data.forward_attachments || [];
    const srcId = data.forward_src_id, srcAcc = data.forward_src_account, srcFolder = data.forward_src_folder || '';
    if (fwdNames.length && srcId) {
      fwdNames.forEach(async (name) => {
        try {
          const qs = new URLSearchParams({ account_id: srcAcc || '', folder: srcFolder || '' });
          const r = await fetch(`${API}/mail/${encodeURIComponent(srcId)}/attachment/${encodeURIComponent(name)}?${qs}`);
          if (!r.ok) { console.warn('[FORWARD] allegato non scaricato:', name, r.status); return; }
          const blob = await r.blob();
          const b64 = await new Promise((res, rej) => {
            const fr = new FileReader();
            fr.onload = () => res(String(fr.result).split(',')[1]);
            fr.onerror = rej;
            fr.readAsDataURL(blob);
          });
          attachments.push({
            name,
            data_b64: b64,
            type: blob.type || 'application/octet-stream',
            size: blob.size,
            isImage: (blob.type || '').startsWith('image/'),
            dataUrl: null,
          });
          renderAttachments();
        } catch (e) { console.warn('[FORWARD] errore allegato', name, e); }
      });
    }

    mailData.id = null;  // non agganciare il thread originale
    document.getElementById('replyTo').focus();
    return;
  }

  // ── MODALITÀ RISPOSTA (default) ───────────────────────────
  document.getElementById('replyTo').value      = data.sender  || '';
  document.getElementById('replySubject').value = data.subject
    ? (/^re:/i.test(data.subject) ? data.subject : `Re: ${data.subject}`)
    : '';
  // Popola CC per reply-all
  if (data.replyAll && Array.isArray(data.ccAddrs) && data.ccAddrs.length) {
    document.getElementById('replyCc').value = data.ccAddrs.join(', ');
  }
  if (data.instruction) {
    document.getElementById('instruction').value = data.instruction;
    setTimeout(() => document.getElementById('btnGenerate').click(), 300);
  } else {
    document.getElementById('replyText').focus();
  }
}

if (window.replyWindowAPI) {
  window.replyWindowAPI.onLoadReply((data) => applyMailData(data));
  window.replyWindowAPI.ready?.();
}

document.getElementById('btnClose').addEventListener('click', () => window.replyWindowAPI?.close());
document.getElementById('btnMin').addEventListener('click',   () => window.replyWindowAPI?.minimize());
document.getElementById('btnMax').addEventListener('click',   () => window.replyWindowAPI?.maximize());

// ── ALLEGATI ──────────────────────────────────────────────────────────────────
document.getElementById('btnAttach').addEventListener('click', () => document.getElementById('fileInput').click());
document.getElementById('fileInput').addEventListener('change', (e) => {
  for (const file of Array.from(e.target.files||[])) addFileAsAttachment(file);
  e.target.value = '';
});

function isImage(file) {
  return file.type.startsWith('image/');
}

function addFileAsAttachment(file) {
  const reader = new FileReader();
  reader.onload = ev => {
    const data_b64 = ev.target.result.split(',')[1];
    attachments.push({
      name: file.name,
      data_b64,
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
const bodyWrap = document.getElementById('replyBodyWrap');
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
  for (const file of Array.from(e.dataTransfer.files || [])) {
    addFileAsAttachment(file);
  }
});

// ── CTRL+V — INCOLLA IMMAGINI DAGLI APPUNTI ───────────────────────────────────
document.getElementById('replyText').addEventListener('paste', (e) => {
  const items = e.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const file = item.getAsFile();
      if (file) {
        // Dai un nome sensato
        const ext = item.type.split('/')[1] || 'png';
        const named = new File([file], `screenshot_${Date.now()}.${ext}`, { type: item.type });
        addFileAsAttachment(named);
      }
    }
  }
});

// ── DRAG & DROP SULL'ISTRUZIONE AI ────────────────────────────────────────────
const instrEl = document.getElementById('instruction');
const ctxBadge = document.getElementById('ctxBadge');

instrEl.addEventListener('dragover', (e) => {
  e.preventDefault();
  instrEl.classList.add('drag-over');
});
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
    instrEl.placeholder = T('cmp_ai_instruction_opt_ph', 'Istruzione AI (opz.)…');
  } catch(err) {
    instrEl.placeholder = T('cmp_extract_error_retry', 'Errore estrazione — riprova');
    console.error(err);
  }
});

// Click su badge → rimuovi contesto
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

// Enter su instruction triggera GENERA
instrEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); document.getElementById('btnGenerate').click(); }
});

// ── GENERA ────────────────────────────────────────────────────────────────────
document.getElementById('btnGenerate').addEventListener('click', async () => {
  if (!mailData) { document.getElementById('replyText').value = T('cmp_mail_data_not_loaded', 'Errore: dati mail non caricati.'); return; }
  const btn = document.getElementById('btnGenerate');
  const ta  = document.getElementById('replyText');
  btn.textContent = '…'; btn.disabled = true; ta.value = T('cmp_generating_draft', 'Generazione bozza…');
  try {
    const baseInstruction = instrEl.value.trim();
    // Se c'è contesto da file, appendilo all'istruzione
    const instruction = instructionContext
      ? `${baseInstruction}\n\n[CONTESTO FILE]\n${instructionContext.slice(0, 3000)}`
      : baseInstruction;

    let url = `${API}/mail/${encodeURIComponent(mailData.id)}/smart_draft`;
    const params = [];
    if (mailData.account_id) params.push(`account_id=${mailData.account_id}`);
    if (mailData.folder)     params.push(`folder=${encodeURIComponent(mailData.folder)}`);
    if (params.length) url += '?' + params.join('&');
    const r = await fetch(url, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ instruction, body_text:mailData.body_text||mailData.bodyPreview||'', subject:mailData.subject||'', sender:mailData.sender||'' })
    });
    const data = await r.json();
    // Un errore del server (agente non collegato, login scaduto) va detto:
    // un campo vuoto sembra una bozza che non arriva mai.
    if (!r.ok) throw (data.detail || `HTTP ${r.status}`);
    const guard = document.getElementById('guardBanner');
    guard.style.display = 'none';
    document.getElementById('suggestedBanner').style.display = 'none';
    if (data.blocked) {
      // Il presidio ha fermato la mail PRIMA della generazione: non c'e'
      // nessuna bozza da mostrare, e non deve sembrare che l'app si sia
      // rotta. Si dice cosa e' stato riconosciuto e si mostra il passaggio.
      // I motivi arrivano come codici: qui diventano la lingua di chi guarda.
      const motivi = (data.reasons || [])
        .map(m => `• ${esc(T('guard_' + m, m))}`).join('<br/>');
      guard.innerHTML = `<div class="gb-title">⚠ ${esc(T('guard_title',
        "NESSUNA BOZZA: LA MAIL DA' ORDINI ALL'ASSISTENTE"))}</div>
        <div class="gb-why">${motivi || esc(T('guard_generic',
          "testo rivolto all'assistente"))}</div>
        <div class="gb-quote">${esc(data.passage || '')}</div>`;
      guard.style.display = 'block';
      ta.value = '';
      window._lastGeneratedDraft = '';
      btn.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('zap', 14) : '') + ' ' + T('generate', 'GENERA'); btn.disabled = false;
      return;
    }
    ta.value = data.draft || data.text || '';
    window._lastGeneratedDraft = ta.value;
    if (data.suggested_attachments?.length) {
      const banner = document.getElementById('suggestedBanner');
      const items = data.suggested_attachments.map((a,i) =>
        `<label style="display:flex;align-items:center;gap:6px;margin-top:4px;cursor:pointer">
          <input type="checkbox" data-path="${esc(a.path)}" data-name="${esc(a.name)}" checked/>
          <span style="font-size:11px;font-family:monospace">${esc(a.name)}</span>
         </label>`).join('');
      banner.innerHTML = `<div style="font-size:10px;font-weight:700;letter-spacing:1.5px;color:rgba(26,80,180,0.8);margin-bottom:3px">📎 ${esc(T('suggested_attachments','ALLEGATI SUGGERITI'))}</div>${items}
        <button id="btnAddSuggested" style="margin-top:6px;padding:4px 10px;border-radius:6px;background:rgba(26,108,245,0.1);border:1px solid rgba(26,108,245,0.2);color:var(--accent);font-size:10px;cursor:pointer">+ ${esc(T('add_selected','AGGIUNGI SELEZIONATI'))}</button>`;
      banner.style.display = 'block';
      document.getElementById('btnAddSuggested')?.addEventListener('click', addSuggestedAttachments);
    }
  } catch(e) { ta.value = `${T('error', 'Errore')}: ${e}`; }
  btn.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('zap', 14) : '') + ' ' + T('generate', 'GENERA'); btn.disabled = false;
});

async function addSuggestedAttachments() {
  const checks = document.querySelectorAll('#suggestedBanner input[type=checkbox]:checked');
  for (const cb of checks) {
    try {
      const r = await fetch(`${API}/files/local?path=${encodeURIComponent(cb.dataset.path)}`);
      const f = await r.json();
      attachments.push({ name:f.name, data_b64:f.data_b64, type:f.type||'application/octet-stream', size:f.size, isImage:false });
    } catch {}
  }
  renderAttachments();
  document.getElementById('suggestedBanner').style.display = 'none';
}

// ── INVIA con delay 5s ────────────────────────────────────────────────────────
function resetSendBtn() {
  const label  = document.getElementById('sendLabel');
  const circle = document.getElementById('sendCircle');
  const btn    = document.getElementById('btnSend');
  if (sendTimer) { clearTimeout(sendTimer); sendTimer = null; }
  if (sendRafId) { cancelAnimationFrame(sendRafId); sendRafId = null; }
  btn.disabled = false;
  label.textContent = T('send', 'Invia ↑');
  circle.style.setProperty('--pct', '0%');
}

async function execSend() {
  const btn    = document.getElementById('btnSend');
  const label  = document.getElementById('sendLabel');
  const circle = document.getElementById('sendCircle');
  const to      = document.getElementById('replyTo').value.trim();
  const subject = document.getElementById('replySubject').value.trim();
  const body    = document.getElementById('replyText').value;
  const cc      = document.getElementById('replyCc').value.trim();

  btn.disabled = true; label.textContent = T('cmp_sending_btn', 'Invio…');
  circle.style.setProperty('--pct', '100%');
  try {
    let url = `${API}/mail/send`;
    if (mailData.account_id) url += `?account_id=${mailData.account_id}`;
    // Manda attachments senza il campo dataUrl (non serve al backend)
    const attachmentsClean = attachments.map(({dataUrl, isImage, ...rest}) => rest);
    const response = await fetch(url, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        to,
        subject,
        body,
        reply_to_id:    mailData.id,
        cc:             cc ? [cc] : [],
        attachments:    attachmentsClean,
        original_draft: window._lastGeneratedDraft || '',
        instruction:    document.getElementById('instruction')?.value?.trim() || '',
      })
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
      alert(T('cmp_dryrun_no_send', 'Simulazione: nessuna mail inviata.'));
      resetSendBtn();
      return;
    }
    if (followupHours > 0) {
      try {
        await window.replyWindowAPI?.followupSave({ message_id:mailData.id||null, account_id:mailData.account_id||0, subject, to_addr:to, hours:followupHours });
      } catch (e) { console.warn('followupSave:', e); }
    }
    window.replyWindowAPI?.close();
  } catch(e) {
    alert(T('cmp_send_error', 'Errore invio') + ': ' + e);
    resetSendBtn();
  }
}

document.getElementById('btnSend').addEventListener('click', () => {
  if (!mailData) return;
  if (sendTimer) { resetSendBtn(); return; }
  const to   = document.getElementById('replyTo').value.trim();
  const body = document.getElementById('replyText').value;
  if (!to || !body) { alert(T('cmp_fill_to_body', 'Compila A e il testo')); return; }
  const label  = document.getElementById('sendLabel');
  const circle = document.getElementById('sendCircle');
  label.textContent = '✕ ' + T('cancel', 'Annulla');
  circle.style.setProperty('--pct', '0%');
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
// MASKER — privacy dati sensibili (Opzione B: pannello di controllo)
// ══════════════════════════════════════════════════════════════
let maskOriginalText = '';   // corpo originale in chiaro (mai inviato così)
let maskCandidates = [];     // [{type,label_prefix,value,start,end,active,index}]
let maskMapping = {};        // placeholder -> valore (per unmask bozza)

function _maskAccountId() {
  return (mailData && mailData.account_id) || null;
}

// Ricostruisce mailData.body_text mascherando SOLO i candidati attivi.
// Questo è ciò che GENERA invierà all'LLM.
function applyMaskToBody() {
  let text = maskOriginalText;
  maskMapping = {};
  const counters = {};
  // ordina per lunghezza valore desc per evitare sostituzioni parziali
  const active = maskCandidates.filter(c => c.active)
    .sort((a, b) => b.value.length - a.value.length);
  const valToPh = {};
  for (const c of active) {
    if (valToPh[c.value]) continue;
    const p = c.label_prefix || 'MASK';
    counters[p] = (counters[p] || 0) + 1;
    const ph = `[${p}_${counters[p]}]`;
    valToPh[c.value] = ph;
    maskMapping[ph] = c.value;
  }
  for (const val of Object.keys(valToPh).sort((a, b) => b.length - a.length)) {
    text = text.split(val).join(valToPh[val]);
  }
  if (mailData) mailData.body_text = text;
}

function showMaskBadge(n) {
  const btn = document.getElementById('btnMask');
  if (!btn) return;
  btn.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('lock', 15) : '') + (n > 0 ? ` ${n}` : '');
  btn.title = n > 0
    ? T('cmp_mask_badge_n', '{n} dati sensibili mascherati. Click per controllare.').replace('{n}', n)
    : T('cmp_mask_badge_none', 'Nessun dato sensibile rilevato. Click per gestire.');
  btn.style.background = n > 0 ? 'rgba(46,160,67,0.18)' : '';
}

// ── Pannello di controllo dati mascherati ──
function openMaskPanel() {
  closeMaskPanel();
  const panel = document.createElement('div');
  panel.id = 'maskPanel';
  panel.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:99999;width:min(560px,94vw);max-height:82vh;display:flex;flex-direction:column;background:#fff;border:1px solid rgba(0,0,0,0.14);border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,0.4);font-family:inherit;overflow:hidden;';

  panel.innerHTML = `
    <div style="padding:12px 16px;background:#f3e6f0;display:flex;align-items:center;justify-content:space-between;flex-shrink:0">
      <strong style="font-size:13px">🔒 ${escMask(T('cmp_mask_panel_title', 'Controlla i dati prima di generare'))}</strong>
      <button id="maskPanelClose" style="border:none;background:rgba(255,255,255,0.4);border-radius:6px;width:24px;height:24px;cursor:pointer;font-weight:700">✕</button>
    </div>
    <div style="font-size:11px;color:rgba(0,0,0,0.6);padding:8px 14px 4px;flex-shrink:0">${escMask(T('cmp_mask_panel_intro', 'Mail originale (i dati mascherati appaiono come {ph}). Seleziona altro testo qui sotto e usa il tasto destro per mascherarlo.')).replace('{ph}', '<b>[' + escMask(T('cmp_mask_label_word', 'ETICHETTA')) + '_N]</b>')}</div>
    <div id="maskOrigBox" style="margin:0 14px;padding:10px 12px;background:rgba(248,250,252,0.9);border:1px solid rgba(0,0,0,0.12);border-radius:8px;font-size:12px;line-height:1.5;white-space:pre-wrap;overflow:auto;flex:1;min-height:120px;user-select:text;"></div>
    <div style="font-size:11px;color:rgba(0,0,0,0.6);padding:8px 14px 4px;flex-shrink:0">${escMask(T('cmp_mask_panel_check_hint', 'Spunta = mascherato (non esce). Togli per lasciare in chiaro.'))}</div>
    <div id="maskList" style="margin:0 14px 12px;border:1px solid rgba(0,0,0,0.1);border-radius:8px;overflow:auto;max-height:160px;flex-shrink:0"></div>
  `;
  document.body.appendChild(panel);
  panel.querySelector('#maskPanelClose').addEventListener('click', closeMaskPanel);

  renderMaskPanel();

  // selezione + tasto destro nel testo originale
  const box = panel.querySelector('#maskOrigBox');
  box.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const sel = (window.getSelection().toString() || '').trim();
    if (sel) showMaskCtxMenu(e.clientX, e.clientY, sel);
  });
}

// Decodifica entità HTML per la visualizzazione
function decodeEntities(s) {
  const t = document.createElement('textarea');
  t.innerHTML = s || '';
  return t.value;
}

// Testo originale con i placeholder dei candidati ATTIVI (per il riquadro)
function maskedDisplayText() {
  let text = decodeEntities(maskOriginalText);
  const counters = {};
  const active = maskCandidates.filter(c => c.active)
    .sort((a, b) => b.value.length - a.value.length);
  const valToPh = {};
  for (const c of active) {
    if (valToPh[c.value]) continue;
    const p = c.label_prefix || 'MASK';
    counters[p] = (counters[p] || 0) + 1;
    valToPh[c.value] = `[${p}_${counters[p]}]`;
  }
  for (const val of Object.keys(valToPh).sort((a, b) => b.length - a.length)) {
    text = text.split(decodeEntities(val)).join(valToPh[val]);
  }
  return text;
}

function renderMaskPanel() {
  const box = document.getElementById('maskOrigBox');
  const list = document.getElementById('maskList');
  if (box) box.textContent = maskedDisplayText();
  if (list) {
    list.innerHTML = maskCandidates.map(c => {
      const checked = c.active ? 'checked' : '';
      const trash = (c.source === 'user' && c.mask_id)
        ? `<button data-del-mask="${c.mask_id}" title="${escMask(T('cmp_delete_rule_title', 'Elimina regola salvata (non maschera più in futuro)'))}" style="border:none;background:none;cursor:pointer;font-size:13px;opacity:0.55;flex-shrink:0">🗑</button>`
        : '';
      return `<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid rgba(0,0,0,0.06);font-size:12.5px">
        <input type="checkbox" data-mask-idx="${c.index}" ${checked} style="width:16px;height:16px;flex-shrink:0;cursor:pointer"/>
        <span style="font-weight:700;color:#2ea043;flex-shrink:0;min-width:78px">[${c.label_prefix}_]</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escMask(c.value)}</span>
        <span style="font-size:10px;color:rgba(0,0,0,0.55)">${escMask(c.source==='user' ? T('cmp_mask_source_user', 'tua regola') : T('cmp_mask_source_auto', 'auto'))}</span>
        ${trash}
      </div>`;
    }).join('') || '<div style="padding:14px;color:rgba(0,0,0,0.55);font-size:12px;text-align:center">' + escMask(T('cmp_mask_list_empty', 'Nessun dato rilevato. Seleziona testo sopra e tasto destro per mascherare.')) + '</div>';
    list.querySelectorAll('input[data-mask-idx]').forEach(cb => {
      cb.addEventListener('change', () => {
        const idx = parseInt(cb.dataset.maskIdx, 10);
        const cand = maskCandidates.find(c => c.index === idx);
        if (cand) cand.active = cb.checked;
        applyMaskToBody();
        showMaskBadge(maskCandidates.filter(c => c.active).length);
        renderMaskPanel();
      });
    });
    // Cestino: elimina la regola salvata dal DB + toglie il candidato
    list.querySelectorAll('button[data-del-mask]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const mid = btn.dataset.delMask;
        if (!(await GMDialog.confirm(T('cmp_delete_rule_confirm', 'Eliminare questa regola salvata? Non verrà più mascherata in automatico.'), { danger: true }))) return;
        try {
          const aid = _maskAccountId();
          await fetch(`${API}/masks/${mid}` + (aid ? `?account_id=${aid}` : ''), { method: 'DELETE' });
        } catch (e) { console.warn('[MASK] delete fail', e); }
        // rimuovi dai candidati e ricalcola
        maskCandidates = maskCandidates.filter(c => String(c.mask_id) !== String(mid));
        applyMaskToBody();
        showMaskBadge(maskCandidates.filter(c => c.active).length);
        renderMaskPanel();
      });
    });
  }
}

function closeMaskPanel() { document.getElementById('maskPanel')?.remove(); }
function escMask(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// Dialog custom per l'etichetta (Electron blocca prompt())
function askLabel(selected, suggested) {
  return new Promise((resolve) => {
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;z-index:100001;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;';
    ov.innerHTML = `
      <div style="background:#fff;border:1px solid rgba(0,0,0,0.14);border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,0.4);width:min(360px,90vw);padding:16px;font-family:inherit">
        <div style="font-size:13px;margin-bottom:4px">${escMask(T('cmp_mask', 'Maschera'))} <b>${escMask(selected)}</b></div>
        <div style="font-size:11px;color:rgba(0,0,0,0.6);margin-bottom:8px">${escMask(T('cmp_mask_label_editable', 'Etichetta (modificabile):'))}</div>
        <input id="maskLabelInput" type="text" value="${escMask(suggested)}" style="width:100%;padding:8px 10px;border:1.5px solid rgba(0,0,0,0.4);border-radius:8px;font-size:13px;font-family:inherit;outline:none;box-sizing:border-box"/>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button id="maskLabelCancel" style="padding:7px 14px;border:1px solid rgba(0,0,0,0.2);background:#fff;border-radius:8px;cursor:pointer;font-size:12px">${escMask(T('cancel', 'Annulla'))}</button>
          <button id="maskLabelOk" style="padding:7px 14px;border:none;background:#f3e6f0;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600">${escMask(T('cmp_mask', 'Maschera'))}</button>
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

// Maschera una selezione del testo ORIGINALE (dal pannello) + salva regola
async function maskSelection(selectedText) {
  const selected = (selectedText || '').trim();
  if (!selected) return;
  let suggested = 'MASK';
  try {
    const r = await fetch(`${API}/mask/suggest?selection=${encodeURIComponent(selected)}`);
    suggested = (await r.json()).label_type || 'MASK';
  } catch {}
  const label = await askLabel(selected, suggested);
  if (label === null) return;
  const lab = (label.trim() || 'MASK').toUpperCase().replace(/[^A-Z0-9_]/g, '_');
  try {
    await fetch(`${API}/masks`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ account_id:_maskAccountId(), value:selected, label_type:lab })
    });
  } catch(err){ console.warn('[MASK] save rule fail', err); }
  // aggiungi come candidato attivo (così entra nella lista e nel body)
  const newIdx = (maskCandidates.reduce((m,c)=>Math.max(m,c.index),-1)) + 1;
  maskCandidates.push({ type:lab, label_prefix:lab, value:selected, active:true, index:newIdx, source:'user' });
  applyMaskToBody();
  showMaskBadge(maskCandidates.filter(c=>c.active).length);
  renderMaskPanel();
}

function showMaskCtxMenu(x, y, selectedText) {
  hideMaskCtxMenu();
  const m = document.createElement('div');
  m.id = 'maskCtxMenu';
  m.style.cssText = 'position:fixed;z-index:100000;min-width:180px;background:#fff;border:1px solid rgba(0,0,0,0.14);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.07);padding:5px;';
  m.innerHTML = '<div class="mask-ctx-item" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer">🔒 ' + escMask(T('cmp_mask_selection', 'Maschera selezione')) + '</div>';
  document.body.appendChild(m);
  const rect = m.getBoundingClientRect();
  m.style.left = Math.max(4,(x+rect.width>window.innerWidth)?x-rect.width:x)+'px';
  m.style.top  = Math.max(4,(y+rect.height>window.innerHeight)?y-rect.height:y)+'px';
  m.querySelector('.mask-ctx-item').addEventListener('click', () => { hideMaskCtxMenu(); maskSelection(selectedText); });
}
function hideMaskCtxMenu(){ document.getElementById('maskCtxMenu')?.remove(); }

document.getElementById('btnMask')?.addEventListener('click', openMaskPanel);
document.addEventListener('click', (e) => { if (!e.target.closest('#maskCtxMenu')) hideMaskCtxMenu(); });
