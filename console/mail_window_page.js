// mail_window_page.js — the script of mail_window.html, moved out of the page so that the
// Content-Security-Policy can forbid inline scripts (no 'unsafe-inline').
const API = window.GIGAMAIL_API || 'http://127.0.0.1:8002';
const featuresReady = Features.load(API);

// Visible text follows the UI language (i18n.js loads after this script,
// so the helper looks it up at call time).
function T(key, it){ return (window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it; }

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtDate(d) {
  if (!d) return '';
  try {
    const dt = new Date(d);
    const loc = (window.i18n && window.i18n.locale) || 'it-IT';
    return dt.toLocaleDateString(loc,{day:'2-digit',month:'short',year:'numeric'}) +
           ', ' + dt.toLocaleTimeString(loc,{hour:'2-digit',minute:'2-digit'});
  } catch { return d; }
}

async function apiJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// Ricevi dati dalla finestra principale
window.addEventListener('message', async (e) => {
  if (e.data?.type === 'load-mail') {
    await loadMail(e.data.id, e.data.folder, e.data.account_id);
  }
});

// Electron IPC via preload
if (window.mailWindowAPI) {
  window.mailWindowAPI.onLoadMail((data) => {
    loadMail(data.id, data.folder, data.account_id);
  });
}

// `preloadedMsg`: il messaggio gia' in mano (test e2e), salta il fetch.
async function loadMail(id, folder, accountId, preloadedMsg = null) {
  // Salva per dockBack
  window._mailId        = id;
  window._mailFolder    = folder;
  window._mailAccountId = accountId;
  const app = document.getElementById('app');
  app.innerHTML = `<div class="loading">${window.i18n?window.i18n.t("loading"):"Caricamento…"}</div>`;

  try {
    let url = `${API}/mail/${encodeURIComponent(id)}`;
    const params = [];
    if (accountId) params.push(`account_id=${accountId}`);
    if (folder)    params.push(`folder=${encodeURIComponent(folder)}`);
    if (params.length) url += '?' + params.join('&');

    const msg = preloadedMsg || await apiJson(url);
    // Opened here by the human: mark it read on the server, reading does not
    // (marking an already read mail again is harmless; the e2e test's
    // preloaded mail is left alone).
    if (!preloadedMsg && window.MailRender && MailRender.shouldMarkRead(msg, null)) {
      const target = MailRender.markReadTarget(msg, id, folder);
      if (target) {
        fetch(MailRender.markReadUrl(API, target, accountId), { method: 'POST' })
          .catch((e) => console.warn('[mark read]', (e && e.message) || e));
      }
    }

    const sender     = msg.from?.emailAddress?.address || '?';
    const senderName = msg.from?.emailAddress?.name || sender;
    const subject    = msg.subject || '(nessun oggetto)';
    // What the window shows; `subject` above is what reply/forward receive.
    const subjectLabel = msg.subject || T('no_subject', '(nessun oggetto)');
    const rawHtml    = msg.body?.content || '';
    const bodyType   = (msg.body?.contentType||'').toLowerCase();
    // Stesso criterio della finestra principale: il tipo dichiarato vince,
    // e un testo che inizia con un indirizzo tra <> non e' HTML.
    const isHtml     = bodyType === 'html' || (bodyType !== 'text' && /^<\s*(!doctype|html|head|body|div|p|table|span|font)\b/i.test(rawHtml.trimStart()));
    const bodyText   = msg.body_text || msg.bodyPreview || '';
    console.log('[DBG] isHtml:', isHtml, '| body_text len:', bodyText.length, '| rawHtml len:', rawHtml.length);
    console.log('[DBG] body_text inizio:', bodyText.slice(0,200));
    const attachments = msg.attachments || [];

    // Titolo finestra
    document.title = subjectLabel;
    const winTitle = document.getElementById('winTitle');
    // Without this, applyLang() below puts "GigaMail" back over the subject.
    winTitle.removeAttribute('data-i18n');
    winTitle.textContent = subjectLabel;

    // Costruisci UI
    let html = '';

    // Header
    html += `<div class="mail-header">
      <div class="mail-subject">${esc(subjectLabel)}</div>
      <div class="mail-from">${window.i18n?window.i18n.t("from_label"):"Da"}: <strong>${esc(senderName)}</strong> &lt;${esc(sender)}&gt; — ${esc(fmtDate(msg.receivedDateTime||msg.sentDateTime))}</div>
      <div class="mail-actions">
        <button class="btn" id="btnAscolta" data-requires="/mail/{message_id}/tts">◉ <span data-i18n="listen_cap">Ascolta</span></button>
        <button class="btn btn-reply" id="btnReply">↩ <span data-i18n="reply_cap">Rispondi</span></button>
        <button class="btn" id="btnForward">↪ <span data-i18n="forward_cap">Inoltra</span></button>
        <button class="btn" id="btnSummary" data-requires="/mail/{message_id}/summary">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('clipboard', 14) : '')} <span data-i18n="summarize_cap">Riassumi</span></button>
        <button class="btn" id="btnSpam">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('ban', 14) : '')} <span data-i18n="spam_cap">Spam</span></button>
        <button class="btn btn-danger" id="btnDelete">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('trash', 14) : '')} <span data-i18n="delete_cap">Elimina</span></button>
      </div>
    </div>`;

    // AI summary placeholder
    html += `<div class="ai-summary" id="aiSummary" style="display:none">
      <span style="font-size:13px;flex-shrink:0">✦</span>
      <span id="aiSummaryText"></span>
    </div>`;

    // Allegati
    if (attachments.length) {
      const chips = attachments.map((a, idx) => {
        return `<div class="attach-chip" data-att-index="${idx}" title="${esc(T('attach_opts_title', 'Click: apri • Tasto destro: opzioni'))}">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('paperclip', 12) : '')} ${esc(a.name)} (${Math.round((a.size||0)/1024)}KB)</div>`;
      }).join('');
      html += `<div class="attachments">${chips}</div>`;
    }

    // Corpo
    html += `<div class="mail-body" id="mailBodyWrap"></div>`;

    // Footer reply
    html += `<div class="mail-footer">
      <button class="reply-trigger" id="btnReplyTrigger">
        <span class="reply-icon">↩</span>
        <span>${window.i18n?window.i18n.t("reply_to"):"Rispondi a"} ${esc(senderName.split(' ')[0])}…</span>
      </button>
    </div>`;

    app.innerHTML = html;
    await featuresReady;
    Features.apply(app);
    // i18n: i bottoni sono appena stati creati, applica la lingua corrente
    if (window.i18n) window.i18n.applyLang();

    // ── Allegati: click = apri, tasto destro = menu (apri / salva con nome) ──
    async function fetchAttachmentBytes(att) {
      let aUrl = `${API}/mail/${encodeURIComponent(id)}/attachment/${encodeURIComponent(att.name)}`;
      const ps = [];
      if (accountId) ps.push(`account_id=${accountId}`);
      if (folder)    ps.push(`folder=${encodeURIComponent(folder)}`);
      if (ps.length) aUrl += '?' + ps.join('&');
      const r = await fetch(aUrl);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const buf = await r.arrayBuffer();
      return new Uint8Array(buf);
    }

    async function openAttachment(att) {
      try {
        // A program is never opened (main.js refuses it): ask without
        // fetching its bytes, so the refusal is all that happens.
        const exe = window.GMAttachmentGuard?.isExecutableName(att.name);
        const bytes = exe ? new Uint8Array(0) : await fetchAttachmentBytes(att);
        const res = await window.mailWindowAPI?.openAttachment(att.name, bytes);
        if (res && !res.ok && !res.canceled) alert(T('mv_cannot_open', 'Impossibile aprire') + ': ' + (res.error || T('mv_error_lower', 'errore')));
      } catch (e) { alert(T('mv_attachment_open_error', 'Errore apertura allegato') + ': ' + e.message); }
    }

    async function saveAttachmentAs(att) {
      try {
        const bytes = await fetchAttachmentBytes(att);
        const res = await window.mailWindowAPI?.saveAttachmentAs(att.name, bytes);
        if (res && !res.ok && !res.canceled) alert(T('mv_cannot_save', 'Impossibile salvare') + ': ' + (res.error || T('mv_error_lower', 'errore')));
      } catch (e) { alert(T('mv_attachment_save_error', 'Errore salvataggio allegato') + ': ' + e.message); }
    }

    document.querySelectorAll('.attach-chip[data-att-index]').forEach(chip => {
      const att = attachments[parseInt(chip.dataset.attIndex, 10)];
      if (!att) return;
      chip.addEventListener('click', () => openAttachment(att));
      chip.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showAttachMenu(e.clientX, e.clientY, att);
      });
    });

    // Menu contesto allegato
    function showAttachMenu(x, y, att) {
      hideAttachMenu();
      const menu = document.createElement('div');
      menu.className = 'attach-menu';
      menu.id = 'attachMenu';
      menu.innerHTML = `
        <div class="attach-menu-item" data-act="open">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('folder-open', 14) : '')} ${esc(T('mv_att_open', 'Apri'))}</div>
        <div class="attach-menu-item" data-act="save">${(typeof GMIcons !== 'undefined' ? GMIcons.svg('save', 14) : '')} ${esc(T('mv_att_save_as', 'Salva con nome…'))}</div>`;
      document.body.appendChild(menu);
      const rect = menu.getBoundingClientRect();
      const px = (x + rect.width  > window.innerWidth)  ? x - rect.width  : x;
      const py = (y + rect.height > window.innerHeight) ? y - rect.height : y;
      menu.style.left = Math.max(4, px) + 'px';
      menu.style.top  = Math.max(4, py) + 'px';
      menu.addEventListener('click', (ev) => {
        const it = ev.target.closest('.attach-menu-item');
        if (!it) return;
        const act = it.dataset.act;
        hideAttachMenu();
        if (act === 'open') openAttachment(att);
        else if (act === 'save') saveAttachmentAs(att);
      });
    }
    function hideAttachMenu() {
      document.getElementById('attachMenu')?.remove();
    }
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#attachMenu')) hideAttachMenu();
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideAttachMenu(); });

    // Popola corpo
    const bodyWrap = document.getElementById('mailBodyWrap');
    if (isHtml && rawHtml) {
      // Pipeline unica (mail_render.js): stessa sanitizzazione e stesso
      // iframe sandbox della finestra principale.
      window.MailRender.renderMailHtml(bodyWrap, rawHtml, {
        attachments,
        attachmentUrl: (att) => {
          let u = `${API}/mail/${encodeURIComponent(id)}/attachment/${encodeURIComponent(att.name)}`;
          const ps = [];
          if (accountId) ps.push(`account_id=${accountId}`);
          if (folder)    ps.push(`folder=${encodeURIComponent(folder)}`);
          return ps.length ? `${u}?${ps.join('&')}` : u;
        },
        openExternal: (href) => window.mailWindowAPI?.openExternal?.(href),
      });
    } else {
      const div = document.createElement('div');
      div.className = 'mail-body-text';
      // Testo semplice: escapato PRIMA dei <br>, e' contenuto della rete.
      div.innerHTML = esc(bodyText||T('mv_empty_message', '(messaggio vuoto)')).replace(/\n/g,'<br>');
      bodyWrap.appendChild(div);
    }

    // Bottoni azioni
    document.getElementById('btnClose2')?.addEventListener('click', () => window.mailWindowAPI?.close());

    // Ascolta TTS
    const ttsUrl = `${API}/mail/${encodeURIComponent(id)}/tts${accountId ? '?account_id=' + accountId : ''}`;
    const audio = new Audio(ttsUrl);
    let isPlaying = false;
    document.getElementById('btnAscolta')?.addEventListener('click', () => {
      const btn = document.getElementById('btnAscolta');
      if (isPlaying) {
        audio.pause(); audio.currentTime = 0;
        btn.textContent = '◉ ' + (window.i18n?window.i18n.t('listen_cap'):'Ascolta'); isPlaying = false;
      } else {
        audio.play(); btn.textContent = '◻ ' + T('mv_stop', 'Stop'); isPlaying = true;
      }
    });
    audio.onended = () => {
      const btn = document.getElementById('btnAscolta');
      if (btn) btn.textContent = '◉ ' + (window.i18n?window.i18n.t('listen_cap'):'Ascolta');
      isPlaying = false;
    };

    document.getElementById('btnReply')?.addEventListener('click', openReply);
    document.getElementById('btnReplyTrigger')?.addEventListener('click', openReply);
    document.getElementById('btnForward')?.addEventListener('click', openForward);

    document.getElementById('btnSummary')?.addEventListener('click', async () => {
      const btn = document.getElementById('btnSummary');
      btn.textContent = '…';
      try {
        let sUrl = `${API}/mail/${encodeURIComponent(id)}/summary`;
        if (accountId) sUrl += `?account_id=${accountId}`;
        if (folder) sUrl += `${accountId?'&':'?'}folder=${encodeURIComponent(folder)}`;
        const data = await apiJson(sUrl);
        const summaryEl = document.getElementById('aiSummary');
        const textEl    = document.getElementById('aiSummaryText');
        if (summaryEl && textEl) {
          textEl.textContent = data.summary || data.text || '';
          summaryEl.style.display = 'flex';
        }
      } catch(e) { btn.textContent = T('error', 'Errore'); }
      btn.innerHTML = (typeof GMIcons !== 'undefined' ? GMIcons.svg('clipboard', 14) : '') + ' ' + (window.i18n?window.i18n.t('summarize_cap'):'Riassumi');
    });

    document.getElementById('btnSpam')?.addEventListener('click', async () => {
      if (!(await GMDialog.confirm(window.i18n?window.i18n.t('move_to_spam'):'Spostare in spam?'))) return;
      try {
        await fetch(`${API}/mail/${encodeURIComponent(id)}/spam?account_id=${accountId}`, {method:'POST'});
        window.mailWindowAPI?.close();
      } catch {}
    });

    document.getElementById('btnDelete')?.addEventListener('click', async () => {
      if (!(await GMDialog.confirm(window.i18n?window.i18n.t('delete_this_mail'):'Eliminare questa mail?', { danger: true }))) return;
      try {
        await fetch(`${API}/mail/${encodeURIComponent(id)}?account_id=${accountId}`, {method:'DELETE'});
        window.mailWindowAPI?.close();
      } catch {}
    });

    function openReply() {
      if (window.mailWindowAPI?.openReply) {
        window.mailWindowAPI.openReply({
          id, folder, account_id: accountId,
          sender, senderName, subject,
        });
      }
    }
    function openForward() {
      if (window.mailWindowAPI?.openForward) {
        const fwdSubject = /^fwd:/i.test(subject) ? subject : `Fwd: ${subject || '(nessun oggetto)'}`;
        const dateText = msg.receivedDateTime || msg.sentDateTime || '';
        // Estrai testo leggibile: se la mail è HTML, strippa i tag; altrimenti usa il testo
        let cleanBody = bodyText || '';
        if (isHtml && rawHtml) {
          // Documento inerte (mail_render.js), mai innerHTML sul DOM vivo.
          cleanBody = MailRender.htmlToText(rawHtml);
        }
        const fwdBody = [
          '', '',
          '---------- Messaggio inoltrato ----------',
          `Da: ${senderName}${sender ? ` <${sender}>` : ''}`,
          `Data: ${dateText}`,
          `Oggetto: ${subject || '(nessun oggetto)'}`,
          '',
          cleanBody
        ].join('\n');
        window.mailWindowAPI.openForward({
          id, folder, account_id: accountId,
          sender, senderName, subject,
          mode: 'forward',
          forward_to: '',
          forward_subject: fwdSubject,
          forward_body: fwdBody,
          forward_attachments: (msg.attachments || []).map(a => a.name).filter(Boolean),
          forward_src_id: id,
          forward_src_folder: folder,
          forward_src_account: accountId,
        });
      }
    }

  } catch(e) {
    app.innerHTML = `<div class="loading">${window.i18n?window.i18n.t("error"):"Errore"}: ${esc(String(e))}</div>`;
  }
}

// Bottoni finestra
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btnClose')?.addEventListener('click', () => window.mailWindowAPI?.close());
  document.getElementById('btnDockBack')?.addEventListener('click', () => {
    if (window.mailWindowAPI?.dockBack) {
      // Passa id, folder, account_id alla console
      const id        = window._mailId;
      const folder    = window._mailFolder;
      const accountId = window._mailAccountId;
      window.mailWindowAPI.dockBack({ id, folder, account_id: accountId });
    }
  });
  document.getElementById('btnMin')?.addEventListener('click',   () => window.mailWindowAPI?.minimize());
  document.getElementById('btnMax')?.addEventListener('click',   () => window.mailWindowAPI?.maximize());
});
