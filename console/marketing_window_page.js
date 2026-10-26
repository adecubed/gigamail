// marketing_window_page.js — the script of marketing_window.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it; }
let _bulkRecipients = [];
let _bulkPollingInterval = null;

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── FORMATO TAB ──
document.getElementById('btnBulkHtml')?.addEventListener('click', () => {
  document.getElementById('bulkEditorHtml').style.display = 'flex';
  document.getElementById('bulkEditorPlain').style.display = 'none';
  document.getElementById('btnBulkHtml').classList.add('active');
  document.getElementById('btnBulkPlain').classList.remove('active');
});
document.getElementById('btnBulkPlain')?.addEventListener('click', () => {
  document.getElementById('bulkEditorHtml').style.display = 'none';
  document.getElementById('bulkEditorPlain').style.display = 'flex';
  document.getElementById('btnBulkHtml').classList.remove('active');
  document.getElementById('btnBulkPlain').classList.add('active');
});

// ── UPLOAD FILE ──
document.getElementById('btnBulkUpload')?.addEventListener('click', () => document.getElementById('bulkFileInput')?.click());
document.getElementById('bulkFileInput')?.addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const info = document.getElementById('bulkFileInfo');
  if (info) info.textContent = T('loading', 'Caricamento…');
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`${API}/mail/bulk/upload`, { method:'POST', body:fd });
    const result = await r.json();
    _bulkRecipients = result.recipients || [];
    if (info) info.innerHTML = `<span style="color:#1A7F4B">✓ ${result.count} ${T('win_recipients_loaded', 'destinatari caricati')}</span><br>${T('win_columns', 'Colonne')}: ${result.columns.join(', ')}`;
    const hint = document.getElementById('bulkVarsHint');
    if (hint) hint.textContent = T('win_variables', 'Variabili:') + ' ' + result.columns.map(c => '{'+c+'}').join(', ');
    document.getElementById('btnBulkStart').disabled = false;
  } catch(err) {
    if (info) info.innerHTML = `<span style="color:#C0392B">✗ ${T('error', 'Errore')}: ${err.message}</span>`;
  }
  e.target.value = '';
});

// ── GENERA AI ──
document.getElementById('btnBulkGenerate')?.addEventListener('click', async () => {
  const instruction = document.getElementById('bulkInstruction')?.value?.trim();
  if (!instruction) { alert(T('bulk_write_instructions', 'Scrivi prima le istruzioni per il LLM')); return; }
  const status = document.getElementById('bulkGenerateStatus');
  const btn = document.getElementById('btnBulkGenerate');
  if (status) status.textContent = T('bulk_generating', 'Generazione in corso...');
  if (btn) btn.disabled = true;
  try {
    const subjectHint = document.getElementById('bulkSubject')?.value?.trim() || '';
    const r = await fetch(`${API}/mail/bulk/generate`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ instruction, subject_hint: subjectHint })
    });
    const result = await r.json();
    if (result.subject) {
      const curr = document.getElementById('bulkSubject')?.value?.trim();
      if (!curr || await GMDialog.confirm(`${T('win_replace_subject_confirm', 'Sostituire oggetto con:')}\n"${result.subject}"?`)) {
        document.getElementById('bulkSubject').value = result.subject;
      }
    }
    if (result.html) document.getElementById('bulkBodyHtml').value = result.html;
    if (result.plain) document.getElementById('bulkBodyPlain').value = result.plain;
    if (status) status.textContent = '✓ ' + T('bulk_generated_ok', 'Generato — controlla e modifica prima di inviare');
  } catch(err) {
    if (status) status.textContent = '✗ ' + T('error', 'Errore') + ': ' + err.message;
  } finally {
    if (btn) btn.disabled = false;
  }
});

