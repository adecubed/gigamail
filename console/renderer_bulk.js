function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key) : it; }
// renderer_bulk.js — Bulk mail (invio massivo)
// Caricato prima di renderer.js in index_v2.html

async function generateBulkCopy() {
  const instruction = byId('bulkInstruction')?.value?.trim();
  if (!instruction) { showToast(T('bulk_write_instructions','Scrivi prima le istruzioni per il LLM')); return; }

  const status = byId('bulkGenerateStatus');
  const btn = byId('btnBulkGenerate');
  if (status) status.textContent = T('bulk_generating','Generazione in corso...');
  if (btn) btn.disabled = true;

  try {
    const subjectHint = byId('bulkSubject')?.value?.trim() || '';
    const result = await api.bulkGenerate(instruction, subjectHint);

    if (result.subject && !byId('bulkSubject')?.value?.trim()) {
      if (byId('bulkSubject')) byId('bulkSubject').value = result.subject;
    } else if (result.subject) {
      // Proponi oggetto se già c'è qualcosa
      if (confirm(`Sostituire oggetto con:\n"${result.subject}"?`)) {
        if (byId('bulkSubject')) byId('bulkSubject').value = result.subject;
      }
    }
    if (result.html && byId('bulkBodyHtml')) byId('bulkBodyHtml').value = result.html;
    if (result.plain && byId('bulkBodyPlain')) byId('bulkBodyPlain').value = result.plain;

    if (status) status.textContent = '✓ ' + T('bulk_generated_ok','Generato — controlla e modifica prima di inviare');
    showToast(T('bulk_draft_generated','Bozza generata!'));
  } catch(err) {
    if (status) status.textContent = '✗ ' + T('error','Errore') + ': ' + err.message;
    showToast(T('error','Errore') + ': ' + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function initBulkTab() {
  // Collega eventi agli elementi HTML della tab MARKETING MAIL
  byId('btnBulkUpload')?.addEventListener('click', () => byId('bulkFileInput')?.click());
  byId('bulkFileInput')?.addEventListener('change', handleBulkFileUpload);
  byId('btnBulkGenerate')?.addEventListener('click', generateBulkCopy);

  byId('btnBulkHtml')?.addEventListener('click', () => {
    byId('bulkEditorHtml').style.display = 'flex';
    byId('bulkEditorPlain').style.display = 'none';
    byId('btnBulkHtml').style.borderBottom = '2px solid var(--blue)';
    byId('btnBulkPlain').style.borderBottom = '';
  });
  byId('btnBulkPlain')?.addEventListener('click', () => {
    byId('bulkEditorHtml').style.display = 'none';
    byId('bulkEditorPlain').style.display = 'flex';
    byId('btnBulkHtml').style.borderBottom = '';
    byId('btnBulkPlain').style.borderBottom = '2px solid var(--blue)';
  });

  byId('btnBulkPreview')?.addEventListener('click', showBulkPreview);
  byId('btnBulkStart')?.addEventListener('click', startBulkSend);
  byId('btnBulkStop')?.addEventListener('click', stopBulkSend);

  // Polling se c'è già un invio in corso
  refreshBulkStatus();
}


async function handleBulkFileUpload(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const info = byId('bulkFileInfo');
  if (info) info.textContent = T('loading','Caricamento...');
  try {
    const result = await api.bulkUpload(file);
    _bulkRecipients = result.recipients || [];
    if (info) info.innerHTML = `<span style="color:#1A7F4B;">✓ ${result.count} destinatari caricati</span><br>Colonne: ${result.columns.join(', ')}`;
    // Aggiorna hint variabili
    const hint = byId('bulkVarsHint');
    if (hint) hint.textContent = 'Variabili disponibili: ' + result.columns.map(c => '{' + c + '}').join(', ');
    // Abilita avvio
    const btnStart = byId('btnBulkStart');
    if (btnStart) btnStart.disabled = false;
    e.target.value = '';
  } catch(err) {
    if (info) info.innerHTML = `<span style="color:#C0392B;">✗ Errore: ${err.message}</span>`;
  }
}

function showBulkPreview() {
  if (!_bulkRecipients.length) { showToast(T('load_recipients_first','Carica prima un file con i destinatari')); return; }
  const first = _bulkRecipients[0];
  const subject = byId('bulkSubject')?.value || T('no_subject','(nessun oggetto)');
  const html = byId('bulkBodyHtml')?.value || '';
  const plain = byId('bulkBodyPlain')?.value || '';

  // Applica variabili
  const applyVars = (t) => {
    let r = t;
    for (const [k, v] of Object.entries(first)) r = r.replaceAll(`{${k}}`, v || '');
    if (r.includes('{nome}')) r = r.replaceAll('{nome}', 'Cliente');
    return r;
  };

  const previewHtml = html ? applyVars(html) : `<pre style="font-family:inherit;white-space:pre-wrap">${esc(applyVars(plain))}</pre>`;
  const fullHtml = `<!DOCTYPE html><html><head><meta charset="UTF-8">
    <title>Preview — ${esc(applyVars(subject))}</title>
    <style>body{font-family:Arial,sans-serif;background:#FAF8F5;margin:0;padding:0}
    .hdr{padding:16px 24px;background:#fff;border-bottom:2px solid #2B5CE6}
    .hdr h3{margin:0 0 4px;font-size:16px;color:#1A1614}
    .hdr p{margin:0;font-size:11px;color:#8A8280;font-family:monospace}
    .body{padding:24px}</style></head><body>
    <div class="hdr"><h3>${esc(applyVars(subject))}</h3>
    <p>A: ${esc(first.email || '')} | Preview destinatario 1 di ${_bulkRecipients.length}</p></div>
    <div class="body">${previewHtml}</div></body></html>`;

  const blob = new Blob([fullHtml], { type: 'text/html' });
  window.open(URL.createObjectURL(blob), '_blank', 'width=800,height=640,scrollbars=yes');
}

async function startBulkSend() {
  if (!_bulkRecipients.length) { showToast(T('load_recipients_first','Carica prima un file con i destinatari')); return; }
  const subject = byId('bulkSubject')?.value?.trim();
  if (!subject) { showToast(T('insert_subject',"Inserisci l'oggetto della mail")); return; }
  const bodyHtml = byId('bulkBodyHtml')?.value?.trim() || '';
  const bodyPlain = byId('bulkBodyPlain')?.value?.trim() || '';
  if (!bodyHtml && !bodyPlain) { showToast(T('write_body','Scrivi il corpo della mail')); return; }

  const sleepMin = parseInt(byId('bulkSleepMin')?.value || '20');
  const sleepMax = parseInt(byId('bulkSleepMax')?.value || '40');

  if (!confirm(`Avviare invio a ${_bulkRecipients.length} destinatari?\n\nOggetto: ${subject}\n\nL'invio girerà in background. Puoi chiudere questa finestra.`)) return;

  try {
    await api.bulkStart({
      subject,
      body_html: bodyHtml,
      body_plain: bodyPlain,
      sleep_min: sleepMin,
      sleep_max: sleepMax,
      batch_size: 50,
      batch_pause: 300,
      recipients: _bulkRecipients,
    }, activeAccountId);

    showToast(T('bulk_started','Invio bulk avviato!'));
    setBulkSendingUI(true);
    startBulkPolling();
  } catch(err) {
    showToast(T('error','Errore') + ': ' + err.message);
  }
}

async function stopBulkSend() {
  try {
    await api.bulkStop();
    showToast(T('bulk_stop_requested','Stop richiesto — attendi completamento mail in corso'));
  } catch(err) {
    showToast(T('error','Errore') + ': ' + err.message);
  }
}

function setBulkSendingUI(sending) {
  const btnStart = byId('btnBulkStart');
  const btnStop = byId('btnBulkStop');
  const progress = byId('bulkProgress');
  if (btnStart) { btnStart.style.display = sending ? 'none' : 'block'; btnStart.disabled = sending; }
  if (btnStop) btnStop.style.display = sending ? 'block' : 'none';
  if (progress) progress.style.display = sending ? 'flex' : 'none';
}

function startBulkPolling() {
  if (_bulkPollingInterval) clearInterval(_bulkPollingInterval);
  _bulkPollingInterval = setInterval(refreshBulkStatus, 2000);
}

async function refreshBulkStatus() {
  try {
    const s = await api.bulkStatus();

    if (s.running || s.sent > 0 || s.failed > 0) {
      setBulkSendingUI(s.running);
      if (!s.running && _bulkPollingInterval) {
        clearInterval(_bulkPollingInterval);
        _bulkPollingInterval = null;
      }

      // Progress bar
      const total = s.total || 1;
      const done = s.sent + s.failed + s.skipped;
      const pct = Math.round((done / total) * 100);
      const bar = byId('bulkProgressBar');
      const label = byId('bulkProgressLabel');
      const count = byId('bulkProgressCount');
      if (bar) bar.style.width = pct + '%';
      if (label) {
        if (s.running) label.textContent = s.current_email ? `${T('sending_to','Invio a')}: ${s.current_email}` : T('in_progress','In corso...');
        else label.textContent = s.error ? `✗ ${T('error','Errore')}: ${s.error}` : '✓ ' + T('completed_ok','Completato');
      }
      if (count) count.textContent = `${s.sent}/${s.total} inviati | ${s.failed} falliti | ${s.skipped} saltati`;

      // Log
      const logEl = byId('bulkLog');
      if (logEl && s.log?.length) {
        logEl.innerHTML = s.log.slice(-50).map(l =>
          `<div style="border-bottom:1px solid #F4F2EE;padding:2px 0;${l.includes('SENT') ? 'color:#1A7F4B' : l.includes('FAIL') ? 'color:#C0392B' : ''}">${esc(l)}</div>`
        ).join('');
        logEl.scrollTop = logEl.scrollHeight;
      }
    }
  } catch(err) {
    console.error('bulk status error:', err);
  }
}



// ── FOLDER IDENTITY MODAL ────────────────────────────────────────────────────
