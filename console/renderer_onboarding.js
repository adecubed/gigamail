// renderer_onboarding.js — guida iniziale dentro la finestra principale.
//
// Stesso pattern del login Microsoft: un .overlay > .modal con i passi come
// div fratelli commutati da setHidden. Nessuna BrowserWindow, nessun dialogo
// nativo oltre al file picker gia' usato dall'identita'.
//
// Si apre da sola al primo avvio (GET /onboarding: flag non scritto e zero
// account) e si riapre da window.openOnboarding() — dashboard vuota e vista
// AI. Il flag "fatto" vive nel backend, non in localStorage: un reinstall
// della console non la ripropone a chi ha gia' tutto.
(function () {
  const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
  const STEPS = ['welcome', 'account', 'identity', 'agent', 'done'];
  const MCP_SNIPPET = '{\n  "mcpServers": {\n    "gigamail": { "command": "gigamail-server" }\n  }\n}';
  const TG_COMMAND = 'gigamail telegram setup';

  const api = window.ademail || {};
  const $ = (id) => document.getElementById(id);

  let step = 0;
  let accounts = [];
  let identityAccountId = null;
  let identitySaved = false;      // salvata in questa sessione della guida
  let identityExists = false;     // gia' presente prima della guida
  let agentReady = false;
  let pickedFiles = [];

  async function apiJson(path, opts) {
    const r = await fetch(`${API}${path}`, opts);
    let payload = null;
    try { payload = await r.json(); } catch (_) { /* corpo vuoto */ }
    if (!r.ok) {
      let detail = payload && (payload.detail || payload.message);
      // 422 di FastAPI: lista di errori di validazione, non una stringa
      if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).slice(-1)[0] || ''}: ${d.msg || ''}`.trim()).join('; ');
      throw new Error(typeof detail === 'string' && detail ? detail : `HTTP ${r.status}`);
    }
    return payload;
  }
  const post = (path, body) => apiJson(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  // ── apertura / chiusura ────────────────────────────────────────────
  async function startIfNeeded() {
    try {
      const st = await apiJson('/onboarding');
      if (!st.done && st.accounts === 0) open();
    } catch (e) { console.warn('[ONBOARDING] status:', e.message); }
  }

  function open() {
    step = 0;
    identitySaved = false;
    identityExists = false;
    pickedFiles = [];
    resetAccountPanels();
    render();
    setHidden('onboardingOverlay', false);
  }

  async function close() {
    setHidden('onboardingOverlay', true);
    // Chi ha collegato almeno un account ha finito: non riproporre la guida
    // al prossimo avvio. Chi chiude senza account la ritrova.
    if (accounts.length) {
      try { await post('/onboarding/done'); } catch (_) { /* best-effort */ }
    }
    if (typeof checkAuth === 'function') checkAuth().catch(() => {});
  }

  // ── navigazione ────────────────────────────────────────────────────
  function goto(n) {
    step = Math.max(0, Math.min(STEPS.length - 1, n));
    render();
  }

  function render() {
    STEPS.forEach((s, i) => setHidden(`ob-step-${s}`, i !== step));
    const dots = $('obDots');
    if (dots) {
      dots.innerHTML = STEPS.map((_, i) =>
        `<span class="ob-dot${i === step ? ' active' : i < step ? ' done' : ''}"></span>`).join('');
    }
    setText('obTitle', T(`ob_title_${STEPS[step]}`, ''));
    setText('obStepLabel', T('ob_step', 'Passo {n} di {total}')
      .replace('{n}', String(step + 1)).replace('{total}', String(STEPS.length)));

    const back = $('obBack'), skip = $('obSkip'), next = $('obNext');
    if (back) back.style.visibility = step === 0 ? 'hidden' : 'visible';
    if (skip) skip.style.display = (STEPS[step] === 'identity' || STEPS[step] === 'agent') ? '' : 'none';
    if (next) {
      const s = STEPS[step];
      next.textContent = s === 'welcome' ? T('ob_start', 'Iniziamo')
        : s === 'identity' ? T('ob_save_next', 'Salva e continua')
        : s === 'done' ? T('ob_open_mail', 'Apri la posta')
        : T('ob_next', 'Avanti');
      next.disabled = false;
    }

    if (STEPS[step] === 'account') refreshAccounts();
    if (STEPS[step] === 'identity') loadIdentity();
    if (STEPS[step] === 'agent') loadAgent();
    if (STEPS[step] === 'done') renderSummary();
  }

  async function onNext() {
    const s = STEPS[step];
    if (s === 'account' && !accounts.length) {
      setStatus('obAccountStatus', T('ob_no_account_yet', ''), 'warn');
      return;
    }
    if (s === 'identity') {
      const ok = await saveIdentity();
      if (!ok) return;
    }
    if (s === 'done') {
      try { await post('/onboarding/done'); } catch (_) { /* best-effort */ }
      setHidden('onboardingOverlay', true);
      if (typeof checkAuth === 'function') await checkAuth().catch(() => {});
      if (typeof refreshCurrentFolder === 'function') refreshCurrentFolder().catch(() => {});
      return;
    }
    goto(step + 1);
  }

  function setStatus(id, msg, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'ob-status' + (kind ? ` ${kind}` : '');
  }

  // ── passo account ──────────────────────────────────────────────────
  function resetAccountPanels() {
    setHidden('obMsPanel', true);
    setHidden('obImapPanel', true);
    setHidden('obMsStep1', false);
    setHidden('obMsStep2', true);
    setHidden('obChoices', false);
    ['obImapName', 'obImapEmail', 'obImapPassword', 'obImapHost', 'obSmtpHost'].forEach((id) => { if ($(id)) $(id).value = ''; });
    setStatus('obImapStatus', '');
    setStatus('obMsStatus', '');
    setStatus('obAccountStatus', '');
  }

  async function refreshAccounts() {
    try { accounts = await api.getAccounts(); } catch (_) { accounts = []; }
    if (!Array.isArray(accounts)) accounts = [];
    const list = $('obAccountList');
    if (list) {
      list.innerHTML = accounts.map((a) =>
        `<div class="ob-account"><span class="ob-check">✓</span><span class="ob-account-name">${esc(a.name || a.email)}</span><span class="ob-account-email">${esc(a.email || '')}</span></div>`).join('');
    }
    setHidden('obAccountsBox', accounts.length === 0);
    setHidden('obAddAnother', accounts.length === 0);
    const showChoices = accounts.length === 0;
    if (showChoices) setHidden('obChoices', false);
    else if ($('obMsPanel')?.classList.contains('hidden') && $('obImapPanel')?.classList.contains('hidden')) setHidden('obChoices', true);
  }

  function showMs() {
    setHidden('obChoices', true); setHidden('obImapPanel', true); setHidden('obMsPanel', false);
    setHidden('obMsStep1', false); setHidden('obMsStep2', true);
    setStatus('obMsStatus', '');
  }

  function showImap(provider) {
    setHidden('obChoices', true); setHidden('obMsPanel', true); setHidden('obImapPanel', false);
    if (provider && $('obImapProvider')) { $('obImapProvider').value = provider; }
    onProviderChange();
    setStatus('obImapStatus', '');
    $('obImapName')?.focus();
  }

  function onProviderChange() {
    const p = $('obImapProvider')?.value || 'aruba';
    setHidden('obImapCustom', p !== 'custom');
    const hint = $('obImapHint');
    if (hint) {
      hint.textContent = p === 'gmail' ? T('ob_imap_hint_gmail', '')
        : p === 'outlook' ? T('ob_imap_hint_outlook', '') : '';
      hint.style.display = hint.textContent ? '' : 'none';
    }
  }

  async function msStart() {
    setStatus('obMsStatus', T('ob_ms_wait', ''), '');
    try {
      const data = await api.startLogin();
      const uri = data.verification_uri || 'https://microsoft.com/devicelogin';
      const link = $('obMsLink');
      if (link) { link.textContent = uri; link.dataset.href = uri; }
      setText('obMsCode', data.user_code || '');
      setHidden('obMsStep1', true); setHidden('obMsStep2', false);
      setStatus('obMsStatus', '');
    } catch (e) { setStatus('obMsStatus', `${T('ob_err', 'Errore:')} ${e.message || e}`, 'err'); }
  }

  function msOpen() {
    const uri = $('obMsLink')?.dataset.href || 'https://microsoft.com/devicelogin';
    if (window.electronAPI?.openExternal) window.electronAPI.openExternal(uri);
  }

  async function msComplete() {
    const btn = $('obMsComplete');
    if (btn) btn.disabled = true;
    setStatus('obMsStatus', T('ob_ms_wait', ''), '');
    try {
      const r = await api.completeLogin();
      if (r && r.success) {
        setHidden('obMsPanel', true);
        setHidden('obMsStep1', false); setHidden('obMsStep2', true);
        await refreshAccounts();
        setStatus('obAccountStatus', '');
        showToast(T('ob_account_ok', 'Account collegato'), 'success');
      } else {
        setStatus('obMsStatus', T('ob_ms_retry', 'Login non completato. Riprova.'), 'err');
      }
    } catch (e) { setStatus('obMsStatus', `${T('ob_err', 'Errore:')} ${e.message || e}`, 'err'); }
    if (btn) btn.disabled = false;
  }

  async function imapSave() {
    const name = $('obImapName')?.value.trim() || '';
    const email = $('obImapEmail')?.value.trim() || '';
    const password = $('obImapPassword')?.value || '';
    const provider = $('obImapProvider')?.value || 'aruba';
    if (!name || !email || !password) {
      setStatus('obImapStatus', T('ob_imap_missing', 'Compila nome, email e password.'), 'err');
      return;
    }
    const body = { name, email, password, provider };
    if (provider === 'custom') {
      body.imap_host = $('obImapHost')?.value.trim() || '';
      body.imap_port = parseInt($('obImapPort')?.value, 10) || 993;
      body.smtp_host = $('obSmtpHost')?.value.trim() || '';
      body.smtp_port = parseInt($('obSmtpPort')?.value, 10) || 465;
    }
    const btn = $('obImapSave');
    if (btn) btn.disabled = true;
    setStatus('obImapStatus', T('ob_imap_verify', ''), '');
    try {
      const r = await post('/accounts/imap', body);
      if (r && r.success) {
        setHidden('obImapPanel', true);
        await refreshAccounts();
        setStatus('obAccountStatus', '');
        showToast(T('ob_account_ok', 'Account collegato'), 'success');
      } else {
        setStatus('obImapStatus', `${T('ob_err', 'Errore:')} ${(r && r.detail) || '?'}`, 'err');
      }
    } catch (e) { setStatus('obImapStatus', `${T('ob_err', 'Errore:')} ${e.message || e}`, 'err'); }
    if (btn) btn.disabled = false;
  }

  // ── passo identita' ────────────────────────────────────────────────
  async function loadIdentity() {
    const acc = accounts.find((a) => a.active) || accounts[0];
    identityAccountId = acc ? acc.id : null;
    setText('obIdentityAccount', acc ? (acc.email || acc.name || '') : '');
    if (!identityAccountId) return;
    try {
      const ident = await api.getIdentity(identityAccountId);
      if ($('obWho')) $('obWho').value = ident.who_am_i || '';
      if ($('obWhat')) $('obWhat').value = ident.what_i_do || '';
      if ($('obTone')) $('obTone').value = ident.tone || '';
      if ($('obKeyInfo')) $('obKeyInfo').value = ident.key_info || '';
      pickedFiles = Array.isArray(ident.file_paths) ? ident.file_paths.slice() : [];
      identityExists = !!(ident.who_am_i || ident.what_i_do || ident.tone || ident.key_info || pickedFiles.length);
    } catch (_) { pickedFiles = []; identityExists = false; }
    renderFiles();
  }

  function renderFiles() {
    const el = $('obFileList');
    if (!el) return;
    if (!pickedFiles.length) {
      el.innerHTML = `<div class="ob-muted">${esc(T('ob_docs_none', ''))}</div>`;
      return;
    }
    el.innerHTML = pickedFiles.map((p, i) =>
      `<div class="ob-file"><span class="ob-file-name" title="${esc(p)}">${esc(p.split(/[\\/]/).pop())}</span><button class="icon-btn-sm ob-file-rm" data-i="${i}" title="${esc(T('close', 'Rimuovi'))}">✕</button></div>`).join('');
    el.querySelectorAll('.ob-file-rm').forEach((b) => b.addEventListener('click', () => {
      pickedFiles.splice(parseInt(b.dataset.i, 10), 1);
      renderFiles();
    }));
  }

  async function pickDocs() {
    if (!window.electronAPI?.pickFiles) return;
    const paths = await window.electronAPI.pickFiles();
    (paths || []).forEach((p) => { if (!pickedFiles.includes(p)) pickedFiles.push(p); });
    renderFiles();
  }

  async function saveIdentity() {
    if (!identityAccountId) return true;
    const data = {
      who_am_i: $('obWho')?.value.trim() || '',
      what_i_do: $('obWhat')?.value.trim() || '',
      tone: $('obTone')?.value.trim() || '',
      key_info: $('obKeyInfo')?.value.trim() || '',
      file_paths: pickedFiles,
    };
    const anything = data.who_am_i || data.what_i_do || data.tone || data.key_info || pickedFiles.length;
    if (!anything) return true;           // niente da salvare: come "salta"
    try {
      await api.setIdentity(identityAccountId, data);
      identitySaved = true;
      return true;
    } catch (e) {
      setStatus('obIdentityStatus', `${T('ob_err', 'Errore:')} ${e.message || e}`, 'err');
      return false;
    }
  }

  // ── passo agente ───────────────────────────────────────────────────
  async function loadAgent() {
    setText('obMcpSnippet', MCP_SNIPPET);
    setText('obTgCommand', TG_COMMAND);
    try {
      const st = await apiJson('/notify/status');
      const ag = st.agent || {};
      agentReady = !!ag.available;
      setStatus('obAgentStatus',
        agentReady ? `${T('ob_agent_found', '')} ${ag.command || ''}` : T('ob_agent_missing', ''),
        agentReady ? 'ok' : 'warn');
      const d = st.desktop || {};
      const isWin = d.platform === 'nt';
      setHidden('obNotifyBox', !isWin || !d.enabled);
      setText('obNotifyText', d.buttons ? T('ob_notify_buttons_on', '') : T('ob_notify_buttons_off', ''));
      setHidden('obNotifySetup', !!d.buttons);
    } catch (e) {
      agentReady = false;
      setStatus('obAgentStatus', `${T('ob_err', 'Errore:')} ${e.message || e}`, 'err');
    }
  }

  async function desktopSetup() {
    setText('obNotifyText', T('ob_notify_uac', 'Conferma il prompt UAC di Windows…'));
    try {
      const r = await post('/notify/desktop-setup');
      showToast(r.buttons ? T('ob_notify_ok', 'Bottoni attivi.') : T('ob_notify_fail', 'Registrazione non riuscita (UAC negato?).'),
        r.buttons ? 'success' : 'error');
    } catch (e) { showToast(e.message || String(e), 'error'); }
    loadAgent();
  }

  async function copy(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
      if (btn) { const old = btn.textContent; btn.textContent = T('ob_copied', 'Copiato'); setTimeout(() => { btn.textContent = old; }, 1500); }
    } catch (_) { showToast(T('ob_copy_fail', 'Copia non riuscita'), 'error'); }
  }

  // ── riepilogo ──────────────────────────────────────────────────────
  function renderSummary() {
    const el = $('obSummary');
    if (!el) return;
    const row = (ok, text) => `<div class="ob-account"><span class="ob-check${ok ? '' : ' off'}">${ok ? '✓' : '○'}</span><span>${esc(text)}</span></div>`;
    const identityOk = identitySaved || identityExists;
    el.innerHTML =
      row(accounts.length > 0, `${accounts.length} ${T('ob_done_accounts', 'account collegati')}`) +
      row(identityOk, identityOk ? T('ob_done_identity_yes', '') : T('ob_done_identity_no', '')) +
      row(agentReady, agentReady ? T('ob_done_agent_yes', '') : T('ob_done_agent_no', ''));
  }

  // ── binding ────────────────────────────────────────────────────────
  function bind() {
    on('obClose', 'click', close);
    on('obBack', 'click', () => goto(step - 1));
    on('obSkip', 'click', () => goto(step + 1));
    on('obNext', 'click', onNext);
    on('obChoiceMs', 'click', showMs);
    on('obChoiceImap', 'click', () => showImap());
    on('obAddAnother', 'click', () => { setHidden('obChoices', false); setHidden('obAddAnother', true); });
    on('obMsStart', 'click', msStart);
    on('obMsOpen', 'click', msOpen);
    on('obMsLink', 'click', (e) => { e.preventDefault(); msOpen(); });
    on('obMsComplete', 'click', msComplete);
    on('obMsCancel', 'click', () => { setHidden('obMsPanel', true); setHidden('obChoices', false); });
    on('obImapProvider', 'change', onProviderChange);
    on('obImapSave', 'click', imapSave);
    on('obImapCancel', 'click', () => { setHidden('obImapPanel', true); setHidden('obChoices', false); });
    on('obImapPassword', 'keydown', (e) => { if (e.key === 'Enter') imapSave(); });
    on('obPickDocs', 'click', pickDocs);
    on('obCopyMcp', 'click', (e) => copy(MCP_SNIPPET, e.currentTarget));
    on('obCopyTg', 'click', (e) => copy(TG_COMMAND, e.currentTarget));
    on('obNotifySetup', 'click', desktopSetup);
    document.querySelectorAll('.ob-lang').forEach((b) => b.addEventListener('click', () => {
      if (window.i18n?.applyLang) window.i18n.applyLang(b.dataset.lang);
      document.querySelectorAll('.ob-lang').forEach((x) => x.classList.toggle('active', x === b));
      render();
    }));
    const cur = (window.i18n && window.i18n.lang) || 'it';
    document.querySelectorAll('.ob-lang').forEach((x) => x.classList.toggle('active', x.dataset.lang === cur));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();

  window.openOnboarding = open;
  window.startOnboardingIfNeeded = startIfNeeded;
})();
