/* renderer_google.js — Collegamento Google: calendario e Drive.
 *
 * Volutamente separato dal bottone "Gmail / Google" della schermata
 * account: quello aggiunge una CASELLA DI POSTA via IMAP con password per
 * le app, questo autorizza CALENDARIO e FILE via OAuth. Sono due cose
 * diverse e l'utente deve poterle distinguere, altrimenti collega la
 * posta e si chiede perche' il calendario resta vuoto.
 */

const GoogleView = (() => {

  const api = () => window.ademail;
  const el = (id) => document.getElementById(id);
  // Local translation helper, so the module also works loaded on its own.
  const T = (key, it) => ((window.i18n && window.i18n.t) ? window.i18n.t(key, it) : it);

  let pollTimer = null;

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function say(msg, tone) {
    const box = el('googleStatus');
    if (!box) return;
    const colore = tone === 'err' ? 'rgba(180,40,30,0.85)'
                 : tone === 'ok' ? 'rgba(20,130,70,0.9)'
                 : 'var(--muted, #666)';
    box.innerHTML = `<span style="color:${colore}">${msg}</span>`;
  }

  async function render() {
    let s;
    try {
      s = await api().googleStatus();
    } catch (e) {
      say(T('app_console_unreachable', 'Console non raggiungibile.'), 'err');
      return;
    }

    const corpo = el('googleBody');
    if (!corpo) return;

    if (!s.configured) {
      // Build senza progetto Google Cloud: dirlo, invece di mostrare un
      // bottone che fallisce.
      corpo.innerHTML = `
        <p style="margin:0 0 8px">${T('app_google_unavailable', "Google non e' disponibile in questa versione di GigaMail: manca il client OAuth.")}</p>`;
      return;
    }

    const righe = (s.identities || []).map(i => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0">
        <span style="flex:1">${i.email}</span>
        <button class="chip-btn" data-google-logout="${i.email}">${T('app_disconnect', 'Scollega')}</button>
      </div>`).join('');

    corpo.innerHTML = `
      <p style="margin:0 0 10px;line-height:1.45">
        ${T('app_google_intro', 'Autorizza GigaMail a leggere e scrivere il tuo <b>calendario</b> e a gestire i <b>file che crea lui</b> su Drive. Non tocca la posta: per collegare Gmail usa "Aggiungi account".')}
      </p>
      ${s.connected ? righe : '<p style="margin:0 0 10px">' + T('app_google_none', 'Nessun account Google collegato.') + '</p>'}
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="chip-btn" id="btnGoogleConnect">
          ${s.connected ? T('app_google_connect_another', 'Collega un altro account') : T('app_google_connect', 'Collega Google')}
        </button>
      </div>
      <div style="height:1px;background:rgba(0,0,0,0.08);margin:14px 0"></div>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="flex:1">${T('app_calendar_served_by', 'Calendario servito da')}</span>
        <select id="googleCalProvider" class="field-input" style="width:auto">
          <option value="microsoft" ${s.calendar_provider === 'microsoft' ? 'selected' : ''}>Microsoft</option>
          <option value="google" ${s.calendar_provider === 'google' ? 'selected' : ''}>Google</option>
        </select>
      </div>
      <p style="margin:8px 0 0;font-size:11px;opacity:0.7">
        ${T('app_google_calendar_hint', "Collegare Google non sposta il calendario da solo: la scelta e' questa qui.")}
      </p>
      <div id="googleStatus" class="hint" style="margin-top:10px"></div>`;

    el('btnGoogleConnect')?.addEventListener('click', connect);
    el('googleCalProvider')?.addEventListener('change', cambiaProvider);
    corpo.querySelectorAll('[data-google-logout]').forEach(b => {
      b.addEventListener('click', () => scollega(b.dataset.googleLogout));
    });
  }

  async function connect() {
    stopPoll();
    let dati;
    try {
      dati = await api().googleLogin();
    } catch (e) {
      say(T('app_google_login_start_failed', 'Impossibile avviare il login Google.'), 'err');
      return;
    }
    window.open(dati.auth_url, '_blank');
    say(T('app_authorize_in_browser', 'Autorizza nel browser, poi torna qui...'));

    // Il redirect arriva a un listener locale nel backend: qui si chiede
    // solo se e' gia' arrivato. Niente attesa bloccante.
    let tentativi = 0;
    pollTimer = setInterval(async () => {
      tentativi += 1;
      if (tentativi > 150) {           // 2 min e mezzo
        stopPoll();
        say(T('app_auth_timeout', 'Tempo scaduto: nessuna autorizzazione ricevuta.'), 'err');
        return;
      }
      try {
        const esito = await api().googleComplete();
        if (esito.status === 'ok') {
          stopPoll();
          await render();
          say(`${T('app_connected', 'Collegato')}: ${esito.email}`, 'ok');
        }
      } catch (e) {
        stopPoll();
        say(T('app_login_failed', 'Login non riuscito.'), 'err');
      }
    }, 1000);
  }

  async function scollega(email) {
    if (!(await GMDialog.confirm(T('app_google_confirm_disconnect', 'Scollegare {email}? Il token viene revocato presso Google.').replace('{email}', () => email)))) return;
    try {
      await api().googleLogout(email);
      await render();
      say(T('app_account_disconnected', 'Account scollegato.'), 'ok');
    } catch (e) {
      say(T('app_disconnect_failed', 'Scollegamento non riuscito.'), 'err');
    }
  }

  async function cambiaProvider(e) {
    try {
      const r = await api().setCalendarProvider(e.target.value);
      say(T('app_calendar_now_on', 'Calendario ora su {provider}.').replace('{provider}', () => r.provider), 'ok');
    } catch (err) {
      say(T('app_calendar_switch_failed', "Cambio non riuscito: controlla che l'account sia collegato."), 'err');
      await render();
    }
  }

  return { render, stopPoll };
})();


function initGoogle() {
  const apri = document.getElementById('btnAddGoogleServices');
  if (apri) {
    apri.addEventListener('click', () => {
      document.getElementById('imapOverlay')?.classList.add('hidden');
      document.getElementById('googleOverlay')?.classList.remove('hidden');
      GoogleView.render();
    });
  }
  document.getElementById('btnCloseGoogle')?.addEventListener('click', () => {
    GoogleView.stopPoll();
    document.getElementById('googleOverlay')?.classList.add('hidden');
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initGoogle);
} else {
  initGoogle();
}
