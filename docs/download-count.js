// Download total under the Download button of the top bar, drawn as a
// station departure board: the digits flip until they land on the number.
// The total (GitHub release downloads plus all-time PyPI downloads) comes
// from the same backend as the visit counter (GET /downloads). The board
// shows digits only; screen readers hear "13632 downloads". Nothing is
// shown until the number is known.
//
// It moves while the page is open: a click on an installer adds one at
// once (that click is a GitHub download), and every minute the board asks
// the backend again and flips to the new total. It never goes backwards,
// so a click counted here before GitHub counts it does not flip back.
import {analyticsConfig} from './business/analytics-config.js';
import {downloadKind} from './business/analytics.js';

const LABEL = {en: 'downloads', it: 'download', zh: '次下载'};
export const REFRESH_MS = 60000;

export function labelFor(lang) {
  return LABEL[(lang || 'en').slice(0, 2).toLowerCase()] || LABEL.en;
}

export function digitsOf(total) {
  return typeof total === 'number' && total > 0 ? String(Math.floor(total)) : '';
}

export function downloadsUrl(config = analyticsConfig) {
  const ev = config.eventsEndpoint || '';
  return ev ? ev.replace(/\/event$/, '/downloads') : '';
}

export async function fetchTotal(fetchFn = fetch, config = analyticsConfig) {
  const url = downloadsUrl(config);
  if (!url) return null;
  try {
    const r = await fetchFn(url, {credentials: 'omit'});
    return r.ok ? (await r.json()).total : null;
  } catch { return null; }
}

// A click that downloads an installer (not one that opens the release page).
export function isInstallerClick(href) {
  const kind = downloadKind(href);
  return !!kind && kind !== 'release-page';
}

export function createBoard(doc, win, button) {
  const wrap = doc.createElement('span');
  wrap.className = 'dl-board-wrap';
  button.replaceWith(wrap);
  wrap.append(button);
  const board = doc.createElement('span');
  board.className = 'dl-board';
  const row = doc.createElement('span');
  row.className = 'tiles';
  board.append(row);
  wrap.append(board);
  const reduce = !!(win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches);
  let shown = 0, tiles = [], timer = null;

  function set(total) {
    const target = Math.max(shown, Math.floor(total || 0));
    if (!(target > 0) || target === shown) return shown;
    const digits = String(target);
    const from = String(shown).padStart(digits.length, '0');
    shown = target;
    board.setAttribute('aria-label', `${digits} ${labelFor(doc.documentElement.lang)}`);
    if (tiles.length !== digits.length) {
      tiles = [...digits].map((_, i) => {
        const t = doc.createElement('span');
        t.className = 'tile';
        t.setAttribute('aria-hidden', 'true');
        t.textContent = from[i];
        return t;
      });
      row.replaceChildren(...tiles);
    }
    // only the digits that change flip; the others stay still
    const moving = tiles.map((t, i) => (t.textContent !== digits[i] ? i : -1)).filter(i => i >= 0);
    if (timer) { win.clearInterval(timer); timer = null; }
    if (reduce) { tiles.forEach((t, i) => { t.textContent = digits[i]; }); return shown; }
    let tick = 0;
    timer = win.setInterval(() => {
      tick += 1;
      moving.forEach((i, k) => {
        const t = tiles[i];
        if (tick >= 8 + k * 3) { t.textContent = digits[i]; t.classList.remove('flipping'); return; }
        t.textContent = String(Math.floor(Math.random() * 10));
        t.classList.add('flipping');
      });
      if (tick >= 8 + moving.length * 3) { win.clearInterval(timer); timer = null; }
    }, 70);
    return shown;
  }
  return {board, set, value: () => shown};
}

export async function showDownloadBoard(doc = document, win = window, fetchFn = fetch, config = analyticsConfig) {
  const button = doc.querySelector('.topbar .btn-primary');
  if (!button) return null;
  let ctl = null;
  // the board belongs to the top of the page: it hides once the page scrolls
  const onScroll = () => { if (ctl) ctl.board.classList.toggle('away', win.scrollY > 40); };
  const update = async () => {
    const total = await fetchTotal(fetchFn, config);
    if (!digitsOf(total)) return;
    if (!ctl) { ctl = createBoard(doc, win, button); onScroll(); }
    ctl.set(total);
  };
  await update();
  doc.addEventListener('click', (e) => {
    const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (ctl && a && isInstallerClick(a.href)) ctl.set(ctl.value() + 1);
  });
  win.addEventListener('scroll', onScroll, {passive: true});
  win.setInterval(() => { if (doc.visibilityState !== 'hidden') update(); }, REFRESH_MS);
  return ctl;
}

if (typeof window !== 'undefined') showDownloadBoard();
