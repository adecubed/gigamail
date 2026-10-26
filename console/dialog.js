// dialog.js — the console's own confirm and alert, in place of the browser's
// (a Windows-style box with "OK / Annulla" that matched nothing else).
// GMDialog.confirm(text) resolves true or false; GMDialog.alert(text)
// resolves when closed. window.alert is replaced too, so a page that still
// calls it gets the same look. Loaded in every window after theme_mode.js.
(function () {
  const CSS = `
  .gm-dialog-overlay { position: fixed; inset: 0; z-index: 100000; display: flex; align-items: center; justify-content: center;
    background: rgba(20, 20, 24, 0.45); backdrop-filter: blur(2px); -webkit-app-region: no-drag; }
  .gm-dialog { width: min(440px, calc(100vw - 48px)); background: var(--gm-card, #fff); color: var(--gm-ink, #1c1c20);
    border: 1.5px solid var(--gm-line, #e6e6ec); border-radius: 16px; box-shadow: 0 24px 60px rgba(0,0,0,0.28);
    font-family: var(--font, -apple-system, 'Segoe UI', sans-serif); padding: 18px 20px 14px; }
  .gm-dialog-text { font-size: 14px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
  .gm-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  .gm-dialog-btn { font: inherit; font-size: 13px; font-weight: 600; padding: 8px 16px; border-radius: 10px; cursor: pointer;
    background: var(--gm-card, #fff); color: var(--gm-ink, #1c1c20); border: 1.5px solid var(--gm-line, #e6e6ec); }
  .gm-dialog-btn:hover { background: var(--gm-fill, #f3f3f6); }
  .gm-dialog-btn.primary { background: var(--gm-pink, #e0409a); color: #fff; border-color: transparent; font-weight: 700; }
  .gm-dialog-btn.primary:hover { background: var(--gm-pink-hi, #ec5aac); }
  .gm-dialog-btn.danger { background: #dc2626; color: #fff; border-color: transparent; font-weight: 700; }
  .gm-dialog-btn.danger:hover { background: #b91c1c; }
  .gm-dialog-btn:focus-visible { outline: 2px solid var(--gm-pink, #e0409a); outline-offset: 2px; }`;

  function ensureStyle() {
    if (document.getElementById('gm-dialog-style')) return;
    const st = document.createElement('style');
    st.id = 'gm-dialog-style';
    st.textContent = CSS;
    (document.head || document.documentElement).appendChild(st);
  }

  function tr(key, fallback) {
    try {
      const t = window.i18n && window.i18n.t ? window.i18n.t(key) : '';
      return (t && t !== key) ? t : fallback;
    } catch (_) { return fallback; }
  }

  // One box, two or one buttons. Enter = the primary one, Escape = cancel.
  function show(text, { okLabel, cancelLabel, danger = false, alertOnly = false } = {}) {
    ensureStyle();
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'gm-dialog-overlay';
      const box = document.createElement('div');
      box.className = 'gm-dialog';
      box.setAttribute('role', alertOnly ? 'alertdialog' : 'dialog');
      box.setAttribute('aria-modal', 'true');
      const p = document.createElement('div');
      p.className = 'gm-dialog-text';
      p.textContent = String(text == null ? '' : text);
      const actions = document.createElement('div');
      actions.className = 'gm-dialog-actions';
      const done = (value) => { overlay.remove(); document.removeEventListener('keydown', onKey, true); resolve(value); };
      let cancel = null;
      if (!alertOnly) {
        cancel = document.createElement('button');
        cancel.className = 'gm-dialog-btn';
        cancel.textContent = cancelLabel || tr('cancel', 'Annulla');
        cancel.addEventListener('click', () => done(false));
        actions.appendChild(cancel);
      }
      const ok = document.createElement('button');
      ok.className = 'gm-dialog-btn ' + (danger ? 'danger' : 'primary');
      ok.textContent = okLabel || tr('ok', 'OK');
      ok.addEventListener('click', () => done(true));
      actions.appendChild(ok);
      box.appendChild(p);
      box.appendChild(actions);
      overlay.appendChild(box);
      overlay.addEventListener('mousedown', (e) => { if (e.target === overlay && !alertOnly) done(false); });
      const onKey = (e) => {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(!alertOnly ? false : true); }
        else if (e.key === 'Enter') {
          e.preventDefault(); e.stopPropagation();
          // the button that has the focus decides: a destructive box
          // starts on Cancel, so Enter there must not delete
          const focused = document.activeElement;
          if (focused === cancel) done(false);
          else done(true);
        }
      };
      document.addEventListener('keydown', onKey, true);
      document.body.appendChild(overlay);
      (danger && cancel ? cancel : ok).focus();
    });
  }

  const GMDialog = {
    confirm: (text, opts) => show(text, opts),
    alert: (text, opts) => show(text, { ...(opts || {}), alertOnly: true }),
  };
  if (typeof window !== 'undefined') {
    window.GMDialog = GMDialog;
    // A page that still calls alert(...) gets the console's box, not the browser's.
    window.alert = (text) => { GMDialog.alert(text); };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = GMDialog;
})();
