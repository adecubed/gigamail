/**
 * claude_login_panel.js: signing Claude Code in from Automations.
 *
 * The console's "ready" only says the program exists. Its sign-in is separate
 * from the Claude desktop app's and can expire, and until now the button
 * appeared only after a question to the agent bar had failed: a user whose
 * rules had stopped drafting had nowhere to press it. This panel asks the
 * backend for the real state and offers the sign-in next to the agent choice.
 */
(function () {
  const CLAUDE_URL = /^https:\/\/(claude\.com|claude\.ai|platform\.claude\.com|console\.anthropic\.com)\//;
  const LOGIN_MAX_MS = 10 * 60 * 1000;
  const $ = (id) => document.getElementById(id);
  const L = (key, fallback) => (window.i18n && window.i18n.t ? window.i18n.t(key, fallback) : fallback);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  let busy = false;    // a sign-in is running: a refresh must not redraw it away
  let asked = 0;       // only the latest refresh may draw

  function status(cls, text) {
    const el = $('agentStatus');
    if (!el) return;
    el.className = 'ai-card-status ' + cls;
    el.textContent = text;
  }

  function hide(box) {
    box.innerHTML = '';
    box.style.display = 'none';
  }

  function button(box) {
    const b = document.createElement('button');
    b.className = 'chip-btn';
    b.dataset.act = 'claude-login';
    b.textContent = L('agent_login_btn', 'Accedi a Claude');
    b.addEventListener('click', () => login(box));
    box.appendChild(b);
  }

  function note(box, text) {
    const d = document.createElement('div');
    d.className = 'agent-login-wait';
    d.textContent = text;
    box.appendChild(d);
  }

  function offer(box, text) {
    box.innerHTML = '';
    box.style.display = '';
    note(box, text);
    button(box);
  }

  function showManual(box, url) {
    const manual = document.createElement('div');
    manual.className = 'agent-login-manual';
    manual.append(L('agent_login_manual', 'Il browser non si è aperto? Apri') + ' ');
    const a = document.createElement('a');
    a.className = 'agent-login-url';
    a.target = '_blank';
    a.rel = 'noopener';
    a.href = url;
    a.textContent = L('agent_login_page', 'la pagina di accesso');
    manual.append(a, ' ' + L('agent_login_paste', 'e incolla qui il codice che ti mostra.'));
    const row = document.createElement('div');
    row.className = 'agent-login-code';
    const input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.placeholder = L('agent_login_code_ph', 'Codice');
    const send = document.createElement('button');
    send.className = 'chip-btn';
    send.dataset.act = 'claude-login-code';
    send.textContent = L('agent_login_code_send', 'Invia');
    send.addEventListener('click', async () => {
      const code = input.value.trim();
      if (!code) return;
      try {
        await window.electronAPI.claudeLoginCode(code);
      } catch (e) {
        status('err', e.message || String(e));
      }
    });
    row.append(input, send);
    manual.appendChild(row);
    box.appendChild(manual);
  }

  async function login(box) {
    if (busy) return;
    busy = true;
    try {
      box.innerHTML = '';
      note(box, L('agent_login_wait_panel', 'Si è aperto il browser: autorizza l\'accesso a Claude.'));
      let st;
      try {
        st = await window.electronAPI.claudeLoginStart();
      } catch (e) {
        offer(box, e.message || String(e));
        return;
      }
      const until = Date.now() + LOGIN_MAX_MS;
      let manual = false;
      while (Date.now() < until) {
        if (st && st.logged_in) {
          hide(box);
          status('ok', L('agent_login_ok', 'Claude Code collegato'));
          return;
        }
        if (st && !st.pending) break;
        if (st && st.url && !manual && CLAUDE_URL.test(st.url)) {
          manual = true;
          showManual(box, st.url);
        }
        await sleep(api.POLL_MS);
        try {
          st = await window.electronAPI.claudeLoginStatus();
        } catch (e) { /* the backend may be restarting: keep waiting */ }
      }
      offer(box, L('agent_login_failed', 'Accesso non completato.'));
    } finally {
      busy = false;
    }
  }

  // `agent` is the status the backend gave for the selected agent.
  async function refresh(agent) {
    const box = $('claudeLoginBox');
    if (!box || busy) return;
    const mine = ++asked;
    if (!agent || agent.agent !== 'claude' || !agent.available
        || !window.electronAPI || !window.electronAPI.claudeLoginStatus) {
      hide(box);
      return;
    }
    let st;
    try {
      st = await window.electronAPI.claudeLoginStatus();
    } catch (e) {
      return;   // state unknown: say nothing rather than something false
    }
    if (mine !== asked || busy) return;
    if (st && st.pending) {   // started from the agent bar: it is following it
      hide(box);
      return;
    }
    if (st && st.logged_in) {
      hide(box);
      return;
    }
    status('err', L('agent_login_badge', 'installato, ma non collegato'));
    offer(box, L('agent_login_missing',
      'Claude Code non ha fatto l\'accesso: le regole non possono scrivere bozze. L\'accesso è separato da quello dell\'app Claude.'));
  }

  const api = { refresh, POLL_MS: 2000 };
  window.ClaudeLoginPanel = api;
})();
