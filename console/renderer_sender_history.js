// renderer_sender_history.js — Pannello proattivo "storico con il mittente".
// Slegato da Brain: usa gli endpoint /mail/sender_history e /mail/sender_summary
// che leggono solo il DB mail locale. Caricato in index_v2.html dopo renderer.js.
//
// Espone: window.renderSenderHistory(container, senderEmail, accountId)
// - chiamato all'apertura di una mail (da openMail in renderer.js)
// - mostra subito conteggio + temi (istantaneo, no LLM)
// - bottone "Riassumi storico" → riassunto LLM on-demand

(function () {
  const API = (typeof window !== 'undefined' && (window.GIGAMAIL_API || window.__ADE_MAIL_API__)) || 'http://127.0.0.1:8002';

  function _t(key, fallback) {
    return (window.i18n && window.i18n.t) ? window.i18n.t(key) : fallback;
  }

  function _esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function _year(d) {
    if (!d) return '';
    const s = String(d);
    if (s.length >= 4 && /^\d{4}/.test(s)) return s.slice(0, 4);
    const m = s.match(/\b(19|20)\d{2}\b/);
    return m ? m[0] : '';
  }

  async function renderSenderHistory(container, senderEmail, accountId) {
    if (!container || !senderEmail) return;
    container.innerHTML = '';
    container.style.display = 'none';

    let hist;
    try {
      const url = `${API}/mail/sender_history?sender=${encodeURIComponent(senderEmail)}`
        + (accountId ? `&account_id=${accountId}` : '');
      const r = await fetch(url);
      hist = await r.json();
    } catch (e) {
      return; // silenzioso: se fallisce, nessun riquadro
    }

    const count = hist && hist.count ? hist.count : 0;
    // Non mostrare nulla se è la prima/unica mail di questo mittente (niente "storico")
    if (count <= 1) return;

    const name = hist.sender_name || senderEmail;
    const y1 = _year(hist.first_date);
    const y2 = _year(hist.last_date);
    const period = (y1 && y2 && y1 !== y2) ? `${y1}–${y2}` : (y2 || y1 || '');
    const temi = (hist.temi || []).slice(0, 5);

    const sentLabel = _t('history_sent', 'inviate');
    const recvLabel = _t('history_received', 'ricevute');
    const withLabel = _t('history_with', 'mail con');
    const themesLabel = _t('history_themes', 'Temi');
    const summarizeLabel = _t('history_summarize', 'Riassumi storico');

    const temiHtml = temi.length
      ? `<div class="sh-themes"><span class="sh-themes-label">${_esc(themesLabel)}:</span> ${temi.map(t => `<span class="sh-chip">${_esc(t)}</span>`).join(' ')}</div>`
      : '';

    container.innerHTML = `
      <div class="sh-card">
        <div class="sh-main">
          <span class="sh-icon">📋</span>
          <div class="sh-text">
            <div class="sh-line1"><b>${count}</b> ${_esc(withLabel)} <b>${_esc(name)}</b>${period ? ` · ${period}` : ''}</div>
            <div class="sh-line2">${hist.sent_count || 0} ${_esc(sentLabel)} · ${hist.received_count || 0} ${_esc(recvLabel)}</div>
            ${temiHtml}
          </div>
          <button class="sh-summarize" id="shSummarizeBtn">✨ ${_esc(summarizeLabel)}</button>
        </div>
        <div class="sh-summary" id="shSummary" style="display:none"></div>
      </div>`;

    // stile inline (no dipendenza da CSS esterno; tema coerente con l'app)
    if (!document.getElementById('sh-style')) {
      const st = document.createElement('style');
      st.id = 'sh-style';
      st.textContent = `
        .sh-card{margin:0 0 14px;border:1px solid rgba(0,0,0,0.1);border-radius:12px;
          background:linear-gradient(135deg,rgba(238,185,221,0.10),rgba(176,199,244,0.10));
          padding:11px 14px;font-size:12px;}
        .sh-main{display:flex;align-items:flex-start;gap:10px;}
        .sh-icon{font-size:16px;flex-shrink:0;line-height:1.3;}
        .sh-text{flex:1;min-width:0;}
        .sh-line1{color:rgba(0,0,0,0.8);margin-bottom:2px;}
        .sh-line2{color:rgba(0,0,0,0.5);font-size:11px;}
        .sh-themes{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;}
        .sh-themes-label{color:rgba(0,0,0,0.45);font-size:11px;}
        .sh-chip{background:rgba(176,199,244,0.25);border-radius:6px;padding:1px 7px;font-size:11px;color:rgba(0,0,0,0.7);}
        .sh-summarize{flex-shrink:0;border:1px solid rgba(0,0,0,0.15);background:#fff;border-radius:8px;
          padding:5px 10px;font-size:11px;cursor:pointer;color:rgba(0,0,0,0.7);transition:all .15s;}
        .sh-summarize:hover{box-shadow:0 2px 8px rgba(0,0,0,0.12);}
        .sh-summarize:disabled{opacity:0.5;cursor:default;}
        .sh-summary{margin-top:10px;padding-top:10px;border-top:1px solid rgba(0,0,0,0.08);
          color:rgba(0,0,0,0.75);font-size:12px;line-height:1.55;white-space:pre-wrap;}
      `;
      document.head.appendChild(st);
    }

    container.style.display = 'block';

    // bottone riassunto on-demand
    const btn = container.querySelector('#shSummarizeBtn');
    const summaryEl = container.querySelector('#shSummary');
    if (btn) {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        const loadingTxt = _t('history_summarizing', 'Riassumo…');
        summaryEl.style.display = 'block';
        summaryEl.textContent = loadingTxt;
        try {
          const r = await fetch(`${API}/mail/sender_summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              sender: senderEmail,
              account_id: accountId,
              lang: (window.i18n ? window.i18n.lang : (localStorage.getItem('ade_lang') || 'it')),
            }),
          });
          const d = await r.json();
          summaryEl.textContent = d.summary || _t('history_no_summary', 'Nessun riassunto disponibile.');
        } catch (e) {
          summaryEl.textContent = _t('history_summary_error', 'Errore nel riassunto.');
        }
        btn.disabled = false;
      });
    }
  }

  window.renderSenderHistory = renderSenderHistory;
})();
