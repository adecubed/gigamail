/**
 * renderer_automations.js — vista "Automazioni" (GigaMail 0.2.1):
 * regole di risposta semi/auto, watcher, notifiche, agente.
 *
 * Tutto passa dal backend console (token iniettato da main.js). Creare o
 * riattivare una regola fa alzare Windows Hello dal backend: la finestra
 * mostra solo l'esito. Il token Telegram NON si inserisce qui (CLI).
 */
(function () {
  const API = 'http://127.0.0.1:8002';
  const $ = (id) => document.getElementById(id);
  const isEn = () => (localStorage.getItem('ade_lang') || 'it') === 'en';
  const T = (it, en) => (isEn() ? en : it);

  async function api(path, opts = {}) {
    const r = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    let data = null;
    try { data = await r.json(); } catch (_) { /* no body */ }
    if (!r.ok) {
      const msg = (data && data.detail) || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return data;
  }

  function toast(msg, kind) {
    if (typeof showToast === 'function') { showToast(msg, kind); return; }
    console.log('[automations]', msg);
  }

  // ------------------------------------------------------------ view
  function showView() {
    document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
    $('view-automations')?.classList.add('active');
    document.querySelectorAll('.s-item').forEach((i) => i.classList.remove('active'));
    $('btnShowAutomations')?.classList.add('active');
    refreshAll();
  }

  function leaveView() {
    const v = $('view-automations');
    if (v && v.classList.contains('active')) {
      v.classList.remove('active');
      $('view-mail')?.classList.add('active');
      $('btnShowAutomations')?.classList.remove('active');
    }
  }

  // ------------------------------------------------------------ rules
  function fmtDays(expiresAt) {
    const d = Math.floor((expiresAt * 1000 - Date.now()) / 86400000);
    return d < 0 ? T('scaduta', 'expired') : T(`scade tra ${d}g`, `expires in ${d}d`);
  }

  function ruleCard(r) {
    const trig = r.trigger_kind === 'folder'
      ? T('cartella ', 'folder ') + r.trigger_values[0]
      : r.trigger_values.join(', ');
    const state = r.state === 'active' ? T('attiva', 'active')
      : r.state === 'paused' ? T('in pausa', 'paused') : T('scaduta', 'expired');
    const cls = r.state === 'active' ? 'ok' : 'err';
    const docs = (r.doc_paths || []).map((p) => p.split(/[\\/]/).pop()).join(', ');
    const modeTag = r.mode === 'auto'
      ? `<span class="ai-tag" style="background:rgba(220,38,38,0.1);border-color:rgba(220,38,38,0.3);color:#dc2626">AUTO</span>`
      : `<span class="ai-tag">SEMI</span>`;
    const actBtn = r.state === 'paused'
      ? `<button class="chip-btn" data-act="resume" data-id="${r.rule_id}">▶ ${T('Riattiva (Hello)', 'Resume (Hello)')}</button>`
      : r.state === 'active'
        ? `<button class="chip-btn" data-act="pause" data-id="${r.rule_id}">⏸ ${T('Pausa', 'Pause')}</button>`
        : '';
    return `
      <div class="ai-card" data-rule="${r.rule_id}">
        <div class="ai-card-head">
          <div class="ai-card-titles">
            <div class="ai-card-title">${modeTag} ${escapeHtml(trig)}</div>
            <div class="ai-card-sub">${escapeHtml(r.reply_style || T('(nessuno stile)', '(no style)'))}
              ${docs ? ' · 📎 ' + escapeHtml(docs) : ''}</div>
            <div class="ai-card-sub">${T('cap', 'cap')} ${r.daily_cap}/${T('g', 'd')} · cooldown ${r.cooldown_hours}h ·
              ${T('oggi', 'today')}: ${r.sent_today} · ${fmtDays(r.expires_at)}
              ${r.pause_reason ? ' · ' + escapeHtml(r.pause_reason) : ''}</div>
          </div>
        </div>
        <div class="ai-card-row">
          <span class="ai-card-status ${cls}">${state}</span>
          <span style="flex:1"></span>
          <button class="chip-btn" data-act="activity" data-id="${r.rule_id}">📋 ${T('Attività', 'Activity')}</button>
          ${actBtn}
          <button class="chip-btn danger" data-act="delete" data-id="${r.rule_id}">🗑</button>
        </div>
        <div class="hint" id="act-${r.rule_id}" style="display:none;white-space:pre-wrap;margin-top:8px"></div>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  async function refreshRules() {
    const box = $('rulesList');
    if (!box) return;
    try {
      const rules = await api('/rules');
      box.innerHTML = rules.length
        ? rules.map(ruleCard).join('')
        : `<div class="hint">${T('Nessuna regola. Creane una qui sotto: la conferma finale è Windows Hello.',
                                 'No rules yet. Create one below: the final confirmation is Windows Hello.')}</div>`;
    } catch (e) {
      box.innerHTML = `<div class="hint">${T('Errore', 'Error')}: ${escapeHtml(e.message)}</div>`;
    }
  }

  async function onRuleAction(e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    try {
      if (act === 'pause') {
        await api(`/rules/${id}/pause`, { method: 'POST' });
      } else if (act === 'resume') {
        toast(T('Conferma con Windows Hello…', 'Confirm with Windows Hello…'));
        await api(`/rules/${id}/resume`, { method: 'POST' });
      } else if (act === 'delete') {
        if (!confirm(T('Eliminare la regola?', 'Delete the rule?'))) return;
        await api(`/rules/${id}`, { method: 'DELETE' });
      } else if (act === 'activity') {
        const el = $(`act-${id}`);
        if (el.style.display !== 'none') { el.style.display = 'none'; return; }
        const rows = await api(`/rules/${id}/activity`);
        el.textContent = rows.length
          ? rows.map((r) => `${new Date(r.ts * 1000).toLocaleString()}  ${r.sender}  →  ${r.status}${r.reason ? ' (' + r.reason + ')' : ''}${r.request_id ? '  ' + r.request_id : ''}`).join('\n')
          : T('Nessuna mail gestita finora.', 'No mail handled yet.');
        el.style.display = 'block';
        return;
      }
      await refreshRules();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function onCreateRule() {
    const kind = $('ruleTriggerKind').value;
    const raw = $('ruleTriggerValues').value;
    const values = kind === 'senders'
      ? raw.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean)
      : [raw.trim()];
    const body = {
      account_id: parseInt($('ruleAccount').value, 10) || null,
      trigger_kind: kind,
      trigger_values: values,
      reply_style: $('ruleStyle').value.trim(),
      doc_paths: pickedDocs.slice(),
      mode: $('ruleMode').value,
      first_contact: $('ruleFirstContact').value,
      daily_cap: parseInt($('ruleCap').value, 10) || 10,
      cooldown_hours: parseFloat($('ruleCooldown').value) || 0,
      expiry_days: parseFloat($('ruleExpiry').value) || 30,
    };
    if (!values.length || !values[0]) {
      toast(T('Indica almeno un mittente o una cartella.', 'Enter at least one sender or a folder.'), 'error');
      return;
    }
    const btn = $('btnCreateRule');
    btn.disabled = true;
    $('ruleFormStatus').textContent = T('Conferma con Windows Hello…', 'Confirm with Windows Hello…');
    try {
      const r = await api('/rules', { method: 'POST', body: JSON.stringify(body) });
      $('ruleFormStatus').textContent = T(`Regola creata: ${r.rule_id}`, `Rule created: ${r.rule_id}`);
      pickedDocs = [];
      renderDocs();
      $('ruleTriggerValues').value = '';
      await refreshRules();
    } catch (e) {
      $('ruleFormStatus').textContent = T('Non creata: ', 'Not created: ') + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  // documenti: file picker nativo (IPC) o percorso incollato
  let pickedDocs = [];
  function renderDocs() {
    const el = $('ruleDocsList');
    if (!el) return;
    el.innerHTML = pickedDocs.length
      ? pickedDocs.map((p, i) => `<span class="ai-tag" style="margin:2px">${escapeHtml(p.split(/[\\/]/).pop())}
          <a href="#" data-rm="${i}" style="margin-left:4px;text-decoration:none">✕</a></span>`).join('')
      : `<span class="hint">${T('Nessun documento: la bozza userà solo l\'identità dell\'account.',
                                 'No documents: the draft will only use the account identity.')}</span>`;
    el.querySelectorAll('a[data-rm]').forEach((a) => a.addEventListener('click', (ev) => {
      ev.preventDefault();
      pickedDocs.splice(parseInt(a.dataset.rm, 10), 1);
      renderDocs();
    }));
  }

  async function onPickDocs() {
    if (window.electronAPI?.pickFiles) {
      const paths = await window.electronAPI.pickFiles();
      (paths || []).forEach((p) => { if (!pickedDocs.includes(p)) pickedDocs.push(p); });
    } else {
      const p = prompt(T('Percorso completo del documento:', 'Full path of the document:'));
      if (p) pickedDocs.push(p.trim());
    }
    renderDocs();
  }

  async function fillAccounts() {
    const sel = $('ruleAccount');
    if (!sel) return;
    try {
      const accs = await api('/accounts');
      sel.innerHTML = accs.map((a) => `<option value="${a.id}" ${a.active ? 'selected' : ''}>${escapeHtml(a.email)}</option>`).join('');
    } catch (_) { /* lista vuota */ }
  }

  function onTriggerKindChange() {
    const kind = $('ruleTriggerKind').value;
    $('ruleTriggerValues').placeholder = kind === 'senders'
      ? T('indirizzi separati da virgola', 'comma-separated addresses')
      : T('nome cartella, es. INBOX.Leads', 'folder name, e.g. INBOX.Leads');
    $('ruleFolderWarn').style.display = kind === 'folder' ? 'block' : 'none';
  }

  function onModeChange() {
    $('ruleFirstContactRow').style.display = $('ruleMode').value === 'auto' ? 'flex' : 'none';
  }

  // ------------------------------------------------------------ watcher
  async function refreshWatch() {
    const el = $('watchStatus');
    if (!el) return;
    try {
      const st = await api('/watch/status');
      el.className = 'ai-card-status ' + (st.running ? 'ok' : 'err');
      el.textContent = st.running
        ? T(`attivo (pid ${st.pid}, ogni ${st.interval}s, ultimo giro ${st.last_tick_age_seconds ?? '?'}s fa)`,
            `running (pid ${st.pid}, every ${st.interval}s, last tick ${st.last_tick_age_seconds ?? '?'}s ago)`)
        : T('fermo — le regole non vengono applicate', 'stopped — rules are not applied');
      $('btnWatchStart').style.display = st.running ? 'none' : '';
      $('btnWatchStop').style.display = st.running ? '' : 'none';
      $('watchRulesCount').textContent = T(`${st.active_rules} regole attive`, `${st.active_rules} active rules`);
      const log = await api('/watch/log?lines=25');
      $('watchLog').textContent = log.join('\n') || T('(nessun log)', '(no log)');
    } catch (e) {
      el.className = 'ai-card-status err';
      el.textContent = e.message;
    }
  }

  // ------------------------------------------------------------ notifiche
  async function refreshNotify() {
    try {
      const st = await api('/notify/status');
      const ag = st.agent || {};
      set('agentStatus', ag.available ? 'ok' : 'err',
        ag.available ? T(`pronto: ${ag.command}`, `ready: ${ag.command}`)
                     : T('agente non trovato: installa Claude Code o configura agent.json',
                         'agent not found: install Claude Code or configure agent.json'));
      set('consentStatus', st.consent_backend ? 'ok' : 'err',
        st.consent_backend || T('nessun backend: approvazioni solo da console? NO — fail-closed',
                                'no backend: approvals fail closed'));
      const d = st.desktop || {};
      set('desktopStatus', d.buttons ? 'ok' : (d.enabled ? 'warn' : 'err'),
        !d.enabled ? T('disattivate (GIGAMAIL_NOTIFY_DESKTOP=0)', 'disabled (GIGAMAIL_NOTIFY_DESKTOP=0)')
          : d.buttons ? T('attive, bottoni cliccabili', 'on, clickable buttons')
                      : T('attive, senza bottoni (serve la registrazione)', 'on, no buttons (registration needed)'));
      $('btnDesktopSetup').style.display = (d.enabled && !d.buttons && d.platform === 'nt') ? '' : 'none';
      const tg = st.telegram || {};
      set('telegramStatus', tg.configured ? 'ok' : 'err',
        tg.configured
          ? T(`chat ${tg.chat_id} — approvazione ${tg.approve ? 'ABILITATA' : 'non abilitata (solo avvisi, rifiuto, modifica)'}`,
              `chat ${tg.chat_id} — approval ${tg.approve ? 'ENABLED' : 'not enabled (notify, reject, edit only)'}`)
          : T('non configurato', 'not configured'));
    } catch (e) {
      set('agentStatus', 'err', e.message);
    }
  }

  function set(id, cls, text) {
    const el = $(id);
    if (!el) return;
    el.className = 'ai-card-status ' + cls;
    el.textContent = text;
  }

  async function onDesktopSetup() {
    $('desktopStatus').textContent = T('Conferma il prompt UAC di Windows…', 'Confirm the Windows UAC prompt…');
    try {
      const r = await api('/notify/desktop-setup', { method: 'POST' });
      toast(r.buttons ? T('Bottoni toast attivi.', 'Toast buttons enabled.')
                      : T('Registrazione non riuscita (UAC negato?).', 'Registration failed (UAC denied?).'),
            r.buttons ? 'ok' : 'error');
    } catch (e) {
      toast(e.message, 'error');
    }
    refreshNotify();
  }

  async function refreshAll() {
    await Promise.all([refreshRules(), refreshWatch(), refreshNotify(), fillAccounts()]);
  }

  // ------------------------------------------------------------ bind
  document.addEventListener('DOMContentLoaded', () => {
    $('btnShowAutomations')?.addEventListener('click', showView);
    // qualunque altra voce della sidebar riporta alla posta
    document.querySelectorAll('.sidebar .s-item').forEach((item) => {
      if (item.id !== 'btnShowAutomations' && item.id !== 'langSwitch') {
        item.addEventListener('click', leaveView, true);
      }
    });
    $('rulesList')?.addEventListener('click', onRuleAction);
    $('btnCreateRule')?.addEventListener('click', onCreateRule);
    $('btnPickDocs')?.addEventListener('click', onPickDocs);
    $('ruleTriggerKind')?.addEventListener('change', onTriggerKindChange);
    $('ruleMode')?.addEventListener('change', onModeChange);
    $('btnWatchStart')?.addEventListener('click', async () => {
      try { await api('/watch/start', { method: 'POST' }); } catch (e) { toast(e.message, 'error'); }
      setTimeout(refreshWatch, 1500);
    });
    $('btnWatchStop')?.addEventListener('click', async () => {
      try { await api('/watch/stop', { method: 'POST' }); } catch (e) { toast(e.message, 'error'); }
      refreshWatch();
    });
    $('btnWatchRefresh')?.addEventListener('click', refreshWatch);
    $('btnDesktopSetup')?.addEventListener('click', onDesktopSetup);
    $('btnNotifyRefresh')?.addEventListener('click', refreshNotify);
    // Rotella: scorre .auto-body ovunque sia il puntatore nella vista
    // (non solo sopra la barra), anche quando il target e' un campo.
    const body = document.querySelector('#view-automations .auto-body');
    $('view-automations')?.addEventListener('wheel', (ev) => {
      if (!body) return;
      if (ev.target.closest('.auto-log')) return; // il log scorre da solo
      body.scrollTop += ev.deltaY;
      ev.preventDefault();
    }, { passive: false });
    onTriggerKindChange();
    onModeChange();
    renderDocs();
    // aggiornamento periodico mentre la vista e' aperta
    setInterval(() => {
      if ($('view-automations')?.classList.contains('active')) refreshWatch();
    }, 15000);
  });
})();
