// Download total under the Download button of the top bar, drawn as a
// station departure board: the digits flip until they land on the number.
// The total (GitHub release downloads plus all-time PyPI downloads) comes
// from the same backend as the visit counter (GET /downloads). The board
// shows digits only; screen readers hear "13632 downloads". Nothing is
// shown until the number is known.
import {analyticsConfig} from './business/analytics-config.js';

const LABEL = {en: 'downloads', it: 'download', zh: '次下载'};

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

// Flip each tile through random digits, then settle them left to right.
function flip(tiles, digits, win) {
  const reduce = win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) { tiles.forEach((t, i) => { t.textContent = digits[i]; }); return; }
  let tick = 0;
  const timer = win.setInterval(() => {
    tick += 1;
    tiles.forEach((t, i) => {
      if (tick >= 8 + i * 3) { t.textContent = digits[i]; t.classList.remove('flipping'); return; }
      t.textContent = String(Math.floor(Math.random() * 10));
      t.classList.add('flipping');
    });
    if (tick >= 8 + tiles.length * 3) win.clearInterval(timer);
  }, 70);
}

export async function showDownloadBoard(doc = document, win = window, fetchFn = fetch, config = analyticsConfig) {
  const button = doc.querySelector('.topbar .btn-primary');
  if (!button) return '';
  const digits = digitsOf(await fetchTotal(fetchFn, config));
  if (!digits) return '';
  const wrap = doc.createElement('span');
  wrap.className = 'dl-board-wrap';
  button.replaceWith(wrap);
  wrap.append(button);
  const board = doc.createElement('span');
  board.className = 'dl-board';
  board.setAttribute('aria-label', `${digits} ${labelFor(doc.documentElement.lang)}`);
  const tiles = [...digits].map(() => {
    const t = doc.createElement('span');
    t.className = 'tile';
    t.setAttribute('aria-hidden', 'true');
    t.textContent = '0';
    return t;
  });
  const row = doc.createElement('span');
  row.className = 'tiles';
  row.append(...tiles);
  board.append(row);
  wrap.append(board);
  // the board belongs to the top of the page: it hides once the page scrolls
  const onScroll = () => board.classList.toggle('away', win.scrollY > 40);
  win.addEventListener('scroll', onScroll, {passive: true});
  onScroll();
  flip(tiles, digits, win);
  return digits;
}

if (typeof window !== 'undefined') showDownloadBoard();
