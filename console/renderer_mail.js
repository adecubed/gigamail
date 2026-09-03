// renderer_mail.js — lista mail e dettaglio del messaggio (finestra principale).
//
// Estratto da renderer.js: stesso scope globale degli altri script classici
// (le variabili di stato — activeAccountId, selectedMailId, currentMailList,
// ... — restano dichiarate in renderer.js e vengono lette/scritte a runtime).
// Le parti PURE (HTML di una voce, header del dettaglio, testo dall'HTML)
// stanno in window.MailView e sono coperte da tests/mail_view.test.js:
// ogni stringa che arriva dalla rete passa da esc() — mittente, oggetto,
// nomi allegato, indirizzi — e il testo per l'inoltro viene da un documento
// inerte (DOMParser), mai da innerHTML sul documento vivo.

const MailView = (() => {
  function senderLabel(m) {
    return m.from?.emailAddress?.name ||
      m.from?.emailAddress?.address ||
      m.sender?.emailAddress?.name ||
      m.sender?.emailAddress?.address || '?';
  }

  function hasAttachments(m) {
    return !!(m.hasAttachments || m.has_attachments ||
      (Array.isArray(m.attachments) && m.attachments.length > 0));
  }

  /** HTML di una voce della lista. Tutto cio' che viene dal messaggio e' escapato. */
  function listItemHtml(m, accountId) {
    const date    = fmtDate(m.receivedDateTime || m.sentDateTime || m.createdDateTime);
    const preview = m.bodyPreview || m.body_text || '';
    const unread  = (m.isRead === false) ? 'unread' : '';
    const folder  = m.folder ? ` · ${m.folder}` : '';
    const attIcon = hasAttachments(m) ? '<span class="mail-attach-icon" title="Contiene allegati">📎</span> ' : '';
    const f = esc(cleanFolder(m.folder) || '');
    return `
      <div class="mail-item ${unread}" data-id="${esc(m.id)}" data-folder="${f}" data-account-id="${esc(accountId || '')}">
        <div class="mail-subject">
          ${attIcon}${esc(m.subject || '(nessun oggetto)')}
          <button class="mail-delete-btn" data-id="${esc(m.id)}" data-folder="${f}" title="${T('delete','Elimina')}">✕</button>
        </div>
        <div class="mail-meta">
          <span class="mail-sender">${esc(senderLabel(m))}${esc(folder)}</span>
          <span class="mail-date">${esc(date)}</span>
        </div>
        <div class="mail-preview">${esc(preview)}</div>
      </div>`;
  }

  function addressList(list) {
    return (list || []).map(r => esc(r?.emailAddress?.address || '')).join(', ');
  }

  function attachmentChipsHtml(atts) {
    if (!atts || !atts.length) return '';
    return `
        <div class="mail-attachments">
          ${atts.map((a, idx) => `
            <div class="attachment-chip" data-att-index="${idx}" style="cursor:pointer;user-select:none" title="Click: apri • Tasto destro: opzioni">
              📎 ${esc(a.name)} (${Math.round((a.size||0)/1024)}KB)
            </div>
          `).join('')}
        </div>`;
  }

  /** Header del dettaglio: oggetto, meta, azioni, riassunto, allegati. */
  function detailHeaderHtml(msg, ctx) {
    const { sender, senderName, ttsUrl, inSpam } = ctx;
    return `
        <div class="mail-detail-header">
          <div class="mail-detail-subject">${esc(msg.subject || '(nessun oggetto)')}</div>
          <div class="mail-detail-meta">Da: ${esc(senderName)} &lt;${esc(sender)}&gt; — ${esc(fmtDate(msg.receivedDateTime || msg.sentDateTime))}</div>
          ${(msg.toRecipients||[]).length ? `<div class="mail-detail-meta" style="font-size:11px;opacity:0.7">A: ${addressList(msg.toRecipients)}</div>` : ''}
          ${(msg.ccRecipients||[]).length ? `<div class="mail-detail-meta" style="font-size:11px;opacity:0.7">CC: ${addressList(msg.ccRecipients)}</div>` : ''}
          <div class="mail-detail-actions">
            <audio id="mailAudio" src="${esc(ttsUrl)}" style="display:none"></audio>
            <button class="btn" id="btnAscolta">◉ ${T('listen','ASCOLTA')}</button>
            <button class="btn" id="btnShowReply">↩ ${T('reply_upper','RISPONDI')}</button>
            <button class="btn" id="btnShowReplyAll">↩↩ ${T('all_upper','TUTTI')}</button>
            <button class="btn" id="btnForward">↪ ${T('forward_upper','INOLTRA')}</button>
            <button class="btn" id="btnRiassumi">📋 ${T('summarize_upper','RIASSUMI')}</button>
            <button class="btn" id="btnMove">📁 ${T('move_upper','SPOSTA')}</button>
            ${inSpam
              ? `<button class="btn" id="btnNotSpam">✅ ${T('not_spam_upper','NON È SPAM')}</button>`
              : `<button class="btn" id="btnSpam">🚫 ${T('spam_upper','SPAM')}</button>`
            }
            <button class="btn btn-danger" id="btnDelete">🗑 ${T('delete_upper','ELIMINA')}</button>
            <button class="btn" id="btnMarkUnread">● ${T('unread_upper','NON LETTA')}</button>
          </div>
        </div>
        <div class="mail-summary-box" id="mailSummaryBox" style="background:linear-gradient(135deg,#eeb9dd,#b0c7f4);border:1.5px solid rgba(0,0,0,0.75);border-radius:10px;margin:10px 15px 0;padding:9px 12px;font-size:11px;color:rgba(0,0,0,0.75);box-shadow:0 4px 14px rgba(0,0,0,0.35);">📋 ${T('press_summarize','Premi RIASSUMI per generare il riassunto.')}</div>
        <div class="mail-suggestion-box hidden" id="mailSuggestionBox"></div>${attachmentChipsHtml(msg.attachments)}`;
  }

  /** Testo semplice da HTML di posta, per citare/inoltrare. Documento inerte:
   *  niente esecuzione di script o handler, niente caricamento di risorse. */
  function htmlToText(html) {
    const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
    doc.querySelectorAll('style, script, head, meta, link, noscript, template').forEach(el => el.remove());
    // <br> e blocchi diventano a capo, come faceva innerText sull'elemento vivo
    doc.querySelectorAll('br').forEach(el => el.replaceWith('\n'));
    doc.querySelectorAll('p, div, li, tr, h1, h2, h3, h4, h5, h6, blockquote, pre').forEach(el => el.append('\n'));
    return (doc.body ? doc.body.textContent : '').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  return { senderLabel, hasAttachments, listItemHtml, detailHeaderHtml, attachmentChipsHtml, htmlToText };
})();
if (typeof window !== 'undefined') window.MailView = MailView;

// ============================================================
// MAIL LIST
// ============================================================

function renderMailList(mails) {
  const list = byId('mailList');
  if (!list) return;

  if (!Array.isArray(mails) || mails.length === 0) {
    list.innerHTML = '<div class="list-empty">'+T('no_mail','Nessuna mail.')+'</div>';
    return;
  }

  list.innerHTML = mails.map(m => MailView.listItemHtml(m, activeAccountId)).join('');

  currentMailList = mails;
  list.querySelectorAll('.mail-item').forEach((item, idx) => {
    item.addEventListener('click', () => { if (item.dataset.id) { currentMailIndex = idx; openMail(item.dataset.id, item.dataset.folder || null); } });
    item.addEventListener('dblclick', () => { if (item.dataset.id) openMailWindow(item.dataset.id, item.dataset.folder || null); });
  });
  list.querySelectorAll('.mail-delete-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteMail(btn.dataset.id, btn.dataset.folder);
    });
  });
}

