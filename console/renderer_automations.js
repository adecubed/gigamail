/**
 * renderer_automations.js — vista "Automazioni" (GigaMail 0.2.1):
 * regole di risposta semi/auto, watcher, notifiche, agente.
 *
 * Tutto passa dal backend console (token iniettato da main.js). Creare o
 * riattivare una regola fa alzare Windows Hello dal backend: la finestra
 * mostra solo l'esito. Il token Telegram NON si inserisce qui (CLI).
 */
(function () {
  const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
  const $ = (id) => document.getElementById(id);
  const lang = () => (localStorage.getItem('ade_lang') || 'it');
  const T = (it, en, zh) =>
    lang() === 'it' ? it : lang() === 'zh' ? (zh || en) : en;

  let refreshCodex = null;   // stato di ChatGPT/Codex (codex_connect.js), legato al primo caricamento

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

  // Waiting for you has its own view and its own icon, under Automations.
  function showPendingView() {
    document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
    $('view-pending')?.classList.add('active');
    document.querySelectorAll('.s-item').forEach((i) => i.classList.remove('active'));
    $('btnShowPending')?.classList.add('active');
    refreshPending();
  }

  function leaveView() {
    for (const [view, btn] of [['view-automations', 'btnShowAutomations'], ['view-pending', 'btnShowPending']]) {
      const v = $(view);
      if (v && v.classList.contains('active')) {
        v.classList.remove('active');
        $('view-mail')?.classList.add('active');
        $(btn)?.classList.remove('active');
      }
    }
  }

  // ------------------------------------------------------------ rules
  function fmtDays(expiresAt) {
    const d = Math.floor((expiresAt * 1000 - Date.now()) / 86400000);
    if (expiresAt * 1000 <= Date.now()) return T('scaduta', 'expired', '已过期');
    if (d < 1) return T('scade entro un giorno', 'expires within a day', '一天内过期');
    return T(`scade tra ${d}g`, `expires in ${d}d`, `${d} 天后过期`);
  }

  function ruleCard(r) {
    const trig = r.trigger_kind === 'folder'
      ? T('cartella ', 'folder ', '文件夹 ') + r.trigger_values[0]
      : r.trigger_values.join(', ');
    const state = r.state === 'active' ? T('attiva', 'active', '启用')
      : r.state === 'paused' ? T('in pausa', 'paused', '已暂停') : T('scaduta', 'expired', '已过期');
    const cls = r.state === 'active' ? 'ok' : 'err';
    const docs = (r.doc_paths || []).map((p) => p.split(/[\\/]/).pop()).join(', ');
    const modeTag = r.mode === 'auto'
      ? `<span class="ai-tag" style="background:rgba(220,38,38,0.1);border-color:rgba(220,38,38,0.3);color:#dc2626">AUTO</span>`
      : `<span class="ai-tag">SEMI</span>`;
    const actBtn = r.state === 'paused'
      ? `<button class="chip-btn" data-act="resume" data-id="${r.rule_id}">▶ ${T('Riattiva (Hello)', 'Resume (Hello)', '恢复 (Hello)')}</button>`
      : r.state === 'active'
        ? `<button class="chip-btn" data-act="pause" data-id="${r.rule_id}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('pause', 12) : '')} ${T('Pausa', 'Pause', '暂停')}</button>`
        : '';
    const renewBtn = (r.expired || r.expiring) ? renewButton(r) : '';
    return `
      <div class="ai-card" data-rule="${r.rule_id}">
        <div class="ai-card-head">
          <div class="ai-card-titles">
            <div class="ai-card-title">${modeTag} ${escapeHtml(trig)}</div>
            <div class="ai-card-sub">${escapeHtml(r.reply_style || T('(nessuno stile)', '(no style)', '(无风格)'))}
              ${docs ? ' · ' + (typeof GMIcons !== 'undefined' ? GMIcons.svg('paperclip', 11) : '') + ' ' + escapeHtml(docs) : ''}</div>
            <div class="ai-card-sub">${T('cap', 'cap', '上限')} ${r.daily_cap}/${T('g', 'd', '天')} · ${T('cooldown', 'cooldown', '冷却')} ${r.cooldown_hours}h ·
              ${T('oggi', 'today', '今天')}: ${r.sent_today} · ${fmtDays(r.expires_at)}
              ${r.pause_reason ? ' · ' + escapeHtml(r.pause_reason) : ''}</div>
          </div>
        </div>
        <div class="ai-card-row">
          <span class="ai-card-status ${cls}">${state}</span>
          <span style="flex:1"></span>
          <button class="chip-btn" data-act="edit" data-id="${r.rule_id}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('pencil', 12) : '')} ${T('Modifica', 'Edit', '编辑')}</button>
          <button class="chip-btn" data-act="activity" data-id="${r.rule_id}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('clipboard', 12) : '')} ${T('Attività', 'Activity', '活动')}</button>
          ${actBtn}
          ${renewBtn}
          <button class="chip-btn danger" data-act="delete" data-id="${r.rule_id}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('trash', 13) : '')}</button>
        </div>
        <div class="doc-notes" data-docs-for="${escapeHtml(r.rule_id)}" style="display:none"></div>
        <div class="hint" id="act-${r.rule_id}" style="display:none;white-space:pre-wrap;margin-top:8px"></div>
      </div>`;
  }

  // What the agent will not read well in each rule's documents, under its card.
  function showDocNotes(rules) {
    if (!window.DocNotes) return;
    for (const r of rules) {
      const box = document.querySelector(`[data-docs-for="${r.rule_id}"]`);
      if (box && (r.doc_paths || []).length) window.DocNotes.show(box, r.doc_paths, api);
    }
  }

  function renewButton(r) {
    const days = Math.round(r.expiry_days || 30);
    return `<button class="chip-btn" data-act="renew" data-id="${escapeHtml(r.rule_id)}">↻ ${T(`Rinnova per ${days}g (Hello)`, `Renew for ${days}d (Hello)`, `续期 ${days} 天 (Hello)`)}</button>`;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  let lastRules = [];
  let editingRuleId = null;

  async function refreshRules() {
    const box = $('rulesList');
    if (!box) return;
    try {
      const rules = await api('/rules');
      lastRules = rules;
      setRulesBadge(rules);
      box.innerHTML = pausedBanner(rules) + (rules.length
        ? rules.map(ruleCard).join('')
        : `<div class="hint">${T('Nessuna regola. Creane una qui sotto: la conferma finale è Windows Hello.',
                                 'No rules yet. Create one below: the final confirmation is Windows Hello.',
                                 '还没有规则。在下方创建一条：最终确认由 Windows Hello 完成。')}</div>`);
      showDocNotes(rules);
    } catch (e) {
      box.innerHTML = `<div class="hint">${T('Errore', 'Error', '错误')}: ${escapeHtml(e.message)}</div>`;
    }
  }

  // A rule that paused itself (burst guard) stops answering until a human
  // resumes it with Hello: a banner above the list and a mark on the
  // sidebar icon, visible from any view, until that happens.
  function pausedBanner(rules) {
    return autoPausedBanner(rules) + renewBanner(rules);
  }

  // A rule that expired, or will within days, answers nothing after that:
  // say so above the list, with the button to renew it.
  function renewBanner(rules) {
    const due = AV() ? AV().toRenew(rules) : [];
    return due.map((r) => `
      <div class="ai-card gm-rule-alert" data-rule-alert="${escapeHtml(r.rule_id)}">
        <div class="ai-card-title">${r.expired ? T('Regola scaduta', 'Rule expired', '规则已过期') : T('Regola in scadenza', 'Rule expiring', '规则即将过期')}: ${escapeHtml((r.trigger_values || []).join(', '))}</div>
        <div class="ai-card-sub">${fmtDays(r.expires_at)} · ${r.expired
          ? T('non risponde a nessuna mail finché non la rinnovi.', 'it answers no mail until you renew it.', '在你续期之前不会回复任何邮件。')
          : T('dopo non risponde più a nessuna mail.', 'after that it answers no mail.', '之后将不再回复任何邮件。')}</div>
        <div class="ai-card-row" style="margin-top:8px">
          <span style="flex:1"></span>
          ${renewButton(r)}
        </div>
      </div>`).join('');
  }

  function autoPausedBanner(rules) {
    const stuck = AV() ? AV().autoPaused(rules) : [];
    return stuck.map((r) => `
      <div class="ai-card gm-rule-alert" data-rule-alert="${escapeHtml(r.rule_id)}">
        <div class="ai-card-title">${T('Regola in pausa da sola', 'Rule paused itself', '规则已自动暂停')}: ${escapeHtml((r.trigger_values || []).join(', '))}</div>
        <div class="ai-card-sub">${escapeHtml(r.pause_reason || '')} · ${T('non risponde a nessuna mail finché non la riattivi.', 'it answers no mail until you resume it.', '在你恢复之前不会回复任何邮件。')}</div>
        <div class="ai-card-row" style="margin-top:8px">
          <span style="flex:1"></span>
          <button class="chip-btn" data-act="activity" data-id="${escapeHtml(r.rule_id)}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('clipboard', 12) : '')} ${T('Attività', 'Activity', '活动')}</button>
          <button class="chip-btn" data-act="resume" data-id="${escapeHtml(r.rule_id)}">▶ ${T('Riattiva (Hello)', 'Resume (Hello)', '恢复 (Hello)')}</button>
        </div>
      </div>`).join('');
  }

  function setRulesBadge(rules) {
    const b = $('automationsBadge');
    if (!b) return;
    // how many rules wait for a human to resume them (paused by the burst
    // guard): what needs doing here, not a statistic
    const n = AV() ? AV().autoPaused(rules).length + AV().toRenew(rules).length : 0;
    b.textContent = AV() ? AV().badgeText(n) : (n ? String(n) : '');
    b.hidden = !n;
    b.title = T('Regole da riattivare o rinnovare', 'Rules to resume or renew', '待恢复或续期的规则');
  }

  async function onRuleAction(e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    try {
      if (act === 'edit') {
        startEditRule(id);
        return;
      }
      if (act === 'pause') {
        await api(`/rules/${id}/pause`, { method: 'POST' });
      } else if (act === 'resume') {
        toast(T('Conferma con Windows Hello…', 'Confirm with Windows Hello…', '请用 Windows Hello 确认…'));
        await api(`/rules/${id}/resume`, { method: 'POST' });
      } else if (act === 'renew') {
        toast(T('Conferma con Windows Hello…', 'Confirm with Windows Hello…', '请用 Windows Hello 确认…'));
        await api(`/rules/${id}/renew`, { method: 'POST' });
      } else if (act === 'delete') {
        if (!(await GMDialog.confirm(T('Eliminare la regola?', 'Delete the rule?', '删除此规则？'), { danger: true }))) return;
        await api(`/rules/${id}`, { method: 'DELETE' });
      } else if (act === 'activity') {
        const el = $(`act-${id}`);
        if (el.style.display !== 'none') { el.style.display = 'none'; return; }
        const rows = await api(`/rules/${id}/activity`);
        el.textContent = rows.length
          ? rows.map((r) => `${new Date(r.ts * 1000).toLocaleString()}  ${r.sender}  →  ${r.status}${r.reason ? ' (' + r.reason + ')' : ''}${r.request_id ? '  ' + r.request_id : ''}`).join('\n')
          : T('Nessuna mail gestita finora.', 'No mail handled yet.', '尚未处理任何邮件。');
        el.style.display = 'block';
        return;
      }
      await refreshRules();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  function splitList(value) {
    return String(value || '').split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
  }

  // Edit on a card: the rule goes into the form, Create becomes Save.
  // Saving changes the rule in place (same id, same expiry, the mails it
  // handled stay handled) behind Hello, as creating it.
  function startEditRule(id) {
    const r = lastRules.find((x) => x.rule_id === id);
    if (!r) return;
    editingRuleId = id;
    if ($('ruleAccount')) $('ruleAccount').value = String(r.account_id);
    $('ruleTriggerKind').value = r.trigger_kind;
    $('ruleTriggerValues').value = (r.trigger_values || []).join(', ');
    $('ruleStyle').value = r.reply_style || '';
    pickedDocs = (r.doc_paths || []).slice();
    renderDocs();
    if ($('ruleAttachments')) $('ruleAttachments').value = (r.attachments || []).join(', ');
    if ($('ruleCc')) $('ruleCc').value = (r.cc || []).join(', ');
    $('ruleMode').value = r.mode;
    if ($('ruleFirstContact')) $('ruleFirstContact').value = r.first_contact || 'semi';
    if ($('ruleCap')) $('ruleCap').value = r.daily_cap;
    if ($('ruleCooldown')) $('ruleCooldown').value = r.cooldown_hours;
    if ($('ruleExpiry')) $('ruleExpiry').value = Math.round(r.expiry_days || 30);
    onTriggerKindChange();
    onModeChange();
    if ($('ruleFormTitle')) $('ruleFormTitle').textContent = T('Modifica regola', 'Edit rule', '编辑规则') + ': ' + (r.trigger_values || []).join(', ');
    $('btnCreateRule').textContent = T('Salva modifiche (Hello)', 'Save changes (Hello)', '保存更改 (Hello)');
    if ($('btnCancelEdit')) $('btnCancelEdit').style.display = '';
    if ($('ruleFormStatus')) $('ruleFormStatus').textContent = T('La regola resta attiva con le stesse scadenze: cambia solo quello che modifichi qui.', 'The rule stays as it is, same expiry: only what you change here changes.', '规则保持不变，到期时间相同：只更改你在这里修改的内容。');
    $('ruleForm')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }

  function cancelEditRule() {
    editingRuleId = null;
    $('ruleTriggerValues').value = '';
    $('ruleStyle').value = '';
    pickedDocs = [];
    renderDocs();
    if ($('ruleAttachments')) $('ruleAttachments').value = '';
    if ($('ruleCc')) $('ruleCc').value = '';
    if ($('ruleFormTitle')) $('ruleFormTitle').textContent = T('Nuova regola', 'New rule', '新规则');
    $('btnCreateRule').textContent = T('Crea regola', 'Create rule', '创建规则');
    if ($('btnCancelEdit')) $('btnCancelEdit').style.display = 'none';
    if ($('ruleFormStatus')) $('ruleFormStatus').textContent = T('La conferma finale è Windows Hello: una regola è una pre-approvazione.', 'The final confirmation is Windows Hello: a rule is a pre-approval.', '最终确认由 Windows Hello 完成：规则是一种预先批准。');
  }

  async function onCreateRule() {
    const kind = $('ruleTriggerKind').value;
    const raw = $('ruleTriggerValues').value;
    const values = kind === 'senders' ? splitList(raw) : [raw.trim()];
    const body = {
      account_id: parseInt($('ruleAccount')?.value, 10) || null,
      trigger_kind: kind,
      trigger_values: values,
      reply_style: $('ruleStyle').value.trim(),
      doc_paths: pickedDocs.slice(),
      mode: $('ruleMode').value,
      first_contact: $('ruleFirstContact')?.value || 'semi',
      daily_cap: parseInt($('ruleCap')?.value, 10) || 10,
      cooldown_hours: parseFloat($('ruleCooldown')?.value) || 0,
      expiry_days: parseFloat($('ruleExpiry')?.value) || 30,
      attachments: splitList($('ruleAttachments')?.value),
      cc: splitList($('ruleCc')?.value),
    };
    if (!values.length || !values[0]) {
      toast(T('Indica almeno un mittente o una cartella.', 'Enter at least one sender or a folder.', '请至少填写一个发件人或一个文件夹。'), 'error');
      return;
    }
    const btn = $('btnCreateRule');
    btn.disabled = true;
    $('ruleFormStatus').textContent = T('Conferma con Windows Hello…', 'Confirm with Windows Hello…', '请用 Windows Hello 确认…');
    const editing = editingRuleId;
    try {
      if (editing) {
        delete body.account_id;
        delete body.expiry_days;
        const r = await api(`/rules/${editing}`, { method: 'PUT', body: JSON.stringify(body) });
        cancelEditRule();
        $('ruleFormStatus').textContent = T(`Regola aggiornata: ${r.rule_id}`, `Rule updated: ${r.rule_id}`, `规则已更新：${r.rule_id}`);
      } else {
        const r = await api('/rules', { method: 'POST', body: JSON.stringify(body) });
        $('ruleFormStatus').textContent = T(`Regola creata: ${r.rule_id}`, `Rule created: ${r.rule_id}`, `规则已创建：${r.rule_id}`);
        pickedDocs = [];
        renderDocs();
        $('ruleTriggerValues').value = '';
      }
      await refreshRules();
    } catch (e) {
      $('ruleFormStatus').textContent = (editing
        ? T('Non modificata: ', 'Not changed: ', '未更改：')
        : T('Non creata: ', 'Not created: ', '未创建：')) + e.message;
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
                                 'No documents: the draft will only use the account identity.',
                                 '没有文档：草稿只会使用账户身份。')}</span>`;
    el.querySelectorAll('a[data-rm]').forEach((a) => a.addEventListener('click', (ev) => {
      ev.preventDefault();
      pickedDocs.splice(parseInt(a.dataset.rm, 10), 1);
      renderDocs();
    }));
    if (window.DocNotes) window.DocNotes.show($('ruleDocsNotes'), pickedDocs.slice(), api);
  }

  async function onPickDocs() {
    if (window.electronAPI?.pickFiles) {
      const paths = await window.electronAPI.pickFiles();
      (paths || []).forEach((p) => { if (!pickedDocs.includes(p)) pickedDocs.push(p); });
    } else {
      const p = prompt(T('Percorso completo del documento:', 'Full path of the document:', '文档的完整路径：'));
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
      ? T('indirizzi separati da virgola', 'comma-separated addresses', '用逗号分隔的地址')
      : T('nome cartella, es. INBOX.Leads', 'folder name, e.g. INBOX.Leads', '文件夹名称，例如 INBOX.Leads');
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
            `running (pid ${st.pid}, every ${st.interval}s, last tick ${st.last_tick_age_seconds ?? '?'}s ago)`,
            `运行中 (pid ${st.pid}，每 ${st.interval} 秒，上次轮询 ${st.last_tick_age_seconds ?? '?'} 秒前)`)
        : T('fermo — le regole non vengono applicate e l\'archivio non si aggiorna',
            'stopped — rules are not applied and the archive is not updated',
            '已停止 — 规则不会生效，存档也不会更新');
      $('btnWatchStart').style.display = st.running ? 'none' : '';
      $('btnWatchStop').style.display = st.running ? '' : 'none';
      $('watchRulesCount').textContent = T(`${st.active_rules} regole attive`, `${st.active_rules} active rules`, `${st.active_rules} 条启用的规则`);
      renderArchiveSync(st.archive_sync || []);
      const log = await api('/watch/log?lines=25');
      $('watchLog').textContent = log.join('\n') || T('(nessun log)', '(no log)', '(无日志)');
    } catch (e) {
      el.className = 'ai-card-status err';
      el.textContent = e.message;
    }
  }

  // One line per account: how much the archive holds and when it last
  // synced, so an account that stopped syncing shows here, not only in
  // the log.
  function agoText(ts) {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 120) return T('adesso', 'just now', '刚刚');
    const m = Math.round(s / 60);
    if (m < 120) return T(`${m} min fa`, `${m} min ago`, `${m} 分钟前`);
    const h = Math.round(s / 3600);
    if (h < 48) return T(`${h} ore fa`, `${h} hours ago`, `${h} 小时前`);
    const d = Math.round(s / 86400);
    return T(`${d} giorni fa`, `${d} days ago`, `${d} 天前`);
  }

  function renderArchiveSync(rows) {
    const box = $('watchSync');
    if (!box) return;
    box.innerHTML = rows.map((r) => {
      const who = escapeHtml(r.email || r.name || String(r.account_id));
      const n = Number(r.messages || 0).toLocaleString();
      const when = r.last_ok_at
        ? T(`aggiornato ${agoText(r.last_ok_at)}`, `updated ${agoText(r.last_ok_at)}`, `更新于 ${agoText(r.last_ok_at)}`)
        : T('mai sincronizzato', 'never synced', '从未同步');
      const err = r.error
        ? ` · <span class="watch-sync-err">${escapeHtml(T('errore', 'error', '错误'))}: ${escapeHtml(r.error)}</span>`
        : '';
      const cls = r.behind || r.error ? 'watch-sync-row bad' : 'watch-sync-row';
      return `<div class="${cls}">${r.behind ? '⚠ ' : ''}<b>${who}</b> · ${n} mail · ${escapeHtml(when)}${err}</div>`;
    }).join('');
  }

  // ------------------------------------------------------------ notifiche
  async function refreshNotify() {
    try {
      const st = await api('/notify/status');
      const ag = st.agent || {};
      const sel = $('agentSelect');
      if (sel) {
        sel.innerHTML = '';
        (ag.agents || []).forEach((a) => {
          const o = document.createElement('option');
          o.value = a.id;
          o.textContent = a.found ? a.label : `${a.label} — ${T('non trovato', 'not found', '未找到')}`;
          sel.appendChild(o);
        });
        if (ag.agent) sel.value = ag.agent;
      }
      set('agentStatus', ag.available ? 'ok' : 'err',
        ag.available ? T(`pronto: ${ag.command}`, `ready: ${ag.command}`, `就绪：${ag.command}`) + (ag.codex_model ? ` · ${ag.codex_model}` : '')
                     : T('agente non trovato: installa Claude Code, l\'app Codex / ChatGPT o Antigravity (agy), o configura agent.json',
                         'agent not found: install Claude Code, the Codex / ChatGPT app or Antigravity (agy), or configure agent.json',
                         '未找到代理：请安装 Claude Code、Codex / ChatGPT 应用或 Antigravity (agy)，或配置 agent.json'));
      if (window.ClaudeLoginPanel) window.ClaudeLoginPanel.refresh(ag);
      set('consentStatus', st.consent_backend ? 'ok' : 'err',
        st.consent_backend || (
          T('nessun backend, approvazioni bloccate', 'no backend, approvals fail closed', '无后端，审批被阻止')
          + (st.consent_reason ? `: ${st.consent_reason}` : '')));
      const sendHello = $('consoleSendHello');
      if (sendHello) sendHello.checked = !!st.console_send_hello;
      const d = st.desktop || {};
      set('desktopStatus', d.buttons ? 'ok' : (d.enabled ? 'warn' : 'err'),
        !d.enabled ? T('disattivate (GIGAMAIL_NOTIFY_DESKTOP=0)', 'disabled (GIGAMAIL_NOTIFY_DESKTOP=0)', '已关闭 (GIGAMAIL_NOTIFY_DESKTOP=0)')
          : d.buttons ? T('attive, bottoni cliccabili', 'on, clickable buttons', '已开启，按钮可点击')
          : d.buttons_off === 'legacy'
            ? T('attive, senza bottoni: lo schema apre ancora una vecchia installazione', 'on, no buttons: the scheme still opens an old installation', '已开启，无按钮：协议仍指向旧安装')
            : T('attive, senza bottoni (serve la registrazione)', 'on, no buttons (registration needed)', '已开启，无按钮（需要注册）'));
      $('btnDesktopSetup').style.display = (d.enabled && !d.buttons && d.platform === 'nt') ? '' : 'none';
      const tg = st.telegram || {};
      set('telegramStatus', tg.configured ? 'ok' : 'err',
        tg.configured
          ? T(`chat ${tg.chat_id} — approvazione ${tg.approve ? 'ABILITATA' : 'non abilitata (solo avvisi, rifiuto, modifica)'}`,
              `chat ${tg.chat_id} — approval ${tg.approve ? 'ENABLED' : 'not enabled (notify, reject, edit only)'}`,
              `chat ${tg.chat_id} — 审批${tg.approve ? '已启用' : '未启用（仅通知、拒绝、修改）'}`)
          : T('non configurato', 'not configured', '未配置'));
      // Il comando nel suggerimento: con il Python dell'app, perche' `gigamail`
      // non e' nel PATH di chi usa l'app desktop (mcp_snippets.js).
      if (window.CodexConnect) {
        refreshCodex = refreshCodex || CodexConnect.bind('codexStatus', 'btnCodexConnect');
        refreshCodex();
      }
      const tgCode = document.querySelector('[data-i18n-html="telegram_hint"] code');
      if (tgCode && window.McpSnippets) tgCode.textContent = McpSnippets.cliCommand(ag, 'telegram setup');
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
    $('desktopStatus').textContent = T('Conferma il prompt UAC di Windows…', 'Confirm the Windows UAC prompt…', '请确认 Windows UAC 提示…');
    try {
      const r = await api('/notify/desktop-setup', { method: 'POST' });
      toast(r.buttons ? T('Bottoni toast attivi.', 'Toast buttons enabled.', '通知按钮已启用。')
                      : T('Registrazione non riuscita (UAC negato?).', 'Registration failed (UAC denied?).', '注册失败（UAC 被拒绝？）。'),
            r.buttons ? 'ok' : 'error');
    } catch (e) {
      toast(e.message, 'error');
    }
    refreshNotify();
  }

  // The user's choice: sends clicked in the console go straight away, or
  // ask the OS verification like the agent's requests.
  async function onConsoleSendHello(ev) {
    const want = ev.target.checked;
    try {
      const r = await api('/console/send-hello', { method: 'POST', body: JSON.stringify({ enabled: want }) });
      ev.target.checked = !!r.console_send_hello;
      toast(want ? T('Gli invii dalla console chiederanno la verifica.', 'Sends from the console will ask for verification.', '从控制台发送将需要验证。')
                 : T('Gli invii dalla console partono al clic.', 'Sends from the console go out on click.', '从控制台发送将直接发出。'), 'ok');
    } catch (e) {
      ev.target.checked = !want;
      toast(e.message, 'error');
    }
  }

  // ------------------------------------------------------------ pending approvals
  // The requests the watcher's rules and the agent raise. Approving goes
  // through the backend, which asks Windows Hello; the window only shows
  // the outcome. The badge on the sidebar icon is refreshed from any view.
  const L = (key, fallback) => (window.i18n && window.i18n.t ? window.i18n.t(key, fallback) : fallback);
  const AV = () => window.ApprovalsView;

  // When the user last opened "waiting for you": the decided outcomes
  // counted on the icon are the ones after this moment.
  const SEEN_KEY = 'gm_pending_seen_at';
  const seenAt = () => { try { return Number(localStorage.getItem(SEEN_KEY) || 0); } catch (_) { return 0; } };
  const markSeen = () => { try { localStorage.setItem(SEEN_KEY, String(Date.now() / 1000)); } catch (_) { /* no storage */ } };

  function setBadge(pending, recent) {
    const b = $('pendingBadge');
    if (!b || !AV()) return;
    const c = AV().badgeCounts(pending, recent, seenAt());
    const pill = (cls, n, title) => (n > 0
      ? `<span class="s-pill ${cls}" title="${escapeHtml(title)}">${AV().badgeText(n)}</span>` : '');
    b.innerHTML = pill('todo', c.todo, L('pending_title', 'Richieste in attesa'))
      + pill('ok', c.ok, L('st_sent', 'inviata'))
      + pill('warn', c.warn, L('st_approved_agent', 'approvata, in esecuzione'))
      + pill('err', c.err, L('badge_err', 'fallite, rifiutate o scadute'));
    b.hidden = !b.innerHTML;
  }

  async function refreshPending() {
    const box = $('pendingList');
    const recentBox = $('recentList');
    if (!box || !AV()) return;
    try {
      const [pending, recent] = await Promise.all([api('/approvals'), api('/approvals/recent?hours=24')]);
      // the page is open: what it shows is seen
      markSeen();
      setBadge(pending, recent);
      box.innerHTML = pending.length
        ? pending.map((r) => AV().pendingCard(r, L)).join('')
        : `<div class="hint">${L('pending_none', 'Nessuna richiesta in attesa.')}</div>`;
      if (recentBox) {
        // the list redraws every 30s: a card the user opened stays open
        const open = new Set([...recentBox.querySelectorAll('details[open]')].map((d) => d.dataset.request));
        recentBox.innerHTML = recent.length
          ? recent.map((r) => AV().recentCard(r, L)).join('')
          : `<div class="hint">${L('recent_none', 'Niente nelle ultime 24 ore.')}</div>`;
        recentBox.querySelectorAll('details[data-request]').forEach((d) => { if (open.has(d.dataset.request)) d.open = true; });
      }
    } catch (e) {
      box.innerHTML = `<div class="hint">${T('Errore', 'Error', '错误')}: ${escapeHtml(e.message)}</div>`;
    }
  }

  async function pollBadge() {
    try {
      const [pending, recent] = await Promise.all([api('/approvals'), api('/approvals/recent?hours=24')]);
      setBadge(pending, recent);
      setRulesBadge(await api('/rules'));
    } catch (_) { /* no backend yet: the badge stays as it is */ }
  }

  async function onPendingAction(e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.dataset.act === 'edit') {
      // The request's own window: the text to correct, a note for the
      // agent, Save. The same window the toast's buttons open.
      if (window.electronAPI?.openApprovalWindow) window.electronAPI.openApprovalWindow(id, 'edit');
      return;
    }
    btn.disabled = true;
    try {
      if (btn.dataset.act === 'approve') {
        toast(L('pending_confirm_hello', 'Conferma con Windows Hello…'));
        const r = await api(`/approvals/${encodeURIComponent(id)}/approve`, { method: 'POST' });
        if (r.status === 'executed' && r.outcome === 'failed') {
          toast(`${L('st_send_failed', 'invio fallito')}: ${r.error || ''}`, 'error');
        } else if (r.status === 'executed') {
          toast(r.completed_by === 'watcher'
            ? L('pending_approved_watcher', 'Approvata e inviata.')
            : L('pending_approved_agent', 'Approvata ed eseguita.'), 'ok');
        } else {
          toast(`${L('st_approved_agent', 'approvata, in esecuzione')}${r.error ? ': ' + r.error : ''}`, 'ok');
        }
      } else if (btn.dataset.act === 'reject') {
        await api(`/approvals/${encodeURIComponent(id)}/reject`, { method: 'POST' });
        toast(L('pending_rejected_msg', 'Rifiutata: non parte nulla.'), 'ok');
      }
    } catch (err) {
      toast(err.message, 'error');
      btn.disabled = false;
    }
    refreshPending();
  }

  async function refreshAll() {
    await Promise.all([refreshPending(), refreshRules(), refreshWatch(), refreshNotify(), fillAccounts(),
      window.SpamFilterUI ? window.SpamFilterUI.refreshList() : null]);
  }

  // ------------------------------------------------------------ bind
  document.addEventListener('DOMContentLoaded', () => {
    $('btnShowAutomations')?.addEventListener('click', showView);
    $('btnShowPending')?.addEventListener('click', showPendingView);
    // a popup opened by a notification asks the main window for the list
    if (window.electronAPI?.onShowPending) window.electronAPI.onShowPending(showPendingView);
    $('agentSelect')?.addEventListener('change', async (e) => {
      try {
        await api('/agent/select', { method: 'POST', body: JSON.stringify({ agent: e.target.value }) });
      } catch (err) {
        set('agentStatus', 'err', err.message);
      }
      refreshNotify();
    });
    // qualunque altra voce della sidebar riporta alla posta
    document.querySelectorAll('.sidebar .s-item').forEach((item) => {
      if (item.id !== 'btnShowAutomations' && item.id !== 'btnShowPending' && item.id !== 'langSwitch' && item.id !== 'themeSwitch' && item.id !== 'accentSwitch') {
        item.addEventListener('click', leaveView, true);
      }
    });
    $('rulesList')?.addEventListener('click', onRuleAction);
    $('pendingList')?.addEventListener('click', onPendingAction);
    // the badge follows the watcher from any view; the list only while shown
    setTimeout(pollBadge, 4000);
    setInterval(() => {
      if ($('view-pending')?.classList.contains('active')) refreshPending();
      else pollBadge();
    }, 30000);
    $('btnCreateRule')?.addEventListener('click', onCreateRule);
    $('btnCancelEdit')?.addEventListener('click', cancelEditRule);
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
    $('consoleSendHello')?.addEventListener('change', onConsoleSendHello);
    $('btnNotifyRefresh')?.addEventListener('click', refreshNotify);
    // Rotella: scorre .auto-body ovunque sia il puntatore nella vista
    // (non solo sopra la barra), anche quando il target e' un campo.
    for (const id of ['view-automations', 'view-pending']) {
      const body = document.querySelector(`#${id} .auto-body`);
      $(id)?.addEventListener('wheel', (ev) => {
        if (!body) return;
        if (ev.target.closest('.auto-log')) return; // il log scorre da solo
        body.scrollTop += ev.deltaY;
        ev.preventDefault();
      }, { passive: false });
    }
    onTriggerKindChange();
    onModeChange();
    renderDocs();
    // aggiornamento periodico mentre la vista e' aperta
    setInterval(() => {
      if ($('view-automations')?.classList.contains('active')) refreshWatch();
    }, 15000);
  });
})();
