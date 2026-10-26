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
  // Local translation helper: the unit tests load this file alone, without
  // the global T() from renderer_utils.js.
  const T = (key, it) => ((window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it);
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

  // Il link personale vale da solo: chi non vuole creare l'app Zoom incolla
  // qui il link della sua riunione personale e GigaMail lo mette nelle mail.
  function linkHtml(s) {
    const url = (s && s.link) || '';
    return `
      <div style="height:1px;background:rgba(0,0,0,0.08);margin:14px 0"></div>
      <p style="margin:0 0 8px;line-height:1.45">
        ${T('app_zoom_link_intro', "<b>Link personale</b> — l'alternativa all'app: un solo link, sempre lo stesso, che GigaMail mette nelle mail di conferma. Tieni accesa la sala d'attesa su Zoom.")}
      </p>
      <div class="field-row"><label class="field-label">${T('app_zoom_link_label', 'Link della tua riunione personale')}</label>
        <input type="text" id="zoomLink" class="field-input" autocomplete="off"
               placeholder="https://us02web.zoom.us/j/..." value="${esc(url)}"/></div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
        <button class="chip-btn" id="btnZoomLink">${T('app_zoom_save_link', 'Salva link')}</button>
      </div>`;
  }

  function bodyHtml(s) {
    if (s && s.configured) {
      return `
      <p style="margin:0 0 10px;line-height:1.45">
        ${T('app_zoom_connected_html', "Zoom e' <b>collegato</b> (Account ID {id}).").replace('{id}', () => esc(s.account_id))}
        ${T('app_zoom_flow', 'Quando un cliente conferma una video call, GigaMail crea la riunione e prepara la mail con il link, che parte solo dopo la tua approvazione.')}
      </p>
      <div style="display:flex;gap:8px">
        <button class="chip-btn" id="btnZoomTest">${T('app_zoom_test', 'Verifica')}</button>
        <button class="chip-btn" id="btnZoomRemove">${T('app_disconnect', 'Scollega')}</button>
      </div>
      ${linkHtml(s)}
      <div id="zoomStatus" class="hint" style="margin-top:10px"></div>`;
    }
    return `
      <p style="margin:0 0 10px;line-height:1.45">
        ${T('app_zoom_connect_intro', 'Collega il tuo account Zoom: quando un cliente conferma una video call, GigaMail crea la riunione e prepara la mail con il link, che parte solo dopo la tua approvazione.')}
      </p>
      <ol style="margin:0 0 12px;padding-left:18px;line-height:1.5;font-size:12px">
        <li>${T('app_zoom_step1', 'Su <b>marketplace.zoom.us</b> apri Develop &gt; Build App e scegli <b>Server-to-Server OAuth</b>.')}</li>
        <li>${T('app_zoom_step2', 'In Scopes aggiungi <code>meeting:write:meeting:admin</code>, <code>meeting:update:meeting:admin</code>, <code>meeting:delete:meeting:admin</code> e <code>user:read:user:admin</code>.')}</li>
        <li>${T('app_zoom_step3', "Attiva l'app e copia qui i tre codici.")}</li>
      </ol>
      <div class="field-row"><label class="field-label">Account ID</label>
        <input type="text" id="zoomAccountId" class="field-input" autocomplete="off"/></div>
      <div class="field-row"><label class="field-label">Client ID</label>
        <input type="text" id="zoomClientId" class="field-input" autocomplete="off"/></div>
      <div class="field-row"><label class="field-label">Client Secret</label>
        <input type="password" id="zoomClientSecret" class="field-input" autocomplete="off"/></div>
      <div style="display:flex;justify-content:flex-end;margin-top:10px">
        <button class="compose-btn" style="margin:0;width:auto;padding:8px 18px" id="btnZoomConnect">${T('app_zoom_connect', 'Collega Zoom')}</button>
      </div>
      ${linkHtml(s)}
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
      say(T('app_console_unreachable', 'Console non raggiungibile.'), 'err');
      return;
    }
    corpo.innerHTML = bodyHtml(s);
    el('btnZoomConnect')?.addEventListener('click', connect);
    el('btnZoomTest')?.addEventListener('click', verifica);
    el('btnZoomRemove')?.addEventListener('click', scollega);
    el('btnZoomLink')?.addEventListener('click', salvaLink);
  }

  async function connect() {
    const dati = {
      account_id: (el('zoomAccountId')?.value || '').trim(),
      client_id: (el('zoomClientId')?.value || '').trim(),
      client_secret: (el('zoomClientSecret')?.value || '').trim(),
    };
    if (!dati.account_id || !dati.client_id || !dati.client_secret) {
      say(T('app_zoom_need_three', 'Servono tutti e tre i codici.'), 'err');
      return;
    }
    const bottone = el('btnZoomConnect');
    if (bottone) bottone.disabled = true;
    say(T('app_zoom_checking', 'Verifico con Zoom...'));
    try {
      const esito = await api().zoomSetup(dati);
      await render();
      say(`${T('app_zoom_connected', 'Zoom collegato')}${esito.email ? `: ${esito.email}` : ''}.`, 'ok');
    } catch (e) {
      // Il segreto resta nel campo: l'utente corregge senza reincollarlo.
      if (bottone) bottone.disabled = false;
      say(e && e.message ? e.message : T('app_connect_failed', 'Collegamento non riuscito.'), 'err');
    }
  }

  async function salvaLink() {
    const url = (el('zoomLink')?.value || '').trim();
    say(url ? T('app_zoom_saving_link', 'Salvo il link...') : T('app_zoom_removing_link', 'Tolgo il link...'));
    try {
      await api().zoomLink(url);
      say(url ? T('app_zoom_link_saved', 'Link personale salvato: lo useremo nelle mail di conferma.')
              : T('app_zoom_link_removed', 'Link personale rimosso.'), 'ok');
    } catch (e) {
      say(e && e.message ? e.message : T('app_save_failed', 'Salvataggio non riuscito.'), 'err');
    }
  }

  async function verifica() {
    say(T('app_zoom_checking', 'Verifico con Zoom...'));
    try {
      const esito = await api().zoomTest();
      say(`${T('app_zoom_responds', 'Zoom risponde')}: ${esito.email || 'ok'}.`, 'ok');
    } catch (e) {
      say(e && e.message ? e.message : T('app_zoom_no_response', 'Zoom non risponde.'), 'err');
    }
  }

  async function scollega() {
    if (!(await GMDialog.confirm(T('app_zoom_confirm_disconnect', "Scollegare Zoom? Le video call confermate non avranno piu' il link automatico.")))) return;
    try {
      await api().zoomRemove();
      await render();
      say(T('app_zoom_disconnected', 'Zoom scollegato.'), 'ok');
    } catch (e) {
      say(T('app_disconnect_failed', 'Scollegamento non riuscito.'), 'err');
    }
  }

  return { render, bodyHtml, connect, salvaLink };
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
