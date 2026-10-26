// approvals_view.js — the "waiting for you" and "recently decided" cards of
// the Automations view: the requests the watcher's rules and the agent
// raise, with Approve (Windows Hello, from the backend) and Reject.
//
// Pure rendering, shared by the window (window.ApprovalsView) and the node
// tests (module.exports). The translation function `t(key, fallback)` is
// passed in: window.i18n.t in the console, an identity in the tests.
(function () {
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // The preview stores recipients as a string, an {address} object or a
  // list of either: one address string out of any of them.
  function addressOf(v) {
    if (!v) return '';
    if (Array.isArray(v)) return v.map(addressOf).filter(Boolean).join(', ');
    if (typeof v === 'object') return String(v.address || v.email || '');
    return String(v);
  }

  function summarize(rec, now = Date.now() / 1000) {
    const p = rec.preview || {};
    const a = rec.args || {};
    const replying = p.replying_to && typeof p.replying_to === 'object' ? p.replying_to : null;
    const attachments = (p.attachments || a.attachments || [])
      .map((x) => (typeof x === 'string' ? x.split(/[\\/]/).pop() : x && x.name))
      .filter(Boolean);
    return {
      id: rec.request_id,
      tool: rec.tool || '',
      status: rec.status || 'pending',
      completedBy: rec.completed_by === 'watcher' ? 'watcher' : 'agent',
      to: addressOf(p.to) || (replying ? addressOf(replying.from) : ''),
      subject: String(p.subject || (replying && replying.subject) || ''),
      body: String(p.body || a.body || ''),
      expiresIn: Math.max(0, Math.round((rec.expires_at || 0) - now)),
      expired: !!rec.expired || (!!rec.expires_at && rec.expires_at <= now),
      ruleMode: String(p.rule_mode || ''),
      toSource: String(p.to_source || ''),
      attachments,
      decidedBy: String(rec.decided_by || ''),
      decidedAt: rec.decided_at || null,
      outcome: String(rec.execution_outcome || ''),
      from: addressOf(p.from),
      cc: addressOf(p.cc),
      bcc: addressOf(p.bcc),
      createdAt: rec.created_at || null,
      // the notifications sent for it, and the ones that failed
      notified: Array.isArray(rec.notified) ? rec.notified : [],
      error: rec.provider_result && typeof rec.provider_result === 'object'
        ? String(rec.provider_result.error || '') : '',
      accepted: rec.provider_result && typeof rec.provider_result === 'object'
        ? rec.provider_result.accepted : undefined,
    };
  }

  function fmtEta(sec, t) {
    if (sec <= 0) return t('pending_expired', 'scaduta');
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    const when = m > 0 ? `${m}m${String(s).padStart(2, '0')}s` : `${s}s`;
    return `${t('pending_expires_in', 'scade tra')} ${when}`;
  }

  // "console:simon" → console, "telegram:123+pin" → Telegram, "cli:simon" → terminal
  function fmtBy(by, t) {
    const chan = String(by || '').split(':')[0];
    if (chan === 'console') return t('by_console', 'console');
    if (chan === 'telegram') return t('by_telegram', 'Telegram');
    if (chan === 'cli') return t('by_cli', 'terminale');
    return by ? String(by) : '';   // plain text: callers escape
  }

  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  // One short label for what happened to a decided request. "executed"
  // alone means consumed, not delivered: the outcome says whether it went.
  function outcomeOf(s, t) {
    if (s.status === 'executed') {
      if (s.outcome === 'ok') return { cls: 'ok', text: t('st_sent', 'inviata') };
      if (s.outcome === 'dryrun') return { cls: 'warn', text: t('st_dryrun', 'prova, non inviata') };
      if (s.outcome) return { cls: 'err', text: t('st_send_failed', 'invio fallito') };
      return { cls: 'warn', text: t('st_executing', 'in esecuzione') };
    }
    if (s.status === 'approved') {
      return { cls: 'warn', text: s.completedBy === 'watcher'
        ? t('st_approved_watcher', 'approvata, la invia il watcher')
        : t('st_approved_agent', 'approvata, in esecuzione') };
    }
    if (s.status === 'rejected') return { cls: 'err', text: t('st_rejected', 'rifiutata') };
    if (s.status === 'pending' && s.expired) return { cls: 'err', text: t('st_expired', 'scaduta senza decisione') };
    return { cls: '', text: esc(s.status) };
  }

  function head(s, t) {
    const origin = s.completedBy === 'watcher'
      ? `<span class="ai-tag">${esc(t('pending_from_watcher', 'bozza del watcher'))}${s.ruleMode ? ' · ' + esc(s.ruleMode.toUpperCase()) : ''}</span>`
      : `<span class="ai-tag">${esc(t('pending_from_agent', "richiesta dell'agente"))}</span>`;
    const title = s.subject || s.tool;
    const to = s.to ? `<div class="ai-card-sub">${esc(t('pending_to', 'a'))} ${esc(s.to)}`
      + (s.toSource ? ` <span class="hint">(${esc(s.toSource)})</span>` : '') + '</div>' : '';
    return `${origin} <span class="hint">${esc(s.tool)} · ${esc(s.id)}</span>
          <div class="ai-card-title" style="margin-top:4px">${esc(title)}</div>${to}`;
  }

  function bodyBlock(s, t) {
    if (!s.body && !s.attachments.length) return '';
    const att = s.attachments.length
      ? `<div class="ai-card-sub">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('paperclip', 11) : '')} ${esc(s.attachments.join(', '))}</div>` : '';
    const body = s.body
      ? `<details class="pending-body"><summary class="hint">${esc(t('pending_body', 'Testo'))}</summary>`
        + `<pre class="hint" style="white-space:pre-wrap;margin:6px 0 0">${esc(s.body)}</pre></details>` : '';
    return att + body;
  }

  function pendingCard(rec, t, now) {
    const s = summarize(rec, now);
    return `
      <div class="ai-card pending-card" data-request="${esc(s.id)}">
        ${head(s, t)}
        ${bodyBlock(s, t)}
        <div class="ai-card-row" style="margin-top:8px">
          <span class="ai-card-status ${s.expiresIn < 120 ? 'warn' : ''}">${fmtEta(s.expiresIn, t)}</span>
          ${notifyFailed(s) ? `<span class="ai-card-status warn">${esc(t('notify_failed_tag', 'notifica non arrivata'))}</span>` : ''}
          <span style="flex:1"></span>
          <button class="chip-btn" data-act="approve" data-id="${esc(s.id)}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('check', 12) : '')} ${esc(t('pending_approve', 'Approva'))}</button>
          <button class="chip-btn danger" data-act="reject" data-id="${esc(s.id)}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('x', 12) : '')} ${esc(t('pending_reject', 'Rifiuta'))}</button>
        </div>
      </div>`;
  }

  function fmtDateTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const p2 = (n) => String(n).padStart(2, '0');
    return `${p2(d.getDate())}/${p2(d.getMonth() + 1)} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
  }

  // What was sent, or what was refused: the request as GigaMail stored it
  // (the same payload the send executes), opened by clicking the card.
  // "telegram ✓ · desktop ✓ · telegram: 401 Unauthorized": what was sent
  // to reach the user, and what did not leave, so a request that expired
  // unseen says why.
  function notifiedText(s, t) {
    return (s.notified || []).map((n) => (n.ok
      ? `${n.channel} ✓`
      : `${n.channel}: ${n.error || t('notify_failed', 'non partita')}`)).join(' · ');
  }

  function notifyFailed(s) {
    return (s.notified || []).some((n) => !n.ok);
  }

  function detailHtml(s, t) {
    const row = (label, value) => (value
      ? `<div class="recent-row"><span class="recent-k">${esc(label)}</span><span class="recent-v">${esc(value)}</span></div>` : '');
    const accepted = Array.isArray(s.accepted) ? s.accepted.join(', ') : '';
    return `<div class="recent-detail">
        ${row(t('detail_from', 'Da'), s.from)}
        ${row(t('detail_to', 'A'), s.to)}
        ${row('CC', s.cc)}
        ${row('CCN', s.bcc)}
        ${row(t('detail_subject', 'Oggetto'), s.subject)}
        ${s.attachments.length ? row(t('detail_attachments', 'Allegati'), s.attachments.join(', ')) : ''}
        ${s.body ? `<pre class="recent-body">${esc(s.body)}</pre>` : ''}
        ${row(t('detail_accepted', 'Accettata per'), accepted)}
        ${row(t('detail_error', 'Errore'), s.error)}
        ${row(t('detail_notified', 'Notifiche'), notifiedText(s, t))}
        ${row(t('detail_requested', 'Richiesta'), fmtDateTime(s.createdAt))}
        ${row(t('detail_decided', 'Decisa'), [fmtDateTime(s.decidedAt), s.decidedBy ? fmtBy(s.decidedBy, t) : ''].filter(Boolean).join(' · '))}
        <div class="recent-row"><span class="recent-k">id</span><span class="recent-v hint">${esc(s.tool)} · ${esc(s.id)}</span></div>
      </div>`;
  }

  function recentCard(rec, t, now) {
    const s = summarize(rec, now);
    const o = outcomeOf(s, t);
    const by = s.decidedBy ? ` · ${esc(fmtBy(s.decidedBy, t))}` : '';
    const when = fmtTime(s.decidedAt || rec.expires_at);
    // <details>: a click opens what was sent (or refused), no script needed
    return `
      <details class="ai-card recent-card" data-request="${esc(s.id)}">
        <summary>
          ${head(s, t)}
          <div class="ai-card-row" style="margin-top:6px">
            <span class="ai-card-status ${o.cls}">${o.text}</span>
            ${notifyFailed(s) ? `<span class="ai-card-status warn">${esc(t('notify_failed_tag', 'notifica non arrivata'))}</span>` : ''}
            <span class="hint">${esc(when)}${by}</span>
            <span style="flex:1"></span>
            <span class="hint recent-more">${esc(t('detail_open', 'dettagli'))}</span>
          </div>
        </summary>
        ${detailHtml(s, t)}
      </details>`;
  }

  // Sidebar badge: how many requests wait, capped so the dot stays a dot.
  function badgeText(n) {
    if (!n || n < 1) return '';
    return n > 9 ? '9+' : String(n);
  }

  // What the "waiting for you" icon shows: the requests still to decide,
  // and the outcomes decided since the user last opened the page, by
  // colour (ok = sent, warn = approved and executing, err = failed,
  // rejected or expired). Opening the page sets seenAt to now and the
  // decided counts go away; the to-do count stays until it is zero.
  function badgeCounts(pending, recent, seenAt, now = Date.now() / 1000) {
    const out = { todo: (pending || []).length, ok: 0, warn: 0, err: 0 };
    for (const rec of recent || []) {
      const s = summarize(rec, now);
      const at = s.decidedAt || rec.expires_at || 0;
      if (at <= (seenAt || 0)) continue;
      const cls = outcomeOf(s, (_k, f) => f).cls;
      if (cls === 'ok' || cls === 'warn' || cls === 'err') out[cls] += 1;
    }
    return out;
  }

  // The rules that paused themselves (the burst guard): a pause nobody
  // chose must be seen, not read in a card's small print days later.
  function autoPaused(rules) {
    return (rules || []).filter((r) => r && r.state === 'paused'
      && /^(raffica|burst)\b/i.test(String(r.pause_reason || '')));
  }

  const ApprovalsView = { summarize, pendingCard, recentCard, detailHtml, outcomeOf, fmtEta, badgeText, badgeCounts, addressOf, notifiedText, notifyFailed, autoPaused };
  if (typeof window !== 'undefined') window.ApprovalsView = ApprovalsView;
  if (typeof module !== 'undefined' && module.exports) module.exports = ApprovalsView;
})();