// ── PREVIEW ──
document.getElementById('btnBulkPreview')?.addEventListener('click', () => {
  if (!_bulkRecipients.length) { alert(window.i18n?window.i18n.t('load_recipients_first'):'Carica prima un file con i destinatari'); return; }
  const first = _bulkRecipients[0];
  const subject = document.getElementById('bulkSubject')?.value || T('no_subject', '(nessun oggetto)');
  const html = document.getElementById('bulkBodyHtml')?.value || '';
  const plain = document.getElementById('bulkBodyPlain')?.value || '';
  const applyVars = (t) => {
    let r = t;
    for (const [k, v] of Object.entries(first)) r = r.replaceAll(`{${k}}`, v || '');
    return r;
  };
  const previewHtml = html ? applyVars(html) : `<pre style="white-space:pre-wrap">${esc(applyVars(plain))}</pre>`;
  const fullHtml = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Preview</title></head><body>
    <div style="padding:16px;background:#eee;font-family:sans-serif;font-size:12px">
      <b>${T('subject_label', 'Oggetto:')}</b> ${esc(applyVars(subject))} &nbsp;|&nbsp; <b>${T('to_label', 'A:')}</b> ${esc(first.email||'')} &nbsp;|&nbsp; ${T('win_n_recipients', '{n} destinatari').replace('{n}', _bulkRecipients.length)}
    </div>${previewHtml}</body></html>`;
  const blob = new Blob([fullHtml], { type:'text/html' });
  window.open(URL.createObjectURL(blob), '_blank', 'width=800,height=640,scrollbars=yes');
});

// ── AVVIA INVIO ──
document.getElementById('btnBulkStart')?.addEventListener('click', async () => {
  if (!_bulkRecipients.length) { alert(T('load_recipients_first', 'Carica prima un file con i destinatari')); return; }
  const subject = document.getElementById('bulkSubject')?.value?.trim();
  if (!subject) { alert(T('insert_subject', 'Inserisci l\'oggetto della mail')); return; }
  const bodyHtml = document.getElementById('bulkBodyHtml')?.value?.trim() || '';
  const bodyPlain = document.getElementById('bulkBodyPlain')?.value?.trim() || '';
  if (!bodyHtml && !bodyPlain) { alert(T('write_body', 'Scrivi il corpo della mail')); return; }
  if (!(await GMDialog.confirm(`${T('win_start_send_confirm', 'Avviare invio a {n} destinatari?').replace('{n}', _bulkRecipients.length)}\n\n${T('subject_label', 'Oggetto:')} ${subject}`))) return;
  try {
    const r = await fetch(`${API}/mail/bulk/start`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        subject, body_html: bodyHtml, body_plain: bodyPlain,
        sleep_min: parseInt(document.getElementById('bulkSleepMin')?.value||'20'),
        sleep_max: parseInt(document.getElementById('bulkSleepMax')?.value||'40'),
        batch_size:50, batch_pause:300, recipients:_bulkRecipients
      })
    });
    if (!r.ok) throw new Error(await r.text());
    setBulkSendingUI(true);
    startBulkPolling();
  } catch(err) { alert(T('win_start_error', 'Errore avvio') + ': ' + err.message); }
});

// ── FERMA INVIO ──
document.getElementById('btnBulkStop')?.addEventListener('click', async () => {
  try {
    await fetch(`${API}/mail/bulk/stop`, { method:'POST' });
  } catch(err) { alert(T('win_stop_error', 'Errore stop') + ': ' + err.message); }
});

function setBulkSendingUI(sending) {
  const btnStart = document.getElementById('btnBulkStart');
  const btnStop  = document.getElementById('btnBulkStop');
  const progress = document.getElementById('bulkProgress');
  if (btnStart) { btnStart.style.display = sending ? 'none' : 'block'; btnStart.disabled = sending; }
  if (btnStop)  btnStop.style.display = sending ? 'block' : 'none';
  if (progress) progress.style.display = sending ? 'flex' : 'none';
}

function startBulkPolling() {
  if (_bulkPollingInterval) clearInterval(_bulkPollingInterval);
  _bulkPollingInterval = setInterval(refreshBulkStatus, 3000);
}

async function refreshBulkStatus() {
  try {
    const r = await fetch(`${API}/mail/bulk/status`);
    const data = await r.json();
    if (!data || data.status === 'idle') {
      if (_bulkPollingInterval) { clearInterval(_bulkPollingInterval); _bulkPollingInterval = null; }
      setBulkSendingUI(false);
      return;
    }
    setBulkSendingUI(true);
    const total = data.total || 0;
    const sent  = data.sent  || 0;
    const pct   = total ? Math.round(sent/total*100) : 0;
    const bar   = document.getElementById('bulkProgressBar');
    const label = document.getElementById('bulkProgressLabel');
    const count = document.getElementById('bulkProgressCount');
    const log   = document.getElementById('bulkLog');
    if (bar)   bar.style.width = pct + '%';
    if (label) label.textContent = data.status === 'running' ? `${T('win_sending_progress', 'Invio in corso…')} ${pct}%` : T('completed_ok', 'Completato');
    if (count) count.textContent = `${sent}/${total}`;
    if (log && data.log) { log.textContent = (data.log||[]).slice(-20).join('\n'); log.scrollTop = log.scrollHeight; }
  } catch {}
}

// ── IMAGE UTILITIES ──────────────────────────────────────────────────────────

let _loadedImages = []; // [{name, dataUrl, mimeType}]
let _selectedImgIdx = null;

function fileToBase64(file) {
  return new Promise((res, rej) => {
    const reader = new FileReader();
    reader.onload = e => res(e.target.result); // data URL
    reader.onerror = rej;
    reader.readAsDataURL(file);
  });
}

function insertImgAtCursor(dataUrl, name) {
  const ta = document.getElementById('bulkBodyHtml');
  if (!ta) return;
  const tag = `<img src="${dataUrl}" alt="${name}" style="max-width:100%;height:auto;display:block;margin:8px auto"/>`;
  const start = ta.selectionStart;
  const end   = ta.selectionEnd;
  ta.value = ta.value.slice(0, start) + tag + ta.value.slice(end);
  ta.selectionStart = ta.selectionEnd = start + tag.length;
  ta.focus();
}

// ── DRAG & DROP sull'editor HTML ──
const editorHtml = document.getElementById('bulkEditorHtml');
const dropOverlay = document.getElementById('dropOverlay');
const bulkBodyHtml = document.getElementById('bulkBodyHtml');

editorHtml?.addEventListener('dragover', (e) => {
  e.preventDefault();
  const hasImg = Array.from(e.dataTransfer.items).some(i => i.type.startsWith('image/'));
  if (hasImg) dropOverlay?.classList.add('visible');
});
editorHtml?.addEventListener('dragleave', (e) => {
  if (!editorHtml.contains(e.relatedTarget)) dropOverlay?.classList.remove('visible');
});
editorHtml?.addEventListener('drop', async (e) => {
  e.preventDefault();
  dropOverlay?.classList.remove('visible');
  const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
  if (!files.length) return;
  for (const file of files) {
    const dataUrl = await fileToBase64(file);
    insertImgAtCursor(dataUrl, file.name);
  }
});

// ── CARICA CARTELLA → IMAGE PICKER ──
document.getElementById('btnLoadFolder')?.addEventListener('click', () => {
  document.getElementById('folderInput')?.click();
});

document.getElementById('folderInput')?.addEventListener('change', async (e) => {
  const files = Array.from(e.target.files).filter(f => f.type.startsWith('image/'));
  if (!files.length) return;
  _loadedImages = [];
  _selectedImgIdx = null;
  const grid = document.getElementById('imgGrid');
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px;color:rgba(0,0,0,0.55)">' + esc(T('win_loading_images', 'Caricamento immagini…')) + '</div>';
  document.getElementById('imgPicker').classList.add('visible');
  document.getElementById('aiImgStatus').textContent = '';
  document.getElementById('btnInsertImg').disabled = true;

  for (const file of files.slice(0, 30)) { // max 30
    const dataUrl = await fileToBase64(file);
    _loadedImages.push({ name: file.name, dataUrl, mimeType: file.type });
  }
  renderImgGrid();
  e.target.value = '';
});

function renderImgGrid(aiPickedIdx = null) {
  const grid = document.getElementById('imgGrid');
  grid.innerHTML = '';
  _loadedImages.forEach((img, idx) => {
    const div = document.createElement('div');
    div.className = 'img-thumb' + (idx === _selectedImgIdx ? ' selected' : '');
    div.innerHTML = `<img src="${img.dataUrl}" loading="lazy"/><div class="img-name">${img.name}</div>${idx === aiPickedIdx ? '<div class="ai-badge">✦ AI</div>' : ''}`;
    div.addEventListener('click', () => {
      _selectedImgIdx = idx;
      grid.querySelectorAll('.img-thumb').forEach(el => el.classList.remove('selected'));
      div.classList.add('selected');
      document.getElementById('btnInsertImg').disabled = false;
    });
    grid.appendChild(div);
  });
}

// ── AI SCEGLIE ──
// Niente LLM interno: la scelta AI dell'immagine passava da una chiamata
// diretta al provider LLM, senza chiave (rotta) e fuori dal modello
// "l'intelligenza e' il tuo agente". Finche' il backend non offre una via
// mediata dall'agente, il bottone spiega e basta.
document.getElementById('btnAiPick')?.addEventListener('click', () => {
  const status = document.getElementById('aiImgStatus');
  const msg = window.i18n ? window.i18n.t('bulk_generate_unavailable')
    : 'Generazione AI non disponibile in questa versione: usa il tuo agente via MCP.';
  if (status) status.textContent = msg;
});

// ── INSERISCI IMMAGINE SCELTA ──
document.getElementById('btnInsertImg')?.addEventListener('click', () => {
  if (_selectedImgIdx === null) return;
  const img = _loadedImages[_selectedImgIdx];
  insertImgAtCursor(img.dataUrl, img.name);
  document.getElementById('imgPicker').classList.remove('visible');
  _selectedImgIdx = null;
});

// ── CHIUDI PICKER ──
document.getElementById('btnPickerClose')?.addEventListener('click', () => {
  document.getElementById('imgPicker').classList.remove('visible');
});

// ── WINDOW CONTROLS ──
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btnClose')?.addEventListener('click',   () => window.marketingWindowAPI?.close());
  document.getElementById('btnMin')?.addEventListener('click',     () => window.marketingWindowAPI?.minimize());
  document.getElementById('btnMax')?.addEventListener('click',     () => window.marketingWindowAPI?.maximize());
  refreshBulkStatus();
});
