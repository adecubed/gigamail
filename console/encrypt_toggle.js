// encrypt_toggle.js — the "Encrypt" button of the compose and reply windows.
//
// The backend decides (GET /encryption/status, then core/pgp.py on send):
// the button only turns on when every recipient has a key, and once on it
// stays on even if a recipient without a key is added later. The send then
// fails with the reason instead of leaving in clear: a mail the user asked
// to encrypt never goes out unencrypted because a button changed by itself.
(function () {
  /** The status line for an /encryption/status answer. T(key, italian). */
  function statusText(st, T) {
    if (!st || st.reason === 'library') return T('enc_unavailable', 'Cifratura non disponibile su questo computer');
    if (st.can_encrypt) return T('enc_on', 'La mail partirà cifrata: solo i destinatari potranno leggerla');
    if (st.reason === 'account') return T('enc_no_account', 'La cifratura per ora funziona solo con gli account IMAP/SMTP');
    if (st.reason === 'key_changed') {
      return fillText(T('enc_key_changed', 'Non posso cifrare per {address}: ha una chiave nuova da accettare.'),
        { address: pendingAddresses(st).join(', ') });
    }
    if (!st.missing || !st.missing.length) return T('enc_no_recipient', 'Aggiungi prima un destinatario');
    return T('enc_missing_keys', 'Nessuna chiave per') + ' ' + st.missing.join(', ') +
      '. ' + T('enc_missing_hint', 'Arriva da sola con la prima mail che ti mandano da GigaMail.');
  }

  function pendingAddresses(st) {
    return ((st && st.pending) || []).map((p) => p && p.address).filter(Boolean);
  }

  // {name} placeholders filled with a function: a '$' in an address stays text.
  function fillText(s, vars) {
    return String(s).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  }

  // Same format as MailRender.formatFingerprint (the compose windows do not
  // load mail_render.js): upper case, groups of four.
  function formatFingerprint(fpr) {
    const s = String(fpr || '').replace(/\s+/g, '').toUpperCase();
    return s ? s.match(/.{1,4}/g).join(' ') : '';
  }

  /** The lines shown under the status while encryption is on: the user's
   * own fingerprint first, then one per recipient. [] when it cannot encrypt. */
  function fingerprintLines(st, T) {
    T = T || ((k, it) => it);
    if (!st || !st.can_encrypt) return [];
    const lines = [];
    if (st.own_fingerprint) {
      lines.push(`${T('enc_fpr_you', 'La tua chiave')}  ${formatFingerprint(st.own_fingerprint)}`);
    }
    for (const p of st.peers || []) {
      if (p && p.address && p.fingerprint) lines.push(`${p.address}  ${formatFingerprint(p.fingerprint)}`);
    }
    return lines;
  }

  function statusUrl(api, accountId, to, cc) {
    const q = new URLSearchParams({ to: to || '', cc: cc || '' });
    if (accountId) q.set('account_id', String(accountId));
    return `${api}/encryption/status?${q.toString()}`;
  }

  /** Wires the button. opts: {button, status, details, api, getAccountId,
   * getRecipients: () => ({to, cc}), T, fetchFn}. `details` (optional) gets
   * the "Review and decide" links for a pending key and, while encryption
   * is on, the fingerprint lines. Returns {isOn, wantsEncryption, set,
   * recheck}. */
  function attach(opts) {
    const T = opts.T || ((k, it) => it);
    const fetchFn = opts.fetchFn || ((u) => fetch(u));
    let on = false;
    // The user asked for encryption and it was refused only because a
    // recipient's new key waits for a decision: once decided, the recheck
    // turns it on. A refusal for a missing key is left as it is.
    let waitingForKey = false;

    // Everything here comes from the server or a recipient field: text only.
    function renderDetails(st) {
      const box = opts.details;
      if (!box) return;
      box.textContent = '';
      const doc = box.ownerDocument;
      if (st && st.reason === 'key_changed') {
        const addresses = pendingAddresses(st);
        for (const address of addresses) {
          const link = doc.createElement('button');
          link.type = 'button';
          link.className = 'enc-key-change-link';
          link.setAttribute('data-key-change', address);
          link.textContent = T('kc_review', 'Vedi e decidi') + (addresses.length > 1 ? ` · ${address}` : '');
          box.appendChild(link);
        }
      }
      if (on) {
        for (const line of fingerprintLines(st, T)) {
          const div = doc.createElement('div');
          div.className = 'enc-fpr-line';
          div.textContent = line;
          box.appendChild(div);
        }
      }
      box.hidden = !box.firstChild;
    }

    async function check() {
      const { to, cc } = opts.getRecipients();
      try {
        const r = await fetchFn(statusUrl(opts.api, opts.getAccountId && opts.getAccountId(), to, cc));
        if (!r.ok) return null;
        return await r.json();
      } catch (e) {
        return null;
      }
    }

    function render() {
      opts.button.classList.toggle('active', on);
      opts.button.setAttribute('aria-pressed', String(on));
    }

    async function set(want) {
      if (!want) {
        on = false;
        waitingForKey = false;
        if (opts.status) opts.status.textContent = '';
        renderDetails(null);
        render();
        return on;
      }
      const st = await check();
      on = !!(st && st.can_encrypt);
      waitingForKey = !on && !!st && st.reason === 'key_changed';
      if (opts.status) opts.status.textContent = statusText(st, T);
      renderDetails(st);
      render();
      return on;
    }

    // Recipients changed, or a key was decided: say what the send will
    // meet, never switch off.
    async function recheck() {
      if (!on) {
        if (waitingForKey) await set(true);
        return;
      }
      const st = await check();
      if (opts.status) opts.status.textContent = statusText(st, T);
      renderDetails(st);
    }

    // While a key waits, a click gives encryption up: the only way to send
    // that mail in clear is to choose it.
    opts.button.addEventListener('click', () => { set(!(on || waitingForKey)); });
    render();
    // wantsEncryption: what the send asks for. True while waiting for a key
    // too, so the server refuses with the reason instead of sending in clear.
    return { isOn: () => on, wantsEncryption: () => on || waitingForKey, set, recheck };
  }

  const EncryptToggle = { attach, statusText, statusUrl, fingerprintLines };
  if (typeof module !== 'undefined' && module.exports) module.exports = EncryptToggle;
  if (typeof window !== 'undefined') window.GMEncryptToggle = EncryptToggle;
})();
