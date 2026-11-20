// Download total under each row of download buttons: GitHub release
// installers plus all-time PyPI downloads, served by the same backend as the
// visit counter (GET /downloads). Shows nothing until the number is known.
import {analyticsConfig} from './business/analytics-config.js';

const LABEL = {
  en: n => `${n} downloads · desktop app and PyPI`,
  it: n => `${n} download · app desktop e PyPI`,
  zh: n => `${n} 次下载 · 桌面应用和 PyPI`,
};

export function countText(total, lang) {
  if (typeof total !== 'number' || !(total > 0)) return '';
  const key = (lang || 'en').slice(0, 2).toLowerCase();
  const locale = key === 'it' ? 'it-IT' : key === 'zh' ? 'zh-CN' : 'en-US';
  return (LABEL[key] || LABEL.en)(total.toLocaleString(locale));
}

export function downloadsUrl(config = analyticsConfig) {
  const ev = config.eventsEndpoint || '';
  return ev ? ev.replace(/\/event$/, '/downloads') : '';
}

export async function showDownloadCount(doc = document, fetchFn = fetch, config = analyticsConfig) {
  const url = downloadsUrl(config);
  const rows = doc.querySelectorAll('.dl3');
  if (!url || !rows.length) return '';
  let total = null;
  try {
    const r = await fetchFn(url, {credentials: 'omit'});
    if (r.ok) total = (await r.json()).total;
  } catch { return ''; }
  const text = countText(total, doc.documentElement.lang);
  if (!text) return '';
  rows.forEach(row => {
    const p = doc.createElement('p');
    p.className = 'dl-count';
    p.textContent = text;
    row.after(p);
  });
  return text;
}

if (typeof window !== 'undefined') showDownloadCount();
