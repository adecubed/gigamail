/* renderer_zoom.js — Collegamento Zoom: link automatico per le video call.
 *
 * Quando un cliente conferma una video call, GigaMail crea la riunione e
 * prepara la mail con il link, che parte solo dopo l'approvazione. Qui si
 * incollano i tre codici dell'app Server-to-Server OAuth di Zoom.
 *
 * Il Client Secret va al backend locale e non torna mai alla pagina: lo
 * stato dice solo se Zoom e' collegato e con quale Account ID.
 */

const ZoomView = (() => {

  const api = () => window.ademail;
  const el = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  function say(msg, tone) {
    const box = el('zoomStatus');
    if (!box) return;
    const colore = tone === 'err' ? 'rgba(180,40,30,0.85)'
                 : tone === 'ok' ? 'rgba(20,130,70,0.9)'
                 : 'var(--muted, #666)';
    box.innerHTML = `<span style="color:${colore}">${esc(msg)}</span>`;
  }

  function bodyHtml(s) {
    if (s && s.configured) {
      return `
      <p style="margin:0 0 10px;line-height:1.45">
        Zoom e' <b>collegato</b> (Account ID ${esc(s.account_id)}).
        Quando un cliente conferma una video call, GigaMail crea la riunione
        e prepara la mail con il link, che parte solo dopo la tua approvazione.
      </p>
      <div style="display:flex;gap:8px">
        <button class="chip-btn" id="btnZoomTest">Verifica</button>
        <button class="chip-btn" id="btnZoomRemove">Scollega</button>
      </div>
      <div id="zoomStatus" class="hint" style="margin-top:10px"></div>`;
    }
    return `
      <p style="margin:0 0 10px;line-height:1.45">
        Collega il tuo account Zoom: quando un cliente conferma una video call,
        GigaMail crea la riunione e prepara la mail con il link, che parte solo
        dopo la tua approvazione.
      </p>
      <ol style="margin:0 0 12px;padding-left:18px;line-height:1.5;font-size:12px">
        <li>Su <b>marketplace.zoom.us</b> apri Develop &gt; Build App e scegli
          <b>Server-to-Server OAuth</b>.</li>
        <li>In Scopes aggiungi <code>meeting:write:meeting:admin</code>,
          <code>meeting:update:meeting:admin</code>,
          <code>meeting:delete:meeting:admin</code> e
          <code>user:read:user:admin</code>.</li>
        <li>Attiva l'app e copia qui i tre codici.</li>
      </ol>
      <div class="field-row"><label class="field-label">Account ID</label>
        <input type="text" id="zoomAccountId" class="field-input" autocomplete="off"/></div>
      <div class="field-row"><label class="field-label">Client ID</label>
        <input type="text" id="zoomClientId" class="field-input" autocomplete="off"/></div>
      <div class="field-row"><label class="field-label">Client Secret</label>
        <input type="password" id="zoomClientSecret" class="field-input" autocomplete="off"/></div>
      <div style="display:flex;justify-content:flex-end;margin-top:10px">
        <button class="compose-btn" style="margin:0;width:auto;padding:8px 18px" id="btnZoomConnect">Collega Zoom</button>
      </div>
      <div id="zoomStatus" class="hint" style="margin-top:10px"></div>`;
  }

  async function render() {
    const corpo = el('zoomBody');
    if (!corpo) return;
    let s;
    try {
      s = await api().zoomStatus();
    } catch (e) {
      corpo.innerHTML = '<div id="zoomStatus" class="hint"></div>';
      say('Console non raggiungibile.', 'err');
      return;
    }
    corpo.innerHTML = bodyHtml(s);
    el('btnZoomConnect')?.addEventListener('click', connect);
    el('btnZoomTest')?.addEventListener('click', verifica);
    el('btnZoomRemove')?.addEventListener('click', scollega);
  }

  async function connect() {
    const dati = {
      account_id: (el('zoomAccountId')?.value || '').trim(),
      client_id: (el('zoomClientId')?.value || '').trim(),
      client_secret: (el('zoomClientSecret')?.value || '').trim(),
    };
    if (!dati.account_id || !dati.client_id || !dati.client_secret) {
      say('Servono tutti e tre i codici.', 'err');
      return;
    }
    const bottone = el('btnZoomConnect');
    if (bottone) bottone.disabled = true;
    say('Verifico con Zoom...');
    try {
      const esito = await api().zoomSetup(dati);
      await render();
      say(`Zoom collegato${esito.email ? `: ${esito.email}` : ''}.`, 'ok');
    } catch (e) {
      // Il segreto resta nel campo: l'utente corregge senza reincollarlo.
      if (bottone) bottone.disabled = false;
      say(e && e.message ? e.message : 'Collegamento non riuscito.', 'err');
    }
  }

  async function verifica() {
    say('Verifico con Zoom...');
    try {
      const esito = await api().zoomTest();
      say(`Zoom risponde: ${esito.email || 'ok'}.`, 'ok');
    } catch (e) {
      say(e && e.message ? e.message : 'Zoom non risponde.', 'err');
    }
  }

  async function scollega() {
    if (!confirm('Scollegare Zoom? Le video call confermate non avranno piu\' il link automatico.')) return;
    try {
      await api().zoomRemove();
      await render();
      say('Zoom scollegato.', 'ok');
    } catch (e) {
      say('Scollegamento non riuscito.', 'err');
    }
  }

  return { render, bodyHtml, connect };
})();

window.ZoomView = ZoomView;


function initZoom() {
  document.getElementById('btnAddZoom')?.addEventListener('click', () => {
    document.getElementById('imapOverlay')?.classList.add('hidden');
    document.getElementById('zoomOverlay')?.classList.remove('hidden');
    ZoomView.render();
  });
  document.getElementById('btnCloseZoom')?.addEventListener('click', () => {
    document.getElementById('zoomOverlay')?.classList.add('hidden');
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initZoom);
} else {
  initZoom();
}