async function deleteMail(id, folder) {
  if (!id) return;
  try {
    const params = new URLSearchParams();
    if (activeAccountId) params.append('account_id', activeAccountId);
    if (folder) params.append('folder', folder);
    const res = await fetch(`http://localhost:8002/mail/${encodeURIComponent(id)}?${params}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error(await res.text());
    showToast('Mail eliminata', 'success');
    document.querySelector(`.mail-item[data-id="${id}"]`)?.remove();
    if (selectedMailId === id) resetMailDetail();
    currentMailList = currentMailList.filter(m => m.id !== id);
  } catch (e) {
    showToast('Errore eliminazione: ' + e.message, 'error');
  }
}

// ============================================================
// OPEN MAIL
// ============================================================

async function openMail(id, overrideFolder = null) {
  overrideFolder = cleanFolder(overrideFolder);
  selectedMailId = id;
  selectedMailFolder = overrideFolder || null;
  // Esponi per popup_bridge.js
  window._currentMailId     = id;
  window._currentMailFolder = overrideFolder || null;
  window._activeAccountId   = activeAccountId;
  updateVoiceContext(id, 0);
  document.querySelectorAll('.mail-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.id === id);
    if (el.dataset.id === id) el.classList.remove('unread');
  });

  const detail = byId('mailDetail');
  if (!detail) return;
  detail.classList.remove('mail-detail-empty');
  detail.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-family:var(--mono);font-size:11px">'+T('loading','Caricamento...')+'</div>';

  try {
    // Usa cartella esplicita (da search results) o quella corrente
    const folderValue = overrideFolder || getCurrentFolderRequestValue();
    const msg = await api.readMail(id, activeAccountId, folderValue);

    const sender     = msg.from?.emailAddress?.address || '?';
    const senderName = msg.from?.emailAddress?.name || sender;
    const ttsUrl     = api.getTtsUrl(id, activeAccountId, folderValue);

    // Corpo mail: preferisci HTML nativo (Microsoft), poi body_text, poi bodyPreview
    const rawHtml    = msg.body?.content || '';
    const bodyType   = (msg.body?.contentType || '').toLowerCase();
    const bodyText   = msg.body_text || msg.bodyPreview || '';
    window._currentMailBodyText = bodyText;  // cache per smart_draft — evita IMAP lento
    const hasHtmlInText = /<[a-z][^>]*>/i.test(bodyText);
    const isHtmlBody = bodyType === 'html' || (rawHtml && rawHtml.trimStart().startsWith('<')) || hasHtmlInText;
    const effectiveHtml = isHtmlBody && !rawHtml ? `<html><body style="font-family:sans-serif;font-size:13px;line-height:1.7;padding:16px;color:#333;">${bodyText}</body></html>` : rawHtml;
    const bodyHtml   = isHtmlBody ? null : formatMailBodyHtml(bodyText);

    detail.className = '';
    detail.style.cssText = 'display:flex;flex-direction:column;flex:1;min-width:0;overflow:hidden;border-left:1px solid rgba(0,0,0,0.08);';
    detail.innerHTML = `
      <div class="mail-detail-content" style="display:flex;flex-direction:column;height:100%;overflow:hidden;">
        <div style="
          height:36px;flex-shrink:0;
          display:flex;align-items:center;padding:0 12px;gap:8px;
          background:linear-gradient(135deg,#eeb9dd,#b0c7f4);
          border-bottom:1px solid rgba(0,0,0,0.08);
          user-select:none;
        ">
          <button id="btnPopOut" title="${T('open_in_window','Apri in finestra')}" style="-webkit-app-region:no-drag;width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,#eeb9dd,#b0c7f4);border:1.5px solid rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;font-size:13px;cursor:pointer;color:rgba(0,0,0,0.6);box-shadow:0 4px 14px rgba(0,0,0,0.35);flex-shrink:0;">⤢</button>
          <div style="flex:1;font-size:11px;font-weight:500;color:rgba(0,0,0,0.75);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(msg.subject || '(nessun oggetto)')}</div>
        </div>
        <div style="flex:1;overflow-y:auto;display:flex;flex-direction:column;min-height:0;">
        ${MailView.detailHeaderHtml(msg, { sender, senderName, ttsUrl, inSpam: currentFolder === 'spam' })}
        <div class="sender-history-box" id="senderHistoryBox"></div>
        <div class="mail-body" id="mailBody"></div>
        </div><!-- /scroll wrap -->
        </div><!-- /mail-detail-content -->
      </div>`;

    // i18n: bottoni mail appena creati, applica lingua corrente
    if (window.i18n) window.i18n.applyLang();

    // Proattivo: mostra lo storico con questo mittente (modulo esterno, slegato da Brain)
    if (window.renderSenderHistory) {
        try { window.renderSenderHistory(byId('senderHistoryBox'), sender, activeAccountId); }
        catch (e) { console.warn('senderHistory:', e); }
    }

    // Popola corpo mail
    const mailBodyEl = byId('mailBody');
    if (mailBodyEl) {
      if (isHtmlBody) {
        // Pipeline unica (mail_render.js): sanitizzazione strutturale,
        // iframe sandbox senza script, cid: risolti sugli allegati, link
        // al browser esterno. Stessa strada della finestra mail.
        window.MailRender.renderMailHtml(mailBodyEl, effectiveHtml || rawHtml, {
          attachments: msg.attachments || [],
          attachmentUrl: (att) => api.getAttachmentUrl(id, att.name, activeAccountId, folderValue),
          openExternal: (href) => window.electronAPI?.openExternal?.(href),
          autoHeight: true,
        });
      } else {
        mailBodyEl.innerHTML = bodyHtml || '<p class="mail-paragraph mail-empty-body">(messaggio senza contenuto testuale)</p>';
      }
    }

// Allegati: click = apri, tasto destro = menu
    (function setupAttachments() {
      const atts = msg.attachments || [];
      if (!atts.length) return;
      async function fetchBytes(att) {
        const url = api.getAttachmentUrl(id, att.name, activeAccountId, folderValue);
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return new Uint8Array(await r.arrayBuffer());
      }
      async function openAtt(att) {
        try { const b = await fetchBytes(att); const res = await window.electronAPI?.openAttachment(att.name, b);
          if (res && !res.ok && !res.canceled) alert('Impossibile aprire: ' + (res.error||'errore')); }
        catch(e){ alert('Errore apertura: ' + e.message); }
      }
      async function saveAtt(att) {
        try { const b = await fetchBytes(att); const res = await window.electronAPI?.saveAttachmentAs(att.name, b);
          if (res && !res.ok && !res.canceled) alert('Impossibile salvare: ' + (res.error||'errore')); }
        catch(e){ alert('Errore salvataggio: ' + e.message); }
      }
      function hideMenu(){ document.getElementById('attachCtxMenu')?.remove(); }
      function showMenu(x, y, att) {
        hideMenu();
        const m = document.createElement('div');
        m.id = 'attachCtxMenu';
        m.style.cssText = 'position:fixed;z-index:99999;min-width:160px;background:#fff;border:1.5px solid rgba(0,0,0,0.75);border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,0.35);padding:5px;font-family:inherit';
        m.innerHTML = '<div class="att-ctx-item" data-act="open" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer">📂 Apri</div><div class="att-ctx-item" data-act="save" style="padding:8px 12px;border-radius:7px;font-size:13px;cursor:pointer">💾 Salva con nome…</div>';
        document.body.appendChild(m);
        const rect = m.getBoundingClientRect();
        m.style.left = Math.max(4, (x+rect.width>window.innerWidth)?x-rect.width:x) + 'px';
        m.style.top  = Math.max(4, (y+rect.height>window.innerHeight)?y-rect.height:y) + 'px';
        m.querySelectorAll('.att-ctx-item').forEach(it => {
          it.addEventListener('mouseenter', () => it.style.background = 'rgba(176,199,244,0.3)');
          it.addEventListener('mouseleave', () => it.style.background = 'transparent');
        });
        m.addEventListener('click', (ev) => {
          const it = ev.target.closest('.att-ctx-item'); if (!it) return;
          const act = it.dataset.act; hideMenu();
          if (act === 'open') openAtt(att); else if (act === 'save') saveAtt(att);
        });
      }
      document.addEventListener('click', (e) => { if (!e.target.closest('#attachCtxMenu')) hideMenu(); });
      document.querySelectorAll('.attachment-chip[data-att-index]').forEach(chip => {
        const att = atts[parseInt(chip.dataset.attIndex, 10)];
        if (!att) return;
        chip.addEventListener('click', () => openAtt(att));
        chip.addEventListener('contextmenu', (e) => { e.preventDefault(); showMenu(e.clientX, e.clientY, att); });
      });
    })();

    // ASCOLTA toggle
    const mailAudio = byId('mailAudio');
    const btnAscolta = byId('btnAscolta');
    if (mailAudio && btnAscolta) {
      let isPlaying = false;
      btnAscolta.addEventListener('click', () => {
        if (isPlaying) {
          mailAudio.pause(); mailAudio.currentTime = 0;
          setVoicePlaybackActive(false);
          btnAscolta.textContent = '◉ ' + T('listen','ASCOLTA'); isPlaying = false;
        } else {
          setVoicePlaybackActive(true);
          mailAudio.play(); btnAscolta.textContent = '◻ STOP'; isPlaying = true;
        }
      });
      mailAudio.onended = () => { setVoicePlaybackActive(false); btnAscolta.textContent = '◉ ' + T('listen','ASCOLTA'); isPlaying = false; };
      mailAudio.onpause = () => { setVoicePlaybackActive(false); };
      // Esposta globale: permette a "giga stop" (voice_mail.js) di fermare la lettura mail
      window.stopMailReading = () => {
        try { mailAudio.pause(); mailAudio.currentTime = 0; } catch (e) {}
        setVoicePlaybackActive(false);
        btnAscolta.textContent = '◉ ' + T('listen','ASCOLTA');
        isPlaying = false;
      };
    }

    // RIASSUMI toggle
    byId('btnRiassumi')?.addEventListener('click', async () => {
      const btn = byId('btnRiassumi');
      if (btn._playing && btn._audio) {
        btn._audio.pause(); btn._audio.currentTime = 0;
        btn.textContent = '📋 ' + T('summarize_upper','RIASSUMI'); btn._playing = false; return;
      }
      try {
        btn.textContent = '...';
        const summaryText = await ensureMailSummary(id, activeAccountId, detail, folderValue);
        if (!summaryText) {
          btn.textContent = '📋 ' + T('summarize_upper','RIASSUMI');
          return;
        }
        const blob = await api.speakText(summaryText);
        const url  = URL.createObjectURL(blob);
        btn._audio = new Audio(url);
        setVoicePlaybackActive(true);
        btn._audio.play(); btn._playing = true; btn.textContent = '◻ STOP';
        btn._audio.onended = () => { setVoicePlaybackActive(false); btn.textContent = '📋 ' + T('summarize_upper','RIASSUMI'); btn._playing = false; URL.revokeObjectURL(url); };
        btn._audio.onpause = () => { setVoicePlaybackActive(false); };
      } catch (e) { showToast(`Errore TTS: ${e}`); }
    });

    loadFolderSuggestion(id, detail).catch(e => console.error('loadFolderSuggestion:', e));

    // SUGGERIMENTO RISPOSTA PROATTIVO
    if (msg._reply_suggestion?.has_suggestion) {
      const s = msg._reply_suggestion;
      const confLabel = s.confidence === 'alta' ? '🟢' : s.confidence === 'media' ? '🟡' : '🟠';
      const suggestBox = byId('mailSuggestionBox');
      if (suggestBox) {
        suggestBox.classList.remove('hidden');
        const banner = document.createElement('div');
        banner.className = 'reply-suggestion-banner';
        const previewText = (s.draft || '').slice(0, 120) + (s.draft?.length > 120 ? '...' : '');
        banner.innerHTML =
          '<div class="mail-suggestion-title">' + confLabel + ' RISPOSTA SUGGERITA (usata ' + s.frequency + ' volte)</div>' +
          '<div class="suggestion-preview">' + esc(previewText) + '</div>' +
          '<div class="mail-suggestion-actions">' +
          '<button class="btn btn-secondary" id="btnUseSuggestion">'+T('use_draft','USA QUESTA BOZZA')+'</button>' +
          '<button class="btn btn-secondary" id="btnDismissReplySuggestion">'+T('ignore','IGNORA')+'</button>' +
          '</div>';
        suggestBox.appendChild(banner);
        byId('btnUseSuggestion')?.addEventListener('click', () => {
          replyAttachments = [];
          currentReplyDefaultTo = sender || '';
          currentReplyDefaultSubject = /^re:/i.test(msg.subject || '')
            ? (msg.subject || '')
            : 'Re: ' + (msg.subject || '(nessun oggetto)');
          openNativeReplyWindow(currentReplyDefaultTo, currentReplyDefaultSubject);
          setTimeout(() => {
            if (byId('replyText')) byId('replyText').value = s.draft || '';
            currentDraft = s.draft || '';
            currentInstruction = '';
          }, 50);
          banner.remove();
        });
        byId('btnDismissReplySuggestion')?.addEventListener('click', () => banner.remove());
      }
    }

    // SPAM
    byId('btnSpam')?.addEventListener('click', async () => {
      if (!confirm('Spostare in spam?')) return;
      try {
        await api.spamMail(id, activeAccountId, currentFolder);
        document.querySelector(`[data-id="${id}"]`)?.remove();
        resetMailDetail();
        await refreshCurrentFolder();
      } catch (e) { showToast(`Errore spam: ${e}`); }
    });

    // NON È SPAM — endpoint dedicato che blocca l'auto-route
    byId('btnNotSpam')?.addEventListener('click', async () => {
      try {
        const folder = selectedMailFolder || getCurrentFolderRequestValue();
        const params = new URLSearchParams();
        if (activeAccountId) params.append('account_id', activeAccountId);
        if (folder) params.append('folder', folder);
        const res = await fetch(`http://127.0.0.1:8002/mail/${encodeURIComponent(id)}/not_spam?${params}`, { method: 'POST' });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        const moved = data.moved || 1;
        // Rimuovi dalla lista tutte le mail visibili (potrebbero essere state spostate in bulk)
        await refreshCurrentFolder();
        resetMailDetail();
        showToast(moved > 1 ? `✅ ${moved} mail spostate in INBOX` : '✅ Mail spostata in INBOX');
      } catch (e) { showToast(`Errore: ${e}`); }
    });

    // ELIMINA
    byId('btnDelete')?.addEventListener('click', async () => {
      if (!confirm('Eliminare questa mail?')) return;
      try {
        await api.deleteMail(id, activeAccountId);
        document.querySelector(`[data-id="${id}"]`)?.remove();
        resetMailDetail();
      } catch (e) { showToast(`Errore elimina: ${e}`); }
    });

    byId('btnMarkUnread')?.addEventListener('click', async () => {
      try {
        const folderValue = selectedMailFolder || getCurrentFolderRequestValue();
        await fetch(`http://127.0.0.1:8002/mail/${encodeURIComponent(selectedMailId)}/unread?account_id=${activeAccountId}&folder=${encodeURIComponent(folderValue||'')}`, { method: 'POST' });
        // Rimarca come unread nel DOM
        document.querySelectorAll('.mail-item').forEach(el => {
          if (el.dataset.id === selectedMailId) el.classList.add('unread');
        });
        showToast('Marcata come non letta');
      } catch(e) { showToast('Errore: ' + e); }
    });

    byId('btnShowReply')?.addEventListener('click', () => {
      replyAttachments = [];
      currentReplyCc = [];
      currentReplyDefaultTo = sender || '';
      currentReplyDefaultSubject = /^re:/i.test(msg.subject || '')
        ? (msg.subject || '')
        : `Re: ${msg.subject || '(nessun oggetto)'}`;
      openNativeReplyWindow(currentReplyDefaultTo, currentReplyDefaultSubject);
    });
    byId('btnShowReplyAll')?.addEventListener('click', () => {
      replyAttachments = [];
      currentReplyCc = [];
      const ownEmail = (activeAccountId
        ? (window._accounts?.find(a => a.id === activeAccountId)?.email || '')
        : ''
      ).toLowerCase();
      const allAddrs = [
        ...(msg.toRecipients || []),
        ...(msg.ccRecipients || []),
      ]
        .map(r => r?.emailAddress?.address || '')
        .filter(a => a && a.toLowerCase() !== ownEmail && a.toLowerCase() !== sender.toLowerCase());
      const ccAddrs = [...new Set(allAddrs)];
      currentReplyCc = ccAddrs;
      currentReplyDefaultTo = sender || '';
      currentReplyDefaultSubject = /^re:/i.test(msg.subject || '')
        ? (msg.subject || '')
        : `Re: ${msg.subject || '(nessun oggetto)'}`;
      // Passa ccAddrs direttamente alla reply window
      if (window.electronAPI?.openReplyWindow) {
        window.electronAPI.openReplyWindow({
          sender:      currentReplyDefaultTo,
          subject:     currentReplyDefaultSubject,
          id:          selectedMailId,
          folder:      selectedMailFolder,
          account_id:  activeAccountId,
          instruction: '',
          body_text:   window._currentMailBodyText || '',
          replyAll:    true,
          ccAddrs,
        });
      } else {
        openReplyModal(currentReplyDefaultTo, currentReplyDefaultSubject);
      }
    });
    byId('btnMove')?.addEventListener('click', () => openMoveMailPanel(id));
    byId('btnForward')?.addEventListener('click', () => openForwardComposer(msg));

    byId('btnReplyVoice')?.addEventListener('click', () => byId('btnVoice')?.click());
    byId('btnGenerateReply')?.addEventListener('click', generateReply);
    byId('btnSendReply')?.addEventListener('click', sendReply);
    byId('replyToInput')?.addEventListener('input', () => handleAddressAutocomplete('replyToInput', 'replyToAutocomplete'));
    byId('replyToInput')?.addEventListener('focus', () => handleAddressAutocomplete('replyToInput', 'replyToAutocomplete'));
    byId('replySubjectInput')?.addEventListener('focus', () => hideAutocompleteBoxes());
    byId('replyText')?.addEventListener('focus', () => hideAutocompleteBoxes());
    byId('replyText')?.addEventListener('click', () => hideAutocompleteBoxes());

    // Allegati reply
    byId('btnReplyAttach')?.addEventListener('click', () => byId('replyFileInput')?.click());
    byId('replyFileInput')?.addEventListener('change', async (e) => {
      for (const file of e.target.files) {
        const data_b64 = await new Promise((res, rej) => {
          const reader = new FileReader();
          reader.onload = () => res(reader.result.split(',')[1]);
          reader.onerror = rej;
          reader.readAsDataURL(file);
        });
        replyAttachments.push({ name: file.name, data_b64, type: file.type || 'application/octet-stream', size: file.size });
      }
      e.target.value = '';
      renderReplyAttachments();
    });

  } catch (e) {
    detail.className = '';
    detail.innerHTML = `<div style="padding:20px;color:var(--red);font-family:var(--mono);font-size:11px">Errore: ${esc(String(e))}</div>`;
  }
}

