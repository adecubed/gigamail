function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it; }
// renderer_identity.js — Identity modals (account e cartella)
// Caricato prima di renderer.js in index_v2.html

async function openFolderIdentityModal(accountId, folderId, folderLabel) {
  const existing = document.getElementById('folderIdentityModal');
  if (existing) existing.remove();

  let identity = { who_am_i: '', what_i_do: '', tone: '', key_info: '', file_paths: [] };
  try { identity = await api.getFolderIdentity(accountId, folderId); } catch(e) {}

  const overlay = document.createElement('div');
  overlay.id = 'folderIdentityModal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(26,22,20,0.35);';

  overlay.innerHTML = `
    <div style="background:#FFFFFF;border:1px solid #E2DDD6;border-top:3px solid #8A5CE6;border-radius:4px;width:min(600px,94vw);max-height:88vh;display:flex;flex-direction:column;box-shadow:0 8px 40px rgba(43,92,230,0.13);overflow:hidden;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-bottom:1px solid #E2DDD6;background:#FAF8F5;flex-shrink:0;">
        <div>
          <div style="font-size:10px;font-weight:600;letter-spacing:2px;color:#8A8280;font-family:var(--mono)">${T('identity_folder','IDENTITY CARTELLA')}</div>
          <div style="font-size:12px;color:#8A5CE6;margin-top:2px;">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('folder', 12) : '')} ${esc(folderLabel)}</div>
          <div style="font-size:10px;color:#8A8280;margin-top:1px;font-family:var(--mono)">${T('identity_folder_sub','sovrascrive identity account per questa cartella')}</div>
        </div>
        <button id="btnCloseFolderIdentity" style="background:none;border:none;color:#8A8280;font-size:16px;cursor:pointer;padding:2px 8px;">✕</button>
      </div>
      <div style="flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:14px;">
        <div>
          <label class="field-label">${T('who_here','CHI SEI IN QUESTA CARTELLA')}</label>
          <input id="fiWhoAmI" type="text" placeholder="${T('who_ph','Lascia vuoto per usare identity account')}"
            value="${esc(identity.who_am_i||'')}"
            style="width:100%;margin-top:5px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('what_you_do','COSA FAI')}</label>
          <input id="fiWhatIDo" type="text" placeholder="${T('whatdo_ph','Es: Rispondo a lead Idealista')}"
            value="${esc(identity.what_i_do||'')}"
            style="width:100%;margin-top:5px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('tone','TONO')}</label>
          <input id="fiTone" type="text" placeholder="${T('tone_ph','Es: Commerciale, veloce, diretto')}"
            value="${esc(identity.tone||'')}"
            style="width:100%;margin-top:5px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('folder_info','INFO SPECIFICHE CARTELLA')}</label>
          <textarea id="fiKeyInfo" rows="4" placeholder="${T('folder_info_ph','Info specifiche per questa cartella...')}"
            style="width:100%;margin-top:5px;resize:vertical;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;font-family:inherit;">${esc(identity.key_info||'')}</textarea>
        </div>
      </div>
      <div style="padding:12px 20px;border-top:1px solid #E2DDD6;background:#FAF8F5;display:flex;gap:10px;justify-content:space-between;flex-shrink:0;">
        <button class="btn btn-secondary" id="btnDeleteFolderIdentity" style="color:#C0392B;border-color:#C0392B;">🗑 ${T('id_remove','RIMUOVI')}</button>
        <div style="display:flex;gap:10px;">
          <button class="btn btn-secondary" id="btnCancelFolderIdentity">${T('cancel_upper','ANNULLA')}</button>
          <button class="btn btn-primary" id="btnSaveFolderIdentity" style="background:#8A5CE6;border-color:#8A5CE6;">${T('save_upper','SALVA')}</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
  document.getElementById('btnCloseFolderIdentity')?.addEventListener('click', close);
  document.getElementById('btnCancelFolderIdentity')?.addEventListener('click', close);

  document.getElementById('btnDeleteFolderIdentity')?.addEventListener('click', async () => {
    try {
      await api.deleteFolderIdentity(accountId, folderId);
      showToast(T('id_folder_removed','Identity cartella rimossa'));
      close();
    } catch(e) { showToast(T('error','Errore') + ': ' + e.message); }
  });

  document.getElementById('btnSaveFolderIdentity')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnSaveFolderIdentity');
    if (btn) { btn.disabled = true; btn.textContent = T('id_saving','Salvataggio...'); }
    try {
      await api.setFolderIdentity(accountId, folderId, {
        who_am_i:  document.getElementById('fiWhoAmI')?.value?.trim() || '',
        what_i_do: document.getElementById('fiWhatIDo')?.value?.trim() || '',
        tone:      document.getElementById('fiTone')?.value?.trim() || '',
        key_info:  document.getElementById('fiKeyInfo')?.value?.trim() || '',
        file_paths: [],
      });
      showToast(T('id_folder_saved','Identity cartella salvata!'));
      close();
    } catch(err) {
      showToast(T('error','Errore') + ': ' + err.message);
      if (btn) { btn.disabled = false; btn.textContent = T('save_upper','SALVA'); }
    }
  });
}

// ── IDENTITY MODAL ────────────────────────────────────────────────────────────

async function openIdentityModal(accountId, accountName) {
  const existing = document.getElementById('identityModal');
  if (existing) existing.remove();

  let identity = { who_am_i: '', what_i_do: '', tone: '', key_info: '', file_paths: [] };
  try { identity = await api.getIdentity(accountId); } catch(e) {}
  let signature = '';
  let sentVia = true;
  let sentViaText = '';
  try {
    const sigInfo = await api.getSignature(accountId);
    signature = sigInfo.signature || '';
    sentVia = sigInfo.sent_via !== false;
    sentViaText = sigInfo.sent_via_text || '';
  } catch(e) {}
  // Unknown (the request failed) is not "off": saving then leaves the
  // switch as it is instead of turning a mask off by accident.
  let attachmentMask = null;
  // Field rules: [{label, action, value}], what a named field of a form
  // becomes before the agent reads the attachment.
  let maskFields = [];
  // The recognised types (tax code, IBAN...) the account masks, out of all.
  let maskAllTypes = [];
  let maskTypes = [];
  // Exact words or names the user saved as masks: a row without an id is
  // new, the ids in maskWordsRemoved go when the modal is saved.
  let maskWords = [];
  const maskWordsRemoved = [];
  try {
    const maskInfo = await api.getAttachmentMask(accountId);
    attachmentMask = !!maskInfo.enabled;
    maskFields = Array.isArray(maskInfo.fields) ? maskInfo.fields.map(f => ({ ...f })) : [];
    maskAllTypes = Array.isArray(maskInfo.all_types) ? maskInfo.all_types : [];
    maskTypes = Array.isArray(maskInfo.types) ? [...maskInfo.types] : [...maskAllTypes];
  } catch(e) {}
  try {
    const saved = await api.getMasks(accountId);
    maskWords = Array.isArray(saved) ? saved.map(m => ({ id: m.id, value: m.value, label_type: m.label_type })) : [];
  } catch(e) {}

  const overlay = document.createElement('div');
  overlay.id = 'identityModal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(26,22,20,0.35);';

  overlay.innerHTML = `
    <div style="background:#FFFFFF;border:1px solid #E2DDD6;border-top:3px solid #2B5CE6;border-radius:4px;width:min(660px,94vw);max-height:90vh;display:flex;flex-direction:column;box-shadow:0 8px 40px rgba(43,92,230,0.13);overflow:hidden;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-bottom:1px solid #E2DDD6;background:#FAF8F5;flex-shrink:0;">
        <div>
          <div style="font-size:10px;font-weight:600;letter-spacing:2px;color:#8A8280;font-family:var(--mono)">${T('identity_account','IDENTITÀ ACCOUNT')}</div>
          <div style="font-size:12px;color:#2B5CE6;margin-top:2px;">${esc(accountName)}</div>
        </div>
        <button id="btnCloseIdentity" style="background:none;border:none;color:#8A8280;font-size:16px;cursor:pointer;padding:2px 8px;">✕</button>
      </div>
      <div style="flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:14px;">
        <div>
          <label class="field-label">${T('who_you_are','CHI SEI')}</label>
          <input id="idWhoAmI" type="text" placeholder="${T('who_account_ph','Es: Ufficio Vendite Progetto Residenze Milano')}"
            value="${esc(identity.who_am_i||'')}"
            style="width:100%;margin-top:5px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('what_you_do','COSA FAI')}</label>
          <input id="idWhatIDo" type="text" placeholder="${T('whatdo_account_ph','Es: Rispondo a richieste su appartamenti')}"
            value="${esc(identity.what_i_do||'')}"
            style="width:100%;margin-top:5px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('tone_reply','TONO DI RISPOSTA')}</label>
          <input id="idTone" type="text" placeholder="${T('tone_account_ph','Es: Professionale, cordiale, italiano formale')}"
            value="${esc(identity.tone||'')}"
            style="width:100%;margin-top:5px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('key_info','INFORMAZIONI CHIAVE')} <span style="font-weight:400;color:#8A8280">${T('key_info_sub','(prezzi, orari, contatti...)')}</span></label>
          <textarea id="idKeyInfo" rows="5" placeholder="${T('id_key_info_ph','Es: Bilocali 250-300k€, trilocali 350-400k€. Tel: 02.123456.')}"
            style="width:100%;margin-top:5px;resize:vertical;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;font-family:inherit;">${esc(identity.key_info||'')}</textarea>
        </div>
        <div>
          <label class="field-label">${T('signature','FIRMA')} <span style="font-weight:400;color:#8A8280">${T('signature_sub','(in fondo a ogni mail inviata da questo account)')}</span></label>
          <textarea id="idSignature" rows="3" maxlength="1000" placeholder="${T('signature_ph','Es: Mario Rossi · Via Roma 10, Milano')}"
            style="width:100%;margin-top:5px;resize:vertical;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:13px;outline:none;box-sizing:border-box;font-family:inherit;">${esc(signature)}</textarea>
          <label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;cursor:pointer;">
            <input type="checkbox" id="idSentVia" ${sentVia ? 'checked' : ''}/>
            <span>${T('sent_via_toggle','Aggiungi in fondo')} «${esc(sentViaText)}»</span>
          </label>
        </div>
        ${attachmentMask === null ? '' : `
        <div>
          <label class="field-label">${T('attachment_mask','PRIVACY')}</label>
          <label style="display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;cursor:pointer;">
            <input type="checkbox" id="idAttachmentMask" ${attachmentMask ? 'checked' : ''}/>
            <span>${T('attachment_mask_toggle','Maschera i dati personali nelle mail e negli allegati letti dall\'agente')}</span>
          </label>
          <div id="idMaskOptions" style="margin-top:10px;padding:10px 12px;border-left:3px solid #2B5CE6;background:#FAF8F5;${attachmentMask ? '' : 'display:none;'}">
            <div style="font-size:12px;font-weight:600;">${T('mask_what','Cosa vuoi mascherare?')}</div>
            <div style="font-size:12px;margin-top:10px;">${T('mask_auto','Riconosciuti in automatico')}</div>
            <div id="idMaskTypes" style="display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:6px;"></div>
            <div style="font-size:12px;margin-top:12px;">${T('mask_words','Parole o nomi precisi')} <span style="color:#8A8280">${T('mask_words_sub','(mascherati ovunque compaiano)')}</span></div>
            <div id="idMaskWords" style="display:flex;flex-direction:column;gap:6px;margin:6px 0;"></div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <input id="idMaskWordInput" type="text" maxlength="200" placeholder="${T('mask_word_ph','Es: Mario Rossi')}"
                style="flex:2;min-width:140px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:6px 8px;font-size:12px;outline:none;box-sizing:border-box;"/>
              <select id="idMaskWordLabel" style="flex:1;min-width:110px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:6px 8px;font-size:12px;outline:none;box-sizing:border-box;">
                <option value="NOME">${T('mask_label_NOME','Nome')}</option>
                <option value="AZIENDA">${T('mask_label_AZIENDA','Azienda')}</option>
                <option value="INDIRIZZO">${T('mask_label_INDIRIZZO','Indirizzo')}</option>
                <option value="MASK">${T('mask_label_MASK','Altro')}</option>
              </select>
              <button class="btn btn-secondary" id="btnAddMaskWord" type="button">+ ${T('mask_word_add','AGGIUNGI')}</button>
            </div>
            <div style="font-size:12px;margin-top:12px;">${T('mask_fields','Caselle di un modulo')} <span style="color:#8A8280">${T('mask_fields_sub','(scrivi l\'etichetta come compare nel documento)')}</span></div>
            <div id="idMaskFields" style="display:flex;flex-direction:column;gap:6px;margin:6px 0;"></div>
            <button class="btn btn-secondary" id="btnAddMaskField" type="button">+ ${T('mask_field_add','CASELLA')}</button>
          </div>
        </div>`}
        <div>
          <label class="field-label">${T('extract_url','ESTRAI DA URL')} <span style="font-weight:400;color:#8A8280">${T('extract_url_sub','(sito, LinkedIn, pagina prodotto...)')}</span></label>
          <div style="display:flex;gap:8px;margin-top:5px;">
            <input id="idUrlInput" type="text" placeholder="${T('url_ph','https://... oppure incolla testo con URL')}"
              style="flex:1;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:12px;outline:none;font-family:var(--mono);box-sizing:border-box;"/>
            <button class="btn btn-secondary" id="btnExtractUrl" style="white-space:nowrap;">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('search', 14) : '')} ${T('id_extract','ESTRAI')}</button>
          </div>
          <div id="idExtractStatus" style="font-size:11px;color:#8A8280;margin-top:4px;font-family:var(--mono);min-height:16px;"></div>
        </div>
        <div>
          <label class="field-label">${T('useful_files','FILE UTILI')} <span style="font-weight:400;color:#8A8280">${T('useful_files_sub','(.txt .md .csv — es. listino prezzi)')}</span></label>
          <div id="idFileList" style="display:flex;flex-direction:column;gap:6px;margin:6px 0;"></div>
          <div id="idDropZone" style="border:2px dashed #C8C3BC;border-radius:4px;padding:14px;text-align:center;color:#8A8280;font-size:11px;font-family:var(--mono);cursor:pointer;transition:border-color 0.15s,background 0.15s;margin-bottom:6px;">
            ${(typeof GMIcons !== 'undefined' ? GMIcons.svg('folder-open', 18) : '')} ${T('id_drop_files','TRASCINA FILE O CARTELLE QUI oppure clicca per sfogliare')}<br><span style="font-size:10px;opacity:0.7">.txt .md .csv .xlsx .pdf .docx</span>
            <input id="idFilePickerInput" type="file" multiple accept=".txt,.md,.csv,.xlsx,.xls,.pdf,.docx" style="display:none" webkitdirectory="false"/>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <input id="idFileInput" type="text" placeholder="${T('id_file_path_ph','C:\\Progetti\\Residenze\\listino.txt o cartella')}"
              style="flex:1;min-width:200px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:8px 10px;font-size:12px;outline:none;font-family:var(--mono);"/>
            <button class="btn btn-secondary" id="btnPickFolder" title="${T('id_select_folder','Seleziona cartella')}">📁 ${T('folder_word','CARTELLA')}</button>
            <button class="btn btn-secondary" id="btnAddFilePath">+ FILE</button>
          </div>
        </div>
      </div>
      <div style="padding:12px 20px;border-top:1px solid #E2DDD6;background:#FAF8F5;display:flex;gap:10px;justify-content:flex-end;flex-shrink:0;">
        <button class="btn btn-secondary" id="btnCancelIdentity">${T('cancel_upper','ANNULLA')}</button>
        <button class="btn btn-primary" id="btnSaveIdentity">${T('save_upper','SALVA')}</button>
      </div>
    </div>`;

  document.body.appendChild(overlay);

  function renderMaskFields() {
    const list = document.getElementById('idMaskFields');
    if (!list) return;
    const box = 'background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:6px 8px;font-size:12px;outline:none;box-sizing:border-box;';
    const actions = [
      ['placeholder', T('mask_action_placeholder','Segnaposto')],
      ['fake_name', T('mask_action_fake','Nome inventato')],
      ['fixed', T('mask_action_fixed','Testo fisso')],
    ];
    list.innerHTML = maskFields.map((f, i) => `
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <input data-idx="${i}" class="idMaskLabel" type="text" maxlength="80" value="${esc(f.label||'')}"
          placeholder="${T('mask_field_label_ph','Es: Nome e cognome')}" style="flex:2;min-width:140px;${box}"/>
        <select data-idx="${i}" class="idMaskAction" style="flex:1;min-width:120px;${box}">
          ${actions.map(([v, name]) => `<option value="${v}" ${f.action === v ? 'selected' : ''}>${esc(name)}</option>`).join('')}
        </select>
        <input data-idx="${i}" class="idMaskValue" type="text" maxlength="200" value="${esc(f.value||'')}"
          placeholder="${T('mask_field_fixed_ph','Testo da mettere')}"
          style="flex:2;min-width:140px;${box}${f.action === 'fixed' ? '' : 'display:none;'}"/>
        <button data-idx="${i}" class="idMaskRemove" type="button" style="background:none;border:none;color:#C0392B;cursor:pointer;font-size:14px;line-height:1;">✕</button>
      </div>`).join('');
    list.querySelectorAll('.idMaskLabel').forEach(el => {
      el.addEventListener('input', () => { maskFields[parseInt(el.dataset.idx)].label = el.value; });
    });
    list.querySelectorAll('.idMaskValue').forEach(el => {
      el.addEventListener('input', () => { maskFields[parseInt(el.dataset.idx)].value = el.value; });
    });
    list.querySelectorAll('.idMaskAction').forEach(el => {
      el.addEventListener('change', () => { maskFields[parseInt(el.dataset.idx)].action = el.value; renderMaskFields(); });
    });
    list.querySelectorAll('.idMaskRemove').forEach(el => {
      el.addEventListener('click', () => { maskFields.splice(parseInt(el.dataset.idx), 1); renderMaskFields(); });
    });
  }
  renderMaskFields();

  function renderMaskTypes() {
    const box = document.getElementById('idMaskTypes');
    if (!box) return;
    const names = {
      CODICE_FISCALE: T('mask_type_CODICE_FISCALE','Codice fiscale'), PARTITA_IVA: T('mask_type_PARTITA_IVA','Partita IVA'),
      IBAN: 'IBAN', EMAIL: T('mask_type_EMAIL','Email'), TELEFONO: T('mask_type_TELEFONO','Telefono'),
      AZIENDA: T('mask_type_AZIENDA','Ragione sociale'),
    };
    box.innerHTML = maskAllTypes.map(t => `
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
        <input type="checkbox" class="idMaskType" value="${esc(t)}" ${maskTypes.includes(t) ? 'checked' : ''}/>
        <span>${esc(names[t] || t)}</span>
      </label>`).join('');
    box.querySelectorAll('.idMaskType').forEach(el => {
      el.addEventListener('change', () => {
        maskTypes = maskAllTypes.filter(t => t === el.value ? el.checked : maskTypes.includes(t));
      });
    });
  }
  renderMaskTypes();

  function renderMaskWords() {
    const list = document.getElementById('idMaskWords');
    if (!list) return;
    list.innerHTML = maskWords.map((w, i) => `
      <div style="display:flex;align-items:center;gap:8px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:5px 10px;">
        <span style="flex:1;font-size:12px;word-break:break-all;">${esc(w.value)}</span>
        <span style="font-family:var(--mono);font-size:10px;color:#8A8280;">${esc(w.label_type || 'MASK')}</span>
        <button data-idx="${i}" class="idMaskWordRemove" type="button" style="background:none;border:none;color:#C0392B;cursor:pointer;font-size:14px;line-height:1;">✕</button>
      </div>`).join('');
    list.querySelectorAll('.idMaskWordRemove').forEach(el => {
      el.addEventListener('click', () => {
        const [gone] = maskWords.splice(parseInt(el.dataset.idx), 1);
        if (gone && gone.id != null) maskWordsRemoved.push(gone.id);
        renderMaskWords();
      });
    });
  }
  renderMaskWords();

  function addMaskWord() {
    const inp = document.getElementById('idMaskWordInput');
    const value = (inp?.value || '').trim();
    if (!value) return;
    if (!maskWords.some(w => w.value === value)) {
      maskWords.push({ value, label_type: document.getElementById('idMaskWordLabel')?.value || 'MASK' });
      renderMaskWords();
    }
    inp.value = '';
    inp.focus();
  }
  document.getElementById('btnAddMaskWord')?.addEventListener('click', addMaskWord);
  document.getElementById('idMaskWordInput')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); addMaskWord(); }
  });
  // The choices show only while the masker is on.
  document.getElementById('idAttachmentMask')?.addEventListener('change', e => {
    const options = document.getElementById('idMaskOptions');
    if (options) options.style.display = e.target.checked ? '' : 'none';
  });

  document.getElementById('btnAddMaskField')?.addEventListener('click', () => {
    maskFields.push({ label: '', action: 'placeholder', value: '' });
    renderMaskFields();
    const labels = document.querySelectorAll('#idMaskFields .idMaskLabel');
    labels[labels.length - 1]?.focus();
  });

  let filePaths = Array.isArray(identity.file_paths) ? [...identity.file_paths] : [];

  function getPathIcon(fp) {
    // Detect se è cartella (no estensione) o file
    const hasExt = /\.[a-zA-Z0-9]+$/.test(fp.trim());
    if (!hasExt) return (typeof GMIcons !== 'undefined' ? GMIcons.svg('folder', 13) : '');
    const ext = fp.split('.').pop().toLowerCase();
    const icons = { xlsx: 'bar-chart', xls: 'bar-chart', csv: 'bar-chart', pdf: 'file-text', docx: 'file-text', txt: 'file-text', md: 'file-text' };
    return (typeof GMIcons !== 'undefined' ? GMIcons.svg(icons[ext] || 'paperclip', 13) : '');
  }

  function renderFilePaths() {
    const list = document.getElementById('idFileList');
    if (!list) return;
    list.innerHTML = filePaths.map((fp, i) => `
      <div style="display:flex;align-items:center;gap:8px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:6px 10px;">
        <span style="font-size:14px;flex-shrink:0;">${getPathIcon(fp)}</span>
        <span style="flex:1;font-family:var(--mono);font-size:11px;color:#4A4340;word-break:break-all;">${esc(fp)}</span>
        <button data-idx="${i}" class="idRemoveFile" style="background:none;border:none;color:#C0392B;cursor:pointer;font-size:14px;line-height:1;">✕</button>
      </div>`).join('');
    list.querySelectorAll('.idRemoveFile').forEach(btn => {
      btn.addEventListener('click', () => { filePaths.splice(parseInt(btn.dataset.idx), 1); renderFilePaths(); });
    });
  }
  renderFilePaths();

  function addFilePath() {
    const inp = document.getElementById('idFileInput');
    const val = inp?.value?.trim();
    if (val && !filePaths.includes(val)) {
      filePaths.push(val);
      renderFilePaths();
      if (inp) inp.value = '';
    }
  }

  function addFilePathFromString(p) {
    const val = p.trim();
    if (val && !filePaths.includes(val)) { filePaths.push(val); renderFilePaths(); }
  }

  // Drag & drop sulla drop zone
  const dropZone = document.getElementById('idDropZone');
  const filePicker = document.getElementById('idFilePickerInput');

  if (dropZone) {
    // Click apre file picker
    dropZone.addEventListener('click', (e) => {
      if (e.target.id === 'idFilePickerInput') return;
      filePicker?.click();
    });

    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.style.borderColor = '#2B5CE6';
      dropZone.style.background = '#EEF2FF';
      dropZone.style.color = '#2B5CE6';
    });
    dropZone.addEventListener('dragleave', () => {
      dropZone.style.borderColor = '#C8C3BC';
      dropZone.style.background = '';
      dropZone.style.color = '';
    });
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.style.borderColor = '#C8C3BC';
      dropZone.style.background = '';
      dropZone.style.color = '';

      const items = Array.from(e.dataTransfer.items || []);
      const files = Array.from(e.dataTransfer.files || []);

      // In Electron: prova a ottenere path da webkitGetAsEntry per cartelle
      let handled = false;
      for (const item of items) {
        if (item.kind === 'file') {
          const entry = item.webkitGetAsEntry?.();
          if (entry && entry.isDirectory) {
            // È una cartella — usa il path del file corrispondente per risalire alla dir
            const f = item.getAsFile();
            if (f && f.path) {
              // f.path sarà tipo C:/Cartella/file.txt — prendi la cartella
              const dirPath = f.path.replace(/[/\\][^/\\]+$/, '');
              addFilePathFromString(dirPath);
              handled = true;
            }
          }
        }
      }

      if (!handled) {
        // File singoli o cartella via f.path diretto
        const seenDirs = new Set();
        files.forEach(f => {
          const p = f.path || f.name;
          if (!p) return;
          // Se il path contiene sottocartelle, aggiungi la cartella padre
          // Controlla se tutti i file vengono dalla stessa directory (drag di cartella)
          const dir = p.replace(/[/\\][^/\\]+$/, '');
          seenDirs.add(dir);
        });
        if (seenDirs.size === 1 && files.length > 1) {
          // Più file dalla stessa dir = probabilmente cartella trascinata
          addFilePathFromString([...seenDirs][0]);
        } else {
          files.forEach(f => {
            const p = f.path || f.name;
            if (p) addFilePathFromString(p);
          });
        }
      }
    });
  }

  if (filePicker) {
    filePicker.addEventListener('change', () => {
      const files = Array.from(filePicker.files || []);
      // Se è una selezione di cartella (webkitdirectory), aggiungi la cartella
      if (files.length > 1) {
        const firstPath = files[0]?.path || '';
        if (firstPath) {
          const dir = firstPath.replace(/[/\\][^/\\]+$/, '');
          addFilePathFromString(dir);
        }
      } else {
        files.forEach(f => {
          const p = f.path || f.name;
          if (p) addFilePathFromString(p);
        });
      }
      filePicker.value = '';
    });
  }

  // Bottone separato per selezionare cartella
  const btnPickFolder = document.getElementById('btnPickFolder');
  if (btnPickFolder) {
    btnPickFolder.addEventListener('click', () => {
      const folderPicker = document.createElement('input');
      folderPicker.type = 'file';
      folderPicker.webkitdirectory = true;
      folderPicker.style.display = 'none';
      document.body.appendChild(folderPicker);
      folderPicker.addEventListener('change', () => {
        const files = Array.from(folderPicker.files || []);
        if (files.length > 0) {
          const firstPath = files[0]?.path || '';
          if (firstPath) {
            const dir = firstPath.replace(/[/\\][^/\\]+$/, '');
            addFilePathFromString(dir);
          }
        }
        folderPicker.remove();
      });
      folderPicker.click();
    });
  }
  // Usa overlay come delegato — sicuro anche se il DOM non è ancora stabile
  overlay.addEventListener('click', (e) => {
    if (e.target.id === 'btnAddFilePath' || e.target.closest('#btnAddFilePath')) {
      addFilePath();
    }
  });
  overlay.addEventListener('keydown', (e) => {
    if (e.target.id === 'idFileInput' && e.key === 'Enter') {
      e.preventDefault();
      addFilePath();
    }
  });
  const close = () => overlay.remove();
  overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
  document.getElementById('btnCloseIdentity')?.addEventListener('click', close);
  document.getElementById('btnCancelIdentity')?.addEventListener('click', close);

  // ── Estrai da URL ──────────────────────────────────────────────
  const btnExtract = document.getElementById('btnExtractUrl');
  const extractStatus = document.getElementById('idExtractStatus');
  if (btnExtract) {
    btnExtract.addEventListener('click', async () => {
      const text = document.getElementById('idUrlInput')?.value?.trim();
      if (!text) return;
      btnExtract.disabled = true;
      btnExtract.textContent = T('id_extracting','Estrazione...');
      if (extractStatus) extractStatus.textContent = T('id_analyzing','Analisi in corso...');
      try {
        const res = await fetch(`${window.GIGAMAIL_API}/identity/extract_from_url`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        _showIdentityPreview(data, (confirmed) => {
          if (!confirmed) return;
          if (confirmed.who_am_i)  document.getElementById('idWhoAmI').value  = confirmed.who_am_i;
          if (confirmed.what_i_do) document.getElementById('idWhatIDo').value = confirmed.what_i_do;
          if (confirmed.tone)      document.getElementById('idTone').value    = confirmed.tone;
          if (confirmed.key_info)  document.getElementById('idKeyInfo').value = confirmed.key_info;
          if (extractStatus) extractStatus.textContent = '✓ ' + T('id_fields_filled','Campi popolati — verifica e salva.');
        });
      } catch(e) {
        if (extractStatus) extractStatus.textContent = '✗ ' + T('error','Errore') + ': ' + e.message;
      } finally {
        btnExtract.disabled = false;
        btnExtract.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('search', 14) : '') + ' ' + T('id_extract','ESTRAI');
      }
    });
  }

  document.getElementById('btnSaveIdentity')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnSaveIdentity');
    if (btn) { btn.disabled = true; btn.textContent = T('id_saving','Salvataggio...'); }
    try {
      await api.setIdentity(accountId, {
        who_am_i:  document.getElementById('idWhoAmI')?.value?.trim() || '',
        what_i_do: document.getElementById('idWhatIDo')?.value?.trim() || '',
        tone:      document.getElementById('idTone')?.value?.trim() || '',
        key_info:  document.getElementById('idKeyInfo')?.value?.trim() || '',
        file_paths: filePaths,
      });
      await api.setSignature(accountId, document.getElementById('idSignature')?.value || '',
                             !!document.getElementById('idSentVia')?.checked);
      const maskBox = document.getElementById('idAttachmentMask');
      if (maskBox) {
        // A row left without a label is a row the user did not fill in.
        const fields = maskFields
          .filter(f => (f.label || '').trim())
          .map(f => ({ label: f.label.trim(), action: f.action, value: f.action === 'fixed' ? (f.value || '').trim() : '' }));
        // A word typed and not yet added is still what the user asked for.
        addMaskWord();
        await api.setAttachmentMask(accountId, maskBox.checked, fields, maskTypes);
        for (const id of maskWordsRemoved) await api.deleteMask(accountId, id);
        for (const w of maskWords) {
          if (w.id == null) await api.addMask(accountId, w.value, w.label_type);
        }
      }
      showToast(T('id_saved','Identità salvata!'));
      close();
    } catch(err) {
      showToast(T('error','Errore') + ': ' + err.message);
      if (btn) { btn.disabled = false; btn.textContent = T('save_upper','SALVA'); }
    }
  });
}
function _showIdentityPreview(data, onConfirm) {
  const existing = document.getElementById('identityPreviewModal');
  if (existing) existing.remove();

  const esc2 = (s) => (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

  const overlay = document.createElement('div');
  overlay.id = 'identityPreviewModal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(26,22,20,0.5);';

  overlay.innerHTML = `
    <div style="background:#FFFFFF;border:1px solid #E2DDD6;border-top:3px solid #2B5CE6;border-radius:4px;width:min(560px,94vw);max-height:85vh;display:flex;flex-direction:column;box-shadow:0 8px 40px rgba(43,92,230,0.18);overflow:hidden;">
      <div style="padding:12px 20px;border-bottom:1px solid #E2DDD6;background:#FAF8F5;flex-shrink:0;">
        <div style="font-size:10px;font-weight:600;letter-spacing:2px;color:#8A8280;font-family:var(--mono)">${T('preview_identity','PREVIEW IDENTITY ESTRATTA')}</div>
        <div style="font-size:11px;color:#8A8280;margin-top:2px;">${T('id_preview_hint','Modifica se necessario, poi conferma per applicare ai campi.')}</div>
      </div>
      <div style="flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px;">
        <div>
          <label class="field-label">${T('who_you_are','CHI SEI')}</label>
          <input id="prevWhoAmI" type="text" value="${esc2(data.who_am_i)}"
            style="width:100%;margin-top:4px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:7px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('what_you_do','COSA FAI')}</label>
          <input id="prevWhatIDo" type="text" value="${esc2(data.what_i_do)}"
            style="width:100%;margin-top:4px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:7px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('tone','TONO')}</label>
          <input id="prevTone" type="text" value="${esc2(data.tone)}"
            style="width:100%;margin-top:4px;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:7px 10px;font-size:13px;outline:none;box-sizing:border-box;"/>
        </div>
        <div>
          <label class="field-label">${T('info_key','INFO CHIAVE')}</label>
          <textarea id="prevKeyInfo" rows="5"
            style="width:100%;margin-top:4px;resize:vertical;background:#F4F2EE;border:1px solid #E2DDD6;border-radius:2px;padding:7px 10px;font-size:13px;outline:none;box-sizing:border-box;font-family:inherit;">${esc2(data.key_info)}</textarea>
        </div>
      </div>
      <div style="padding:12px 20px;border-top:1px solid #E2DDD6;background:#FAF8F5;display:flex;gap:10px;justify-content:flex-end;flex-shrink:0;">
        <button class="btn btn-secondary" id="btnPreviewCancel">${T('cancel_upper','ANNULLA')}</button>
        <button class="btn btn-primary" id="btnPreviewApply" style="background:#2B5CE6;border-color:#2B5CE6;">✓ ${T('id_apply','APPLICA')}</button>
      </div>
    </div>`;

  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
  document.getElementById('btnPreviewCancel')?.addEventListener('click', () => { close(); onConfirm(null); });
  document.getElementById('btnPreviewApply')?.addEventListener('click', () => {
    const confirmed = {
      who_am_i:  document.getElementById('prevWhoAmI')?.value?.trim() || '',
      what_i_do: document.getElementById('prevWhatIDo')?.value?.trim() || '',
      tone:      document.getElementById('prevTone')?.value?.trim() || '',
      key_info:  document.getElementById('prevKeyInfo')?.value?.trim() || '',
    };
    close();
    onConfirm(confirmed);
  });
}
