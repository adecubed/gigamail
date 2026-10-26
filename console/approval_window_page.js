// approval_window_page.js — the popup a toast button opens for a request
// waiting for approval (Read, Approve, Edit, Reject), in the console's own
// style instead of a terminal. The decision goes to the backend as a
// console click: Approve needs no Hello unless the user asked for it.
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
const $ = (id) => document.getElementById(id);
let current = null;      // the request record
let action = 'show';

function T(key, fallback) {
  const t = window.i18n && window.i18n.t ? window.i18n.t(key) : '';
  return (t && t !== key) ? t : fallback;
}
function addressOf(v) {
  if (!v) return '';
  if (Array.isArray(v)) return v.map(addressOf).filter(Boolean).join(', ');
  if (typeof v === 'object') return String(v.address || v.email || (v.emailAddress && v.emailAddress.address) || '');
  return String(v);
}
async function api(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let data = null;
  try { data = await r.json(); } catch (_) { data = null; }
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${r.status}`);
  return data;
}

function stateOf(rec) {
  const now = Date.now() / 1000;
  const expired = rec.expired || (rec.expires_at && rec.expires_at <= now);
  if (rec.status === 'executed') {
    if (rec.execution_outcome === 'ok') return { cls: 'ok', text: T('st_sent', 'inviata') };
    if (rec.execution_outcome === 'dryrun') return { cls: 'warn', text: T('st_dryrun', 'prova, non inviata') };
    if (rec.execution_outcome) return { cls: 'err', text: T('st_send_failed', 'invio fallito') };
    return { cls: 'warn', text: T('st_executing', 'in esecuzione') };
  }
  if (rec.status === 'approved') return { cls: 'warn', text: T('st_approved_watcher', 'approvata, la invia il watcher') };
  if (rec.status === 'rejected') return { cls: 'err', text: T('st_rejected', 'rifiutata') };
  if (rec.status === 'pending' && expired) return { cls: 'err', text: T('st_expired', 'scaduta senza decisione') };
  if (rec.status === 'pending') {
    const left = Math.max(0, Math.round((rec.expires_at || now) - now));
    const m = Math.floor(left / 60);
    return { cls: 'warn', text: `${T('aw_waiting', 'in attesa')} · ${T('pending_expires_in', 'scade tra')} ${m}m${String(left % 60).padStart(2, '0')}s` };
  }
  return { cls: '', text: rec.status || '' };
}

function render(rec) {
  current = rec;
  const p = rec.preview || {};
  const a = rec.args || {};
  const replying = p.replying_to && typeof p.replying_to === 'object' ? p.replying_to : null;
  const st = stateOf(rec);
  $('state').textContent = st.text;
  $('state').className = `field-value state ${st.cls}`;
  $('tool').textContent = `${rec.tool || ''} · ${rec.request_id || ''}`;
  const from = addressOf(p.from);
  const to = addressOf(p.to) || (replying ? addressOf(replying.from) : '');
  const subject = String(p.subject || (replying && replying.subject) || '');
  const att = (p.attachments || a.attachments || []).map((x) => (typeof x === 'string' ? x.split(/[\\/]/).pop() : x && x.name)).filter(Boolean);
  const row = (id, value, el) => { $(id).style.display = value ? '' : 'none'; if (value) $(el).textContent = value; };
  row('rowFrom', from, 'from');
  row('rowTo', to, 'to');
  row('rowSubject', subject, 'subject');
  row('rowAtt', att.join(', '), 'attachments');
  const body = String(p.body || a.body || '');
  $('body').textContent = body || summaryOf(p);
  const open = rec.status === 'pending' && st.cls !== 'err';
  $('btnApprove').disabled = !open;
  $('btnReject').disabled = !open && rec.status !== 'approved';
  $('btnEdit').disabled = !open && rec.status !== 'approved';
}

function summaryOf(p) {
  // a move, a delete, an event: no body, the fields say it
  return Object.entries(p || {})
    .filter(([k, v]) => v && !['body', 'to', 'from', 'subject', 'replying_to', 'attachments', 'recipients'].includes(k))
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join('\n');
}

function say(text, cls = '') {
  $('status').textContent = text;
  $('status').className = `status ${cls}`;
}

// The window exists for one decision: once it is taken and shown, it goes
// away by itself (a second and a half to read the outcome).
const CLOSE_DELAY = (typeof window !== 'undefined' && window.GM_CLOSE_DELAY != null) ? window.GM_CLOSE_DELAY : 1500;
function closeSoon() {
  setTimeout(() => { try { window.approvalWindowAPI.close(); } catch (_) { /* no bridge */ } }, CLOSE_DELAY);
}

async function reload() {
  if (!current) return;
  try { render(await api(`/approvals/${encodeURIComponent(current.request_id)}`)); } catch (_) { /* keep what we have */ }
}

async function doApprove() {
  if (!current) return;
  $('btnApprove').disabled = true;
  say(T('aw_approving', 'Approvo…'));
  const hint = setTimeout(() => say(T('aw_slow', 'Ancora un attimo: se Windows Hello è richiesto, il prompt può essere dietro le finestre (Alt+Tab).')), 4000);
  let decided = false;
  try {
    const r = await api(`/approvals/${encodeURIComponent(current.request_id)}/approve`, { method: 'POST' });
    clearTimeout(hint);
    decided = true;
    if (r.status === 'executed') {
      say(r.outcome === 'failed' ? `${T('st_send_failed', 'invio fallito')}: ${r.error || ''}` : T('aw_done', 'Fatto: eseguita.'), r.outcome === 'failed' ? 'err' : 'ok');
      if (r.outcome === 'failed') decided = false;   // leave the reason on screen
    } else {
      say(`${T('aw_approved_watcher', 'Approvata: la invio ora.')}${r.error ? ' ' + r.error : ''}`, 'ok');
    }
  } catch (e) {
    clearTimeout(hint);
    say(`${T('agent_not_approved', 'Non approvata')}: ${e.message || e}`, 'err');
  }
  await reload();
  if (decided) closeSoon();
}

async function doReject() {
  if (!current) return;
  $('btnReject').disabled = true;
  try {
    await api(`/approvals/${encodeURIComponent(current.request_id)}/reject`, { method: 'POST' });
    say(T('aw_rejected', 'Rifiutata: non verrà eseguita.'), 'ok');
    await reload();
    closeSoon();
    return;
  } catch (e) {
    say(e.message || String(e), 'err');
  }
  await reload();
}

async function doEdit() {
  const box = $('editBox');
  if (!box.classList.contains('visible')) {
    box.classList.add('visible');
    $('note').focus();
    return;
  }
  const note = $('note').value.trim();
  if (!note) { $('note').focus(); return; }
  $('btnEdit').disabled = true;
  try {
    const r = await api(`/approvals/${encodeURIComponent(current.request_id)}/edit`, { method: 'POST', body: JSON.stringify({ note }) });
    say(r.requeued ? T('aw_requeued', 'Chiusa e rimessa in coda con la tua nota: il watcher la riscrive e te la ripropone.')
      : T('aw_note_for_agent', "Chiusa. Riporta la nota all'agente dalla barra agente."), 'ok');
    box.classList.remove('visible');
    await reload();
    closeSoon();
    return;
  } catch (e) {
    say(e.message || String(e), 'err');
    $('btnEdit').disabled = false;
  }
  await reload();
}

async function load(data) {
  action = (data && data.action) || 'show';
  try {
    render(await api(`/approvals/${encodeURIComponent(data.request_id)}`));
  } catch (e) {
    $('state').textContent = T('aw_missing', 'Richiesta non trovata: questa notifica è vecchia.');
    $('state').className = 'field-value state err';
    $('body').textContent = '';
    ['btnApprove', 'btnReject', 'btnEdit'].forEach((id) => { $(id).disabled = true; });
    return;
  }
  if (action === 'reject' && current.status === 'pending') await doReject();
  else if (action === 'edit') { $('editBox').classList.add('visible'); $('note').focus(); }
  else if (action === 'approve') $('btnApprove').focus();
}

$('btnApprove').addEventListener('click', doApprove);
$('btnReject').addEventListener('click', doReject);
$('btnEdit').addEventListener('click', doEdit);
$('note').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) doEdit(); });
$('btnClose').addEventListener('click', () => window.approvalWindowAPI.close());
$('btnMin').addEventListener('click', () => window.approvalWindowAPI.minimize());
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') window.approvalWindowAPI.close(); });
if (window.approvalWindowAPI && window.approvalWindowAPI.onLoad) window.approvalWindowAPI.onLoad(load);
if (typeof module !== 'undefined' && module.exports) module.exports = { stateOf, addressOf, summaryOf };