function openMailWindow(id, overrideFolder = null) {
  // La finestra mail e' una BrowserWindow con il suo preload (mail_window.html),
  // non un window.open: main.js nega i blob: e la pipeline di rendering e'
  // la stessa della finestra principale (mail_render.js).
  if (!id) return;
  const folder = cleanFolder(overrideFolder) || null;
  if (window.electronAPI?.openMailWindow) {
    window.electronAPI.openMailWindow({ id, folder, account_id: activeAccountId || null });
  } else {
    openMail(id, folder);
  }
}

function openForwardComposer(msg) {
  const sender = msg?.from?.emailAddress?.address || '';
  const senderName = msg?.from?.emailAddress?.name || sender;
  const subject = msg?.subject || '';
  let bodyText = msg?.body_text || msg?.bodyPreview || '';
  const rawForward = msg?.body?.content || '';
  const isHtmlForward = (msg?.body?.contentType||'').toLowerCase() === 'html' || rawForward.trimStart().startsWith('<');
  if (isHtmlForward && rawForward) {
    bodyText = MailView.htmlToText(rawForward);
  }
  const dateText = fmtDate(msg?.receivedDateTime || msg?.sentDateTime || msg?.createdDateTime);
  const forwardSubject = /^fwd:/i.test(subject) ? subject : `Fwd: ${subject || '(nessun oggetto)'}`;
  const forwardBody = [
    '',
    '',
    '---------- Messaggio inoltrato ----------',
    `Da: ${senderName}${sender ? ` <${sender}>` : ''}`,
    `Data: ${dateText}`,
    `Oggetto: ${subject || '(nessun oggetto)'}`,
    '',
    bodyText || '',
  ].join('\n');

  if (window.electronAPI?.openReplyWindow) {
    // Forward via finestra reply (gestisce mode:'forward' e ri-allega gli originali)
    window.electronAPI.openReplyWindow({
      mode: 'forward',
      sender: '',
      subject: forwardSubject,
      body: forwardBody,
      forward_subject: forwardSubject,
      forward_body: forwardBody,
      id: null,
      account_id: activeAccountId,
      // riferimenti per scaricare e ri-allegare gli allegati dell'originale
      forward_attachments: (msg.attachments || []).map(a => a.name).filter(Boolean),
      forward_src_id: msg.id,
      forward_src_folder: msg.folder || '',
      forward_src_account: activeAccountId,
    });
  } else if (window.electronAPI?.openNewMailWindow) {
    window.electronAPI.openNewMailWindow({
      account_id: activeAccountId,
      subject: forwardSubject,
      body: forwardBody,
    });
  } else {
    // fallback pannello inline
    if (byId('newMailTo')) byId('newMailTo').value = '';
    if (byId('newMailCc')) byId('newMailCc').value = '';
    if (byId('newMailBcc')) byId('newMailBcc').value = '';
    if (byId('newMailSubject')) byId('newMailSubject').value = forwardSubject;
    if (byId('newMailBody')) byId('newMailBody').value = forwardBody;
    if (byId('newMailStatus')) byId('newMailStatus').textContent = '';
    pendingAttachments = [];
    renderPendingAttachments();
    setHidden('newMailPanel', false);
    byId('newMailTo')?.focus();
  }
}
