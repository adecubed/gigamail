// renderer_agent.js — la barra in fondo alla scheda di destra: l'utente
// chiede qualsiasi cosa all'agente. Le domande tornano come risposta; le
// azioni pericolose tornano come richieste da approvare qui, nella scheda.
(function () {
  const L = (key, it) => (window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it;
  const lang = () => (window.i18n && window.i18n.lang) || 'it';
  const $ = (id) => document.getElementById(id);
  const escHtml = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const history = [];        // ultimi giri, mandati all'agente come contesto
  let busy = false;
  let useMail = true;        // il chip "questa mail" e' attivo

  // A mail the agent mentions comes as a markdown link with this scheme
  // (the prompt asks for it): [subject](gigamail://mail/<account>/<id>?folder=<f>).
  // The text is escaped first, so the link is matched on escaped text and
  // only this scheme becomes clickable: an http link written by the agent
  // (or by a mail it read) stays plain text.
  const MAIL_LINK = /\[([^\]\n]+)\]\(gigamail:\/\/mail\/(\d+)\/([^)\s?]+)(?:\?folder=([^)\s]*))?\)/g;

  // agent text: escape, then mail links, bold and line breaks only
  function formatAnswer(text) {
    return escHtml(text)
      .replace(MAIL_LINK, (_m, label, account, id, folder) =>
        `<a href="#" class="agent-mail-link" data-account="${account}" data-id="${id}"` +
        ` data-folder="${folder || ''}">${label}</a>`)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>')
      .replace(/\n/g, '<br>');
  }

  // What a clicked mail link opens: the reading pane when the mail is in the
  // account on screen, its own window otherwise (the pane reads from the
  // active account only).
  function mailLinkTarget(el) {
    const account = parseInt(el.dataset.account, 10);
    const id = el.dataset.id || '';
    if (!account || !id) return null;
    let folder = el.dataset.folder || '';
    try { folder = decodeURIComponent(folder); } catch { /* keep it as written */ }
    const active = (typeof activeAccountId !== 'undefined') ? activeAccountId : null;
    const merged = (typeof activeGroup !== 'undefined') && activeGroup;
    const inPane = !merged && String(active) === String(account) && typeof window.openMail === 'function';
    return { account, id, folder: folder || null, inPane };
  }

  function openMailLink(el) {
    const t = mailLinkTarget(el);
    if (!t) return;
    if (t.inPane) window.openMail(t.id, t.folder);
    else if (window.electronAPI && window.electronAPI.openMailWindow) {
      window.electronAPI.openMailWindow({ id: t.id, folder: t.folder, account_id: t.account });
    }
  }

  function openMail() {
    const id = window._currentMailId;
    if (!id || !document.querySelector('#mailDetail .mail-detail-subject')) return null;
    const subj = document.querySelector('#mailDetail .mail-detail-subject');
    return { id, folder: window._currentMailFolder || null,
      subject: subj ? subj.textContent.trim() : '' };
  }

  function refreshChip() {
    const chip = $('agentChip');
    if (!chip) return;
    const mail = openMail();
    if (!mail || !useMail) { chip.hidden = true; return; }
    chip.hidden = false;
    $('agentChipText').textContent = mail.subject || L('agent_this_mail', 'Questa mail');
  }

  function scrollThread() {
    const th = $('agentThread');
    if (th) th.scrollTop = th.scrollHeight;
  }

  function addBubble(kind, html) {
    const th = $('agentThread');
    const el = document.createElement('div');
    el.className = `agent-msg ${kind}`;
    el.innerHTML = html;
    th.appendChild(el);
    $('agentBar').classList.add('has-thread');
    scrollThread();
    return el;
  }

  function addThinking() {
    return addBubble('agent thinking',
      `<span class="agent-dots"><i></i><i></i><i></i></span> ${escHtml(L('agent_thinking', 'L\'agente sta lavorando…'))}`);
  }

  // ── memory: the conversation survives a restart ─────────────────────────
  // Kept in this computer's localStorage (the console's own profile), never
  // sent anywhere but to the agent, as the last turns of context. Clear
  // wipes it.
  const STORE_KEY = 'gm-agent-thread-v1';
  const MAX_ENTRIES = 60;
  let log = [];   // {k:'user'|'agent'|'error'|'note'|'appr', t, c, a, q, s}

  function save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        history: history.slice(-12), log: log.slice(-MAX_ENTRIES),
      }));
    } catch (e) { /* storage full or off: the thread just is not kept */ }
  }

  function load() {
    try {
      const data = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (!data || !Array.isArray(data.log)) return;
      (Array.isArray(data.history) ? data.history : []).forEach((h) => {
        if (h && (h.role === 'user' || h.role === 'agent')) history.push({ role: h.role, text: String(h.text || '') });
      });
      data.log.forEach(renderEntry);
      log = data.log.slice(-MAX_ENTRIES);
    } catch (e) { /* unreadable: start empty */ }
  }

  function remember(entry) {
    log.push(entry);
    if (log.length > MAX_ENTRIES) log = log.slice(-MAX_ENTRIES);
    save();
    return entry;
  }

  // Draws an entry, from a live answer or from the saved thread. Every text
  // goes through escHtml / formatAnswer: what comes back from storage is
  // treated as untrusted as what comes from the agent.
  function renderEntry(e) {
    if (!e || typeof e !== 'object') return;
    if (e.k === 'user') {
      addBubble('user', escHtml(e.t) + (e.c ? `<div class="agent-msg-ctx">${escHtml(e.c)}</div>` : ''));
    } else if (e.k === 'agent') {
      addBubble('agent', formatAnswer(e.t));
    } else if (e.k === 'error') {
      addBubble('agent error', escHtml(e.t));
    } else if (e.k === 'note') {
      addBubble('agent note', escHtml(e.t));
    } else if (e.k === 'appr' && e.a) {
      approvalCard(e.a, e.q, e);
    }
  }

  const say = (k, t, c) => renderEntry(remember({ k, t: String(t || ''), c: c || '' }));

  // ── runs: one id per request, so Stop ends the right one ────────────────
  let currentRun = null;
  function newRunId() {
    try { if (window.crypto && crypto.randomUUID) return crypto.randomUUID(); } catch (e) { /* fall back */ }
    return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }

  const STATES = {
    approved: ['approved', 'agent_approved', 'Approvata'],
    executed: ['approved', 'agent_executed', 'Approvata ed eseguita'],
    'not-run': ['not-run', 'agent_not_run', 'Approvata, ma non eseguita'],
    failed: ['not-run', 'agent_run_failed', 'Approvata, ma l\'esecuzione è fallita'],
    rejected: ['rejected', 'agent_rejected', 'Rifiutata: non verrà eseguita'],
  };

  // `question` is the request that opened the approval: the confirmation
  // after it comes back in the language the user wrote it in. `entry` is
  // its saved form: the card keeps its state across a restart.
  function approvalCard(a, question, entry) {
    entry = entry || remember({ k: 'appr', a: {
      request_id: a.request_id, tool: a.tool, subject: a.subject, summary: a.summary,
      to: a.to || '', body: String(a.body || '').slice(0, 20000),
    }, q: question || '', s: 'pending' });
    // What is being approved, in full: the recipient and the text itself,
    // not just the one-line summary (the user could not read the reply
    // before sending it).
    const body = String(a.body || '');
    const el = addBubble('approval', `
      <div class="agent-appr-head">${escHtml(L('agent_waiting', 'In attesa della tua approvazione'))}</div>
      <div class="agent-appr-title">${escHtml(a.subject || a.tool)}</div>
      ${a.to ? `<div class="agent-appr-sum">${escHtml(L('pending_to', 'a'))} ${escHtml(a.to)}</div>` : ''}
      ${body ? `<details class="agent-appr-body" open><summary>${escHtml(L('pending_body', 'Testo'))}</summary><pre>${escHtml(body)}</pre></details>`
        : (a.summary ? `<div class="agent-appr-sum">${escHtml(a.summary)}</div>` : '')}
      <div class="agent-appr-actions">
        <button class="agent-btn ghost" data-act="reject">${escHtml(L('agent_reject', 'Rifiuta'))}</button>
        <button class="agent-btn primary" data-act="approve">${escHtml(L('agent_approve', 'Approva'))}</button>
      </div>`);
    el.dataset.requestId = a.request_id;
    const state = (name) => {
      const [cls, key, it] = STATES[name];
      el.classList.remove('approved', 'not-run', 'rejected');
      el.classList.add(cls);
      el.querySelector('.agent-appr-head').textContent = L(key, it);
      el.querySelector('.agent-appr-actions').innerHTML = '';
      entry.s = name;
      save();
    };
    if (entry.s && entry.s !== 'pending' && STATES[entry.s]) { state(entry.s); return el; }
    el.querySelector('[data-act="approve"]').addEventListener('click', async (ev) => {
      if (busy) return;
      const btn = ev.currentTarget;
      btn.disabled = true;
      // A click in the console approves at once. If the backend still asks
      // the OS verification (the option in Automations, or a backend that
      // does not know this console), its prompt can sit behind the windows.
      const hint = setTimeout(() => {
        const h = document.createElement('div');
        h.className = 'agent-appr-sum agent-appr-wait';
        h.textContent = L('agent_hello_wait', 'In attesa della verifica di Windows Hello: se non la vedi, è dietro le finestre (Alt+Tab).');
        el.querySelector('.agent-appr-actions').before(h);
      }, 3000);
      let approved;
      try {
        approved = await window.electronAPI.approveRequest(a.request_id);
      } catch (e) {
        clearTimeout(hint);
        el.querySelector('.agent-appr-wait')?.remove();
        btn.disabled = false;
        say('error', `${L('agent_not_approved', 'Non approvata')}: ${e.message || e}`);
        return;
      }
      clearTimeout(hint);
      el.querySelector('.agent-appr-wait')?.remove();
      // GigaMail completes an approved request itself (the same from
      // Telegram, the pending page or the CLI): nothing left for the
      // agent to call. Older backends answer "approved" and still wait
      // for the agent.
      if (approved && approved.status === 'executed') {
        state(approved.outcome === 'failed' ? 'failed' : 'executed');
        if (approved.outcome === 'failed' && approved.error) say('error', approved.error);
        return;
      }
      state('approved');
      const wait = addThinking();
      setBusy(true);
      currentRun = newRunId();
      try {
        const r = await window.electronAPI.agentComplete({
          request_id: a.request_id, lang: lang(), question: question || '', run_id: currentRun,
        });
        wait.remove();
        // What GigaMail recorded, not what the agent wrote: an agent that
        // could not call the tool may still answer "done".
        // "executed" means the request was used; the outcome says whether the
        // provider accepted it. A failed send must not read as done.
        state(r.status === 'executed' && r.outcome !== 'failed' ? 'executed'
          : r.status === 'executed' ? 'failed' : 'not-run');
        if (r.cancelled) {
          say('note', L('agent_stopped', 'Fermato.'));
        } else {
          say('agent', r.answer || L('agent_done', 'Fatto.'));
          history.push({ role: 'agent', text: r.answer || '' });
          save();
        }
      } catch (e) {
        wait.remove();
        say('error', e.message || String(e));
      } finally {
        currentRun = null;
        setBusy(false);
      }
    });
    el.querySelector('[data-act="reject"]').addEventListener('click', async () => {
      try {
        await window.electronAPI.rejectRequest(a.request_id);
        state('rejected');
      } catch (e) {
        say('error', e.message || String(e));
      }
    });
    return el;
  }

  function setBusy(on) {
    busy = on;
    const btn = $('agentSend');
    btn.classList.toggle('stop', on);
    btn.textContent = on ? '■' : '↑';
    btn.setAttribute('aria-label', on ? L('agent_stop', 'Ferma') : L('send', 'Invia'));
    btn.title = on ? L('agent_stop', 'Ferma') : '';
    autoGrow();
  }

  function autoGrow() {
    const ta = $('agentInput');
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`;
    // while the agent works the button is Stop, and Stop is always available
    $('agentSend').disabled = busy ? !currentRun : !ta.value.trim();
  }

  async function stop() {
    if (!currentRun) return;
    const btn = $('agentSend');
    btn.disabled = true;
    try { await window.electronAPI.agentCancel({ run_id: currentRun }); } catch (e) { /* the answer will say */ }
  }

  // ── Claude Code signed out: sign in from here, no terminal ──────────────
  // The backend says so with X-GigaMail-Error: agent_login (e.code). The
  // CLI opens the browser on the consent page and the request goes out
  // again once the user has authorised it. When the page cannot hand the
  // code back, its address and a field for the code show up here.
  const CLAUDE_URL = /^https:\/\/(claude\.com|claude\.ai|platform\.claude\.com|console\.anthropic\.com)\//;
  const LOGIN_MAX_MS = 10 * 60 * 1000;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function loginBubble(msg, question) {
    remember({ k: 'error', t: msg });
    const el = addBubble('agent error', `${escHtml(msg)}
      <div class="agent-login"><button class="agent-btn primary" data-act="claude-login">${
        escHtml(L('agent_login_btn', 'Accedi a Claude'))}</button></div>`);
    el.querySelector('[data-act="claude-login"]').addEventListener('click', () => claudeLogin(el, question));
  }

  function showManual(box, url) {
    const manual = document.createElement('div');
    manual.className = 'agent-login-manual';
    manual.innerHTML = `${escHtml(L('agent_login_manual', 'Il browser non si è aperto? Apri'))}
      <a class="agent-login-url" target="_blank" rel="noopener" href="${escHtml(url)}">${
        escHtml(L('agent_login_page', 'la pagina di accesso'))}</a>
      ${escHtml(L('agent_login_paste', 'e incolla qui il codice che ti mostra.'))}
      <div class="agent-login-code"><input type="text" autocomplete="off" spellcheck="false"
        placeholder="${escHtml(L('agent_login_code_ph', 'Codice'))}">
        <button class="agent-btn ghost" data-act="claude-login-code">${escHtml(L('agent_login_code_send', 'Invia'))}</button></div>`;
    manual.querySelector('[data-act="claude-login-code"]').addEventListener('click', async () => {
      const code = manual.querySelector('input').value.trim();
      if (!code) return;
      try { await window.electronAPI.claudeLoginCode(code); } catch (e) { say('error', e.message || String(e)); }
    });
    box.appendChild(manual);
  }

  async function claudeLogin(el, question) {
    const box = el.querySelector('.agent-login');
    box.innerHTML = `<div class="agent-login-wait">${escHtml(L('agent_login_wait',
      'Si è aperto il browser: autorizza l\'accesso a Claude. Poi la richiesta riparte da sola.'))}</div>`;
    let st;
    try {
      st = await window.electronAPI.claudeLoginStart();
    } catch (e) {
      box.textContent = e.message || String(e);
      return;
    }
    const until = Date.now() + LOGIN_MAX_MS;
    let manual = false;
    while (Date.now() < until) {
      if (!el.isConnected) return;   // Clear: nobody is waiting for this any more
      if (st && st.logged_in) {
        box.remove();
        say('note', L('agent_login_done', 'Accesso fatto: riprovo.'));
        if (question) send(question);
        return;
      }
      if (st && !st.pending) break;
      if (st && st.url && !manual && CLAUDE_URL.test(st.url)) { manual = true; showManual(box, st.url); }
      await sleep(window.AgentView.LOGIN_POLL_MS);
      try { st = await window.electronAPI.claudeLoginStatus(); } catch (e) { /* the backend may be restarting: keep waiting */ }
    }
    box.innerHTML = `<div class="agent-login-wait">${escHtml(L('agent_login_failed',
      'Accesso non completato.'))}</div><button class="agent-btn primary" data-act="claude-login">${
      escHtml(L('agent_login_btn', 'Accedi a Claude'))}</button>`;
    box.querySelector('[data-act="claude-login"]').addEventListener('click', () => claudeLogin(el, question));
  }

  // `again`: the question of a request that stopped on the sign-in, sent
  // once more without touching what the user is typing now.
  async function send(again) {
    const ta = $('agentInput');
    const retry = typeof again === 'string';
    const question = retry ? again : ta.value.trim();
    if (!question || busy) return;
    const mail = useMail ? openMail() : null;
    // a retry: the question is on screen and in the history already
    if (!retry) {
      ta.value = '';
      say('user', question, mail ? (mail.subject || L('agent_this_mail', 'Questa mail')) : '');
    }
    const wait = addThinking();
    currentRun = newRunId();
    setBusy(true);
    const body = {
      question, lang: lang(), history: history.slice(-6), run_id: currentRun,
      account_id: (typeof activeAccountId !== 'undefined' && activeAccountId) || null,
      mail_id: mail ? mail.id : null, folder: mail ? mail.folder : null,
    };
    if (!retry) history.push({ role: 'user', text: question });
    save();
    try {
      const r = await window.electronAPI.agentCommand(body);
      wait.remove();
      if (r.cancelled) {
        say('note', L('agent_stopped', 'Fermato.'));
      } else {
        say('agent', r.answer || L('no_answer', '(nessuna risposta)'));
        history.push({ role: 'agent', text: r.answer || '' });
        save();
      }
      (r.approvals || []).forEach((a) => approvalCard(a, question));
    } catch (e) {
      wait.remove();
      const msg = String(e.message || e);
      if (e.code === 'agent_login' && window.electronAPI.claudeLoginStart) {
        loginBubble(msg, question);
        return;
      }
      say('error', /^not found$/i.test(msg)
        ? L('agent_old_backend', 'Il backend in uso non conosce ancora questa funzione: chiudi GigaMail (anche dall\'icona vicino all\'orologio) e riaprila.')
        : /agent|agente|claude|codex|antigravity/i.test(msg) && /install|trovat|found|unavailable/i.test(msg)
        ? L('agent_unavailable', 'Nessun agente trovato. Installa Claude Code, Codex o Antigravity e riprova.')
        : msg);
    } finally {
      currentRun = null;
      setBusy(false);
    }
  }

  function clearThread() {
    $('agentThread').innerHTML = '';
    history.length = 0;
    log = [];
    try { localStorage.removeItem(STORE_KEY); } catch (e) { /* nothing kept anyway */ }
    $('agentBar').classList.remove('has-thread');
  }

  function init() {
    const ta = $('agentInput');
    if (!ta || !window.electronAPI || !window.electronAPI.agentCommand) return;
    ta.addEventListener('input', autoGrow);
    ta.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); send(); }
    });
    $('agentSend').addEventListener('click', () => (busy ? stop() : send()));
    $('agentSend').setAttribute('aria-label', L('send', 'Invia'));
    $('agentClear').addEventListener('click', clearThread);
    $('agentThread').addEventListener('click', (ev) => {
      const link = ev.target.closest && ev.target.closest('.agent-mail-link');
      if (!link) return;
      ev.preventDefault();
      openMailLink(link);
    });
    $('agentChipX').addEventListener('click', () => { useMail = false; refreshChip(); });
    // nuova mail aperta: il chip torna attivo e mostra il suo oggetto
    let lastId = null;
    new MutationObserver(() => {
      if (window._currentMailId !== lastId) { lastId = window._currentMailId; useMail = true; }
      refreshChip();
    }).observe($('mailDetail'), { childList: true, subtree: false });
    load();
    refreshChip();
    autoGrow();
  }

  window.AgentView = { formatAnswer, mailLinkTarget, LOGIN_POLL_MS: 2000 };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
