// codex_connect.js — il pulsante "Collega" per ChatGPT e Codex, nella guida
// iniziale e nelle impostazioni. Il backend scrive la voce gigamail nel
// config.toml di Codex, che l'app desktop di ChatGPT (anche Work) legge
// uguale: niente `codex mcp add` da digitare (core/codex_config.py).
(function () {
  const API = () => window.GIGAMAIL_API || 'http://127.0.0.1:8002';
  const tr = (key, fallback) => (typeof T === 'function' ? T(key, fallback) : fallback);

  /** Il testo e la classe dello stato, da GET /agent/codex. */
  function label(st) {
    if (!st) return { cls: 'err', text: tr('codex_unknown', 'stato sconosciuto') };
    if (st.error) return { cls: 'err', text: `${tr('codex_unreadable', 'config.toml di Codex illeggibile')}: ${st.error}` };
    if (st.connected) return { cls: 'ok', text: tr('codex_ok', 'collegato: apri una nuova chat in ChatGPT o Codex') };
    if (st.entry) return { cls: 'warn', text: `${tr('codex_other', 'punta a un altro GigaMail')}: ${st.entry.command}` };
    return { cls: 'warn', text: tr('codex_off', 'non collegato') };
  }

  async function call(path, opts) {
    const r = await fetch(API() + path, opts);
    let data = null;
    try { data = await r.json(); } catch (_) { /* nessun corpo */ }
    if (!r.ok) throw new Error((data && data.detail) || `HTTP ${r.status}`);
    return data;
  }

  function show(statusEl, btn, st, error) {
    const base = statusEl.dataset.base || '';
    const l = error ? { cls: 'err', text: error } : label(st);
    statusEl.textContent = l.text;
    statusEl.className = `${base} ${l.cls}`.trim();
    btn.textContent = st && st.connected ? tr('codex_reconnect', 'Ricollega') : tr('codex_connect', 'Collega');
  }

  /** Lega pulsante e stato; restituisce la funzione che rilegge lo stato. */
  function bind(statusId, btnId) {
    const statusEl = document.getElementById(statusId);
    const btn = document.getElementById(btnId);
    if (!statusEl || !btn) return () => {};
    statusEl.dataset.base = statusEl.className;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        show(statusEl, btn, await call('/agent/codex/connect', { method: 'POST' }));
      } catch (e) {
        show(statusEl, btn, null, e.message || String(e));
      } finally {
        btn.disabled = false;
      }
    });
    return async () => {
      try { show(statusEl, btn, await call('/agent/codex')); }
      catch (e) { show(statusEl, btn, null, e.message || String(e)); }
    };
  }

  const CodexConnect = { bind, label };
  if (typeof window !== 'undefined') window.CodexConnect = CodexConnect;
  if (typeof module !== 'undefined' && module.exports) module.exports = CodexConnect;
})();
