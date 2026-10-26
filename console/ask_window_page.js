// ask_window_page.js — the script of ask_window.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
let accountId = null;
let history = [];

const messages = document.getElementById('askMessages');
const input = document.getElementById('askInput');
const sendBtn = document.getElementById('askSend');
const emptyEl = document.getElementById('askEmpty');

// Ricevi account_id dalla finestra principale
if (window.askWindowAPI) {
  window.askWindowAPI.onLoad((data) => {
    accountId = data?.account_id ?? null;
  });
}

document.getElementById('btnClose').addEventListener('click', () => window.askWindowAPI?.close());
document.getElementById('btnMin').addEventListener('click',   () => window.askWindowAPI?.minimize());
document.getElementById('btnMax').addEventListener('click',   () => window.askWindowAPI?.maximize());

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function addMsg(text, role, cited){
  if (emptyEl) emptyEl.style.display = 'none';
  const div = document.createElement('div');
  div.className = `ask-msg ${role}`;
  div.textContent = text;
  if (cited && cited.length){
    const box = document.createElement('div');
    box.className = 'ask-cited';
    cited.forEach((c, i) => {
      const chip = document.createElement('div');
      chip.className = 'ask-cite-chip';
      chip.innerHTML = `<span class="ask-cite-num">[${i+1}]</span>
        <div class="ask-cite-body">
          <div class="ask-cite-subj">${esc(c.subject)}</div>
          <div class="ask-cite-from">${esc(c.sender)}</div>
        </div>`;
      chip.addEventListener('click', () => {
        if (c.message_id) {
          window.askWindowAPI?.openMail({ id: c.message_id, folder: c.folder, account_id: c.account_id || accountId });
        }
      });
      box.appendChild(chip);
    });
    div.appendChild(box);
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

async function send(){
  const q = input.value.trim();
  if (!q) return;
  input.value = '';
  addMsg(q, 'user');
  history.push({ role:'user', content:q });
  sendBtn.disabled = true;
  const loading = addMsg(window.i18n?window.i18n.t('searching'):'Sto cercando…', 'bot');
  loading.classList.add('loading');
  try {
    const r = await fetch(`${API}/mail_ask`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ question:q, account_id:accountId, history, lang:(window.i18n?window.i18n.lang:(localStorage.getItem('ade_lang')||'it')) })
    });
    const d = await r.json().catch(() => ({}));
    loading.remove();
    if (!r.ok) {
      // Prima un errore del backend (agente scollegato, 503) diventava
      // "(nessuna risposta)": il motivo vero non arrivava mai a video.
      addMsg((window.i18n?window.i18n.t('error'):'Errore') + ': ' + (d.detail || `HTTP ${r.status}`), 'bot');
      sendBtn.disabled = false;
      input.focus();
      return;
    }
    addMsg(d.answer || (window.i18n?window.i18n.t('no_answer'):'(nessuna risposta)'), 'bot', d.cited_mails);
    history.push({ role:'assistant', content:d.answer||'', cited_thread_ids:d.cited_thread_ids||[] });
    if (history.length > 20) history = history.slice(-20);  // tieni ultimi ~10 scambi (user+bot)
  } catch(e) {
    loading.remove();
    addMsg((window.i18n?window.i18n.t('error'):'Errore') + ': ' + e.message, 'bot');
  }
  sendBtn.disabled = false;
  input.focus();
}

sendBtn.addEventListener('click', send);
input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
input.focus();
