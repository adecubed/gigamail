// The top bar's sections on narrow screens. Below 1240 px the links in
// .topnav do not fit and are hidden (home.css), so a Menu button next to
// Download opens them as a list under the bar. The button is added here,
// so a page without scripts keeps the bar as it was.

const LABELS = { en: 'Menu', it: 'Menu', zh: '菜单' };

export function labelFor(lang) {
  return LABELS[String(lang || '').slice(0, 2).toLowerCase()] || LABELS.en;
}

export function addMenu(doc) {
  const bar = doc.querySelector('.topbar');
  const nav = bar && bar.querySelector('.topnav');
  if (!nav || bar.querySelector('.menu-btn')) return null;
  if (!nav.id) nav.id = 'topnav';
  const btn = doc.createElement('button');
  btn.type = 'button';
  btn.className = 'menu-btn';
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', nav.id);
  btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';
  const text = doc.createElement('span');
  text.textContent = labelFor(doc.documentElement.lang);
  btn.appendChild(text);
  const set = (open) => {
    bar.classList.toggle('menu-open', open);
    btn.setAttribute('aria-expanded', String(open));
  };
  btn.addEventListener('click', () => set(!bar.classList.contains('menu-open')));
  nav.addEventListener('click', (e) => { if (e.target.closest('a')) set(false); });
  doc.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && bar.classList.contains('menu-open')) { set(false); btn.focus(); }
  });
  doc.addEventListener('click', (e) => { if (!bar.contains(e.target)) set(false); });
  // Right of GitHub, just before Download; on narrow screens home.css moves
  // GitHub next to the logo.
  const download = bar.querySelector('.btn-primary');
  if (download) download.before(btn); else nav.before(btn);
  return btn;
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => addMenu(document));
  else addMenu(document);
}
