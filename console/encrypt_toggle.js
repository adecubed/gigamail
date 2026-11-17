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
    if (!st.missing || !st.missing.length) return T('enc_no_recipient', 'Aggiungi prima un destinatario');
    return T('enc_missing_keys', 'Nessuna chiave per') + ' ' + st.missing.join(', ') +
      '. ' + T('enc_missing_hint', 'Arriva da sola con la prima mail che ti mandano da GigaMail.');
  }

  function statusUrl(api, accountId, to, cc) {
    const q = new URLSearchParams({ to: to || '', cc: cc || '' });
    if (accountId) q.set('account_id', String(accountId));
    return `${api}/encryption/status?${q.toString()}`;
  }

  /** Wires the button. opts: {button, status, api, getAccountId,
   * getRecipients: () => ({to, cc}), T, fetchFn}. Returns {isOn, set, recheck}. */
  function attach(opts) {
    const T = opts.T || ((k, it) => it);
    const fetchFn = opts.fetchFn || ((u) => fetch(u));
    let on = false;

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
        if (opts.status) opts.status.textContent = '';
        render();
        return on;
      }
      const st = await check();
      on = !!(st && st.can_encrypt);
      if (opts.status) opts.status.textContent = statusText(st, T);
      render();
      return on;
    }

    // Recipients changed: say what the send will meet, never switch off.
    async function recheck() {
      if (!on) return;
      const st = await check();
      if (opts.status) opts.status.textContent = statusText(st, T);
    }

    opts.button.addEventListener('click', () => { set(!on); });
    render();
    return { isOn: () => on, set, recheck };
  }

  const EncryptToggle = { attach, statusText, statusUrl };
  if (typeof module !== 'undefined' && module.exports) module.exports = EncryptToggle;
  if (typeof window !== 'undefined') window.GMEncryptToggle = EncryptToggle;
})();
