// reply_alert_window_page.js — the "Reply" button of a client-reply alert:
// what to answer, in the console's style. The watcher drafts it on its next
// tick and sends it for approval; nothing leaves from here.
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
const $ = (id) => document.getElementById(id);
let key = '';

function T(k, fallback) {
  const t = window.i18n && window.i18n.t ? window.i18n.t(k) : '';
  return (t && t !== k) ? t : fallback;
}
async function api(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let data = null;
  try { data = await r.json(); } catch (_) { data = null; }
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${r.status}`);
  return data;
}
function say(text, cls = '') { $('status').textContent = text; $('status').className = `status ${cls}`; }

async function load(data) {
  key = String((data && data.key) || '');
  try {
    const ctx = await api(`/alerts/${encodeURIComponent(key)}`);
    $('who').textContent = [ctx.nome, ctx.mittente].filter(Boolean).join(' · ');
    $('subject').textContent = ctx.subject || '';
    $('excerpt').textContent = ctx.testo || ctx.anteprima || ctx.preview || '';
    $('instruction').focus();
  } catch (e) {
    say(T('ra_missing', "Questo avviso non si trova più: non so a quale mail rispondere."), 'err');
    $('btnQueue').disabled = true;
    $('instruction').disabled = true;
  }
}

async function queue() {
  const instruction = $('instruction').value.trim();
  if (!instruction) { $('instruction').focus(); return; }
  $('btnQueue').disabled = true;
  try {
    await api(`/alerts/${encodeURIComponent(key)}/reply`, { method: 'POST', body: JSON.stringify({ instruction }) });
    say(T('ra_queued', 'Ok: entro un paio di minuti l\'agente scrive la bozza e te la propone da approvare.'), 'ok');
    $('instruction').disabled = true;
    const delay = (window.GM_CLOSE_DELAY != null) ? window.GM_CLOSE_DELAY : 2000;
    setTimeout(() => { try { window.replyAlertWindowAPI.close(); } catch (_) { /* no bridge */ } }, delay);
  } catch (e) {
    say(e.message || String(e), 'err');
    $('btnQueue').disabled = false;
  }
}

$('btnQueue').addEventListener('click', queue);
$('instruction').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) queue(); });
$('btnClose').addEventListener('click', () => window.replyAlertWindowAPI.close());
$('btnMin').addEventListener('click', () => window.replyAlertWindowAPI.minimize());
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') window.replyAlertWindowAPI.close(); });
if (window.replyAlertWindowAPI && window.replyAlertWindowAPI.onLoad) window.replyAlertWindowAPI.onLoad(load);
