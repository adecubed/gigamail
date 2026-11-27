// key_change_dialog.js — the window where the user decides about a
// correspondent's new OpenPGP key (core/pgp.py decide_change).
//
// The dialog shows the fingerprints it read from GET /encryption/peer_key
// and posts exactly the held fingerprint it showed: a key that arrived in
// between is refused by the server (409) and the dialog shows the new state
// instead. The decision route answers only to a click in the console; the
// main process adds that proof to this window's requests by itself.
//
// The pure parts (model, pendingLine, the decide flow with an injected
// fetchFn and ui) run under node --test; the DOM part is the default ui.
(function () {
  const ID = (k, it) => it;

  function formatFingerprint(fpr) {
    const s = String(fpr || '').replace(/\s+/g, '').toUpperCase();
    return s ? s.match(/.{1,4}/g).join(' ') : '';
  }

  // {name} placeholders filled with a function: a '$' in an address stays text.
  function fillText(s, vars) {
    return String(s).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  }

  // Seconds since the epoch -> the user's short date.
  function defaultFormatDate(ts) {
    if (ts == null || ts === '') return '';
    try {
      const loc = (typeof window !== 'undefined' && window.i18n && window.i18n.locale) || undefined;
      return new Date(Number(ts) * 1000).toLocaleDateString(loc, { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (_) { return ''; }
  }

  /** What the decision window shows for a peer_key_info answer. Pure. */
  function model(info, T, formatDate) {
    T = T || ID;
    formatDate = formatDate || defaultFormatDate;
    const address = (info && info.address) || '';
    const known = info && info.known;
    const held = info && info.held;
    const refused = !!(held && held.state === 'refused');
    const rows = [];
    if (known) {
      rows.push({
        label: T('kc_known_key', 'Chiave che conoscevi'),
        fingerprint: formatFingerprint(known.fingerprint),
        when: fillText(T('kc_seen_from_to', 'vista dal {from} al {to}'),
          { from: formatDate(known.first_seen), to: formatDate(known.last_seen) }),
      });
    }
    if (held) {
      rows.push({
        label: refused ? T('kc_refused_key', 'Chiave rifiutata') : T('kc_new_key', 'Chiave nuova'),
        fingerprint: formatFingerprint(held.fingerprint),
        when: fillText(T('kc_arrived_on', 'arrivata il {date}'), { date: formatDate(held.first_seen) }),
      });
    }
    const hint = T('kc_hint', 'Se ha reinstallato o cambiato computer, è normale.\nNel dubbio, chiedigli l\'impronta per telefono.');
    if (refused) {
      return {
        title: fillText(T('kc_title_refused', '{address}: hai rifiutato questa chiave'), { address }),
        rows, hint, keepWarning: '',
        // The action of the button that gets the focus: never 'accept', so a
        // reflexive Enter decides nothing.
        focus: 'later',
        buttons: [
          { action: 'accept', label: T('kc_accept_after_all', 'Accettala comunque'), primary: true },
          { action: 'later', label: T('kc_close', 'Chiudi') },
        ],
      };
    }
    return {
      title: fillText(T('kc_title', '{address} ha una chiave di cifratura nuova'), { address }),
      rows, hint,
      keepWarning: T('kc_keep_warning', 'Se ha davvero cambiato chiave, non potrà leggere quello che cifri per questo indirizzo.'),
      focus: 'later',
      buttons: [
        { action: 'accept', label: T('kc_accept_new', 'Accetta la chiave nuova'), primary: true },
        { action: 'keep', label: T('kc_keep_old', 'Tieni la vecchia') },
        { action: 'later', label: T('kc_later', 'Più tardi') },
      ],
    };
  }

  /** The main window's line above the mail list; '' when nothing waits. */
  function pendingLine(count, T) {
    T = T || ID;
    const n = Number(count) || 0;
    if (n <= 0) return '';
    return fillText(T('kc_pending_line', 'Chiavi nuove da accettare: {n}'), { n });
  }

  function infoUrl(api, address) {
    return `${api}/encryption/peer_key?address=${encodeURIComponent(address)}`;
  }

  /** Opens the decision window for `address`. opts: {api, address, T,
   * fetchFn, onDone, formatDate, ui}. Resolves with the decide answer, or
   * null when nothing was decided; onDone gets the same value. */
  async function open(opts) {
    const T = opts.T || ID;
    const fetchFn = opts.fetchFn || ((u, init) => fetch(u, init));
    const ui = opts.ui || domUi();
    const address = opts.address;
    const finish = (result) => {
      ui.close();
      if (opts.onDone) {
        try { opts.onDone(result); } catch (e) { console.warn('[key change] onDone', e); }
      }
      return result;
    };

    async function load() {
      try {
        const r = await fetchFn(infoUrl(opts.api, address));
        if (!r.ok) return null;
        return await r.json();
      } catch (_) { return null; }
    }

    let info = await load();
    let error = '';
    for (;;) {
      if (!info) {
        await ui.notice(T('kc_err_load', 'Non riesco a leggere le chiavi di questo indirizzo.'));
        return finish(null);
      }
      if (!info.held) {
        await ui.notice(fillText(T('kc_nothing_waiting', 'Nessuna chiave in attesa per {address}.'), { address }));
        return finish(null);
      }
      ui.render(model(info, T, opts.formatDate), error);
      const action = await ui.choose();
      if (action !== 'accept' && action !== 'keep') return finish(null);
      error = '';
      let r;
      try {
        r = await fetchFn(`${opts.api}/encryption/peer_key/decide`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // the fingerprint the user was shown, never one read again
          body: JSON.stringify({ address, fingerprint: info.held.fingerprint, accept: action === 'accept' }),
        });
      } catch (_) {
        error = T('kc_err_network', 'GigaMail non risponde: non è stato deciso nulla.');
        continue;
      }
      if (r.status === 409) {
        let detail = '';
        try { detail = ((await r.json()) || {}).detail || ''; } catch (_) {}
        error = detail ? String(detail) : T('kc_err_changed', 'Le chiavi sono cambiate nel frattempo: guarda di nuovo.');
        info = await load();
        continue;
      }
      if (!r.ok) {
        error = r.status === 403
          ? T('kc_err_forbidden', 'Decisione non registrata: va presa con un clic in questa finestra.')
          : T('kc_err_failed', 'Decisione non registrata: riprova.');
        continue;
      }
      let result = null;
      try { result = await r.json(); } catch (_) {}
      return finish(result || { address, outcome: action === 'accept' ? 'accepted' : 'kept' });
    }
  }

  // ── DOM ui: the console dialog's look (dialog.js classes), three buttons
  // and a small table. Every value goes in as text.
  const CSS = `
  .gm-kc { width: min(560px, calc(100vw - 48px)); }
  .gm-kc-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; word-break: break-word; }
  .gm-kc-table { border-collapse: collapse; font-size: 13px; margin-bottom: 12px; width: 100%; }
  .gm-kc-table td { padding: 3px 12px 3px 0; vertical-align: top; }
  .gm-kc-fpr { font-family: monospace; font-size: 12.5px; white-space: nowrap; }
  .gm-kc-when { opacity: 0.7; }
  .gm-kc-error { margin-top: 10px; font-size: 13px; color: #b3261e; white-space: pre-wrap; }
  .gm-kc-warning { margin-top: 6px; font-size: 12px; opacity: 0.75; text-align: right; }
  .gm-dialog-btn:disabled { opacity: 0.5; cursor: default; }`;

  function domUi() {
    const doc = document;
    let overlay = null;
    let box = null;
    let pick = null;
    let busy = false;

    function ensureStyle() {
      if (window.GMDialog && window.GMDialog.ensureStyle) window.GMDialog.ensureStyle();
      if (doc.getElementById('gm-kc-style')) return;
      const st = doc.createElement('style');
      st.id = 'gm-kc-style';
      st.textContent = CSS;
      (doc.head || doc.documentElement).appendChild(st);
    }

    function onKey(e) {
      if (e.key !== 'Escape' || busy || !pick) return;
      e.preventDefault();
      e.stopPropagation();
      choose('later');
    }

    function choose(action) {
      const p = pick;
      pick = null;
      if (p) p(action);
    }

    function ensure() {
      if (overlay) return;
      ensureStyle();
      overlay = doc.createElement('div');
      overlay.className = 'gm-dialog-overlay';
      box = doc.createElement('div');
      box.className = 'gm-dialog gm-kc';
      box.setAttribute('role', 'dialog');
      box.setAttribute('aria-modal', 'true');
      overlay.appendChild(box);
      doc.addEventListener('keydown', onKey, true);
      doc.body.appendChild(overlay);
    }

    function el(tag, cls, text) {
      const e = doc.createElement(tag);
      if (cls) e.className = cls;
      if (text != null) e.textContent = String(text);
      return e;
    }

    function actions(buttons) {
      const row = el('div', 'gm-dialog-actions');
      const all = [];
      for (const b of buttons) {
        const btn = el('button', 'gm-dialog-btn' + (b.primary ? ' primary' : ''), b.label);
        btn.type = 'button';
        btn.addEventListener('click', () => {
          if (busy) return;
          // one decision per click: everything is disabled until the answer
          if (b.action === 'accept' || b.action === 'keep') {
            busy = true;
            all.forEach((x) => { x.disabled = true; });
          }
          choose(b.action);
        });
        all.push(btn);
        row.appendChild(btn);
      }
      return { row, all };
    }

    return {
      render(m, error) {
        ensure();
        busy = false;
        box.textContent = '';
        box.appendChild(el('div', 'gm-kc-title', m.title));
        const table = el('table', 'gm-kc-table');
        for (const r of m.rows) {
          const tr = el('tr');
          tr.appendChild(el('td', '', r.label));
          tr.appendChild(el('td', 'gm-kc-fpr', r.fingerprint));
          tr.appendChild(el('td', 'gm-kc-when', r.when));
          table.appendChild(tr);
        }
        box.appendChild(table);
        box.appendChild(el('div', 'gm-dialog-text', m.hint));
        if (error) {
          const err = el('div', 'gm-kc-error', error);
          err.setAttribute('role', 'alert');
          box.appendChild(err);
        }
        const { row, all } = actions(m.buttons);
        box.appendChild(row);
        if (m.keepWarning) box.appendChild(el('div', 'gm-kc-warning', m.keepWarning));
        // The button the model names, never the accepting one.
        const i = m.buttons.findIndex((b) => b.action === m.focus && b.action !== 'accept');
        const target = i >= 0 ? all[i] : all[all.length - 1];
        if (target) target.focus();
      },
      choose() {
        return new Promise((resolve) => { pick = resolve; });
      },
      notice(text) {
        ensure();
        busy = false;
        box.textContent = '';
        box.appendChild(el('div', 'gm-dialog-text', text));
        const T = (k, it) => ((window.i18n && window.i18n.t) ? window.i18n.t(k, it) : it);
        const { row, all } = actions([{ action: 'ok', label: T('kc_ok', 'OK'), primary: true }]);
        box.appendChild(row);
        if (all[0]) all[0].focus();
        return new Promise((resolve) => { pick = resolve; });
      },
      close() {
        pick = null;
        doc.removeEventListener('keydown', onKey, true);
        if (overlay) overlay.remove();
        overlay = null;
        box = null;
      },
    };
  }

  const GMKeyChange = { model, open, pendingLine, formatFingerprint };
  if (typeof module !== 'undefined' && module.exports) module.exports = GMKeyChange;
  if (typeof window !== 'undefined') window.GMKeyChange = GMKeyChange;
})();
