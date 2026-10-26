// theme_mode.js — tema chiaro / scuro / come il sistema, per tutte le finestre.
// La scelta sta in localStorage (stessa origine per tutte le finestre della
// console): cambiarla in una aggiorna anche le altre via evento "storage".
// Va caricato nel <head>, prima del primo disegno, per non lampeggiare.
(function () {
  const KEY = 'gm-theme';
  const ORDER = ['system', 'light', 'dark'];
  const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const LABELS = {
    it: { system: 'Tema: come il sistema', light: 'Tema: chiaro', dark: 'Tema: scuro' },
    en: { system: 'Theme: match system', light: 'Theme: light', dark: 'Theme: dark' },
    zh: { system: '主题：跟随系统', light: '主题：浅色', dark: '主题：深色' },
  };
  const ICONS = {
    system: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
    light: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    dark: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>',
  };
  function mode() {
    try { const m = localStorage.getItem(KEY); return ORDER.includes(m) ? m : 'system'; } catch (_) { return 'system'; }
  }
  function label(m) {
    // The active UI language wins over the <html lang> attribute, which
    // i18n.js only updates once the page has loaded.
    const lang = String((window.i18n && window.i18n.lang)
      || document.documentElement.getAttribute('lang') || 'it').slice(0, 2);
    return (LABELS[lang] || LABELS.en)[m];
  }
  function apply() {
    const m = mode();
    const dark = m === 'dark' || (m === 'system' && !!(mq && mq.matches));
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    const btn = document.getElementById('themeSwitch');
    if (btn) {
      btn.innerHTML = ICONS[m];
      btn.setAttribute('data-label', label(m));
      btn.setAttribute('aria-label', label(m));
    }
  }
  apply();
  if (mq && mq.addEventListener) mq.addEventListener('change', apply);
  window.addEventListener('storage', (e) => { if (e.key === KEY) apply(); });
  // i18n.applyLang sets <html lang> on every language switch: relabel the
  // button then, instead of waiting for the next click.
  if (window.MutationObserver) {
    new MutationObserver(apply).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  }
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('themeSwitch');
    if (btn) {
      btn.addEventListener('click', () => {
        const next = ORDER[(ORDER.indexOf(mode()) + 1) % ORDER.length];
        try { localStorage.setItem(KEY, next); } catch (_) { /* senza storage: vale solo questa finestra */ }
        apply();
      });
    }
    apply();
  });
  window.gmTheme = { mode, apply };

  // ── accent: pink (default) or blue ─────────────────────────────────────
  const AKEY = 'gm-accent';
  const ACCENTS = ['pink', 'blue'];
  const ALABELS = {
    it: { pink: 'Colore: rosa', blue: 'Colore: blu' },
    en: { pink: 'Colour: pink', blue: 'Colour: blue' },
    zh: { pink: '颜色：粉色', blue: '颜色：蓝色' },
  };
  function accent() {
    try { const a = localStorage.getItem(AKEY); return ACCENTS.includes(a) ? a : 'pink'; } catch (_) { return 'pink'; }
  }
  function applyAccent() {
    const a = accent();
    if (a === 'pink') document.documentElement.removeAttribute('data-accent');
    else document.documentElement.setAttribute('data-accent', a);
    const btn = document.getElementById('accentSwitch');
    if (btn) {
      const lang = String((window.i18n && window.i18n.lang)
        || document.documentElement.getAttribute('lang') || 'it').slice(0, 2);
      const text = (ALABELS[lang] || ALABELS.en)[a];
      // a dot in the current accent: the click switches to the other one
      btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" fill="var(--gm-pink)" stroke="currentColor" stroke-width="1.2" stroke-opacity="0.35"/></svg>';
      btn.setAttribute('data-label', text);
      btn.setAttribute('aria-label', text);
    }
  }
  applyAccent();
  window.addEventListener('storage', (e) => { if (e.key === AKEY) applyAccent(); });
  if (window.MutationObserver) {
    new MutationObserver(applyAccent).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  }
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('accentSwitch');
    if (btn) {
      btn.addEventListener('click', () => {
        const next = ACCENTS[(ACCENTS.indexOf(accent()) + 1) % ACCENTS.length];
        try { localStorage.setItem(AKEY, next); } catch (_) { /* only this window */ }
        applyAccent();
      });
    }
    applyAccent();
  });
  window.gmAccent = { accent, apply: applyAccent };
})();
