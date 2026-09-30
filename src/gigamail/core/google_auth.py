"""
google_auth.py — OAuth2 Google per calendario e Drive.

Gemello di auth.py (Microsoft/MSAL), con due differenze deliberate:

1. Flusso loopback + PKCE, non device flow. Il device flow di Google
   ("TV and Limited-Input Devices") non copre gli scope di Calendar e
   Drive, quindi l'unica strada per un'app desktop e' il redirect su
   127.0.0.1 con porta effimera. Un client OAuth di tipo "Desktop app"
   accetta qualsiasi porta di loopback: non serve registrarle.

2. Nessuna libreria Google. Il flusso e' ~200 righe di requests, come
   ms_calendar.py parla a Graph in HTTP puro. Aggiungere google-auth,
   oauthlib e google-api-python-client complicherebbe il build PyInstaller
   in cambio di poco.

Il refresh token sta nel DB account cifrato (Fernet + DPAPI su Windows).
L'access token vive solo in memoria: dura un'ora, scriverlo su disco
sarebbe superficie di attacco gratuita.

Contratto identico ad auth.py: get_token() NON avvia mai flussi
interattivi, altrimenti dentro il server MCP bloccherebbe la richiesta.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional

import requests
from dotenv import load_dotenv

from .data_paths import token_path as _token_path

load_dotenv()
try:
    from .data_paths import env_path as _user_env_path
    load_dotenv(str(_user_env_path()))
except Exception:
    pass


def _load_google_config() -> dict:
    """Legge google_config.json accanto a questo file: identificativi del
    client OAuth desktop, nessun segreto reale. Fallback per la produzione,
    dove il .env di sviluppo non viene spedito."""
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'google_config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[GAUTH] google_config.json non leggibile: {e}")
    return {}


# -- IL JSON CHE SCARICA GOOGLE ----------------------------------------------
# Google, quando crei il client, offre un file gia' pronto con dentro id e
# secret. Farlo leggere direttamente elimina l'errore piu' facile da
# commettere e piu' difficile da vedere: ricopiare il secret del client
# sbagliato. Tutti i secret cominciano per GOCSPX- e hanno la stessa
# lunghezza, quindi due secret diversi sembrano identici a colpo d'occhio.

CLIENT_JSON_NAME = 'google_client_secret.json'


def client_json_path() -> Optional[str]:
    """Il file credenziali in uso, se c'e'. Nell'ordine: quello indicato da
    GOOGLE_CLIENT_SECRETS, quello installato con `gigamail google setup`,
    oppure un file scaricato da Google e lasciato nella cartella dati con
    il suo nome originale."""
    esplicito = (os.getenv('GOOGLE_CLIENT_SECRETS') or '').strip()
    if esplicito and os.path.isfile(esplicito):
        return esplicito
    try:
        from .data_paths import data_root
        radice = data_root()
    except Exception:
        return None
    fisso = radice / CLIENT_JSON_NAME
    if fisso.is_file():
        return str(fisso)
    # Il file come lo consegna Google, senza obbligare a rinominarlo.
    scaricati = sorted(radice.glob('client_secret_*.json'))
    return str(scaricati[0]) if scaricati else None


def leggi_client_json(path: str) -> dict:
    """-> {client_id, client_secret, project_id, tipo}. Solleva ValueError
    con un messaggio comprensibile se il file non e' quello giusto."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        raise ValueError(f"file non leggibile come JSON: {e}") from e

    if 'installed' in cfg:
        tipo, sez = 'installed', cfg['installed']
    elif 'web' in cfg:
        # Un client "Web application" non accetta il redirect di loopback:
        # fallirebbe al primo login con redirect_uri_mismatch. Meglio dirlo
        # adesso che dopo tre schermate di browser.
        raise ValueError(
            "questo e' un client di tipo 'Web application'. Serve un client "
            "'Desktop app': solo quello accetta il ritorno su 127.0.0.1."
        )
    else:
        raise ValueError(
            "non sembra il file credenziali di un client OAuth Google: "
            "manca la sezione 'installed'."
        )

    cid = (sez.get('client_id') or '').strip()
    sec = (sez.get('client_secret') or '').strip()
    if not cid or not sec:
        raise ValueError("il file non contiene client_id e client_secret.")
    return {'client_id': cid, 'client_secret': sec,
            'project_id': sez.get('project_id', ''), 'tipo': tipo}


def installa_client_json(src: str) -> dict:
    """Installa il file scaricato da Google nella cartella dati, dopo
    averlo validato. Copiare un file sbagliato e scoprirlo al primo login
    sarebbe la stessa trappola di prima, spostata di un passo."""
    import shutil

    info = leggi_client_json(src)
    from .data_paths import data_root
    dest = data_root() / CLIENT_JSON_NAME
    shutil.copyfile(src, dest)
    try:
        os.chmod(dest, 0o600)  # contiene un segreto: non e' un file qualsiasi
    except OSError:
        pass
    return {**info, 'path': str(dest)}


def _da_client_json() -> dict:
    path = client_json_path()
    if not path:
        return {}
    try:
        return leggi_client_json(path)
    except ValueError as e:
        print(f"[GAUTH] {os.path.basename(path)}: {e}")
        return {}


def _risolvi_credenziali():
    """-> (client_id, client_secret, provenienza).

    Le due meta' arrivano SEMPRE dalla stessa fonte. Prenderle da fonti
    diverse - id dalle variabili d'ambiente, secret dal JSON - produce una
    coppia che non esiste da nessuna parte, e Google risponde solo
    'invalid_client': l'id sembra giusto perche' lo e', il secret sembra
    giusto perche' ha la forma giusta, e non si capisce dove guardare.
    Una fonte incompleta viene scartata, non completata con un'altra.
    """
    env_id = (os.getenv('GOOGLE_CLIENT_ID') or '').strip()
    env_sec = (os.getenv('GOOGLE_CLIENT_SECRET') or '').strip()
    if env_id and env_sec:
        return env_id, env_sec, 'variabili di ambiente'
    if env_id or env_sec:
        print("[GAUTH] GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET vanno "
              "impostate insieme: coppia incompleta ignorata.")

    if _G_JSON.get('client_id') and _G_JSON.get('client_secret'):
        return (_G_JSON['client_id'], _G_JSON['client_secret'],
                f"file credenziali {os.path.basename(client_json_path() or '')}")

    if _G_CFG.get('client_id') and _G_CFG.get('client_secret'):
        return _G_CFG['client_id'], _G_CFG['client_secret'], 'google_config.json'

    return '', '', 'nessuna'


_G_CFG = _load_google_config()
_G_JSON = _da_client_json()

CLIENT_ID, CLIENT_SECRET, CREDENTIALS_SOURCE = _risolvi_credenziali()

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'

# Scope minimi. calendar.events copre la CRUD sugli eventi senza chiedere
# la gestione dei calendari. drive.file vede SOLO i file creati o aperti
# da GigaMail: e' non-sensitive, quindi evita la valutazione di sicurezza
# esterna che Google impone allo scope 'drive' completo.
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/drive.file',
]

_FLOW_PATH = str(_token_path('.google_login_flow.json'))

# Access token in memoria, per email: {'token': str, 'exp': epoch}
_access_cache: Dict[str, Dict] = {}
_cache_lock = threading.Lock()

# Contesto identita' corrente, come _current in auth.py
_current = {'email': None}


class AuthRequired(Exception):
    """Nessun token valido per l'identita' Google richiesta: serve un login
    esplicito (CLI `gigamail google login` o console). get_token NON avvia
    mai flussi interattivi da solo."""


class NotConfigured(Exception):
    """Il client OAuth Google non e' configurato: manca client_id. Finche'
    non c'e', nessun login e nessuna chiamata sono possibili."""


def is_configured() -> bool:
    return bool(CLIENT_ID)


def _require_config():
    if not CLIENT_ID:
        raise NotConfigured(
            "Client OAuth Google assente: ne GOOGLE_CLIENT_ID ne "
            "google_config.json. Crea un client 'Desktop app' nel progetto "
            "Google Cloud e riempi google_config.json."
        )


def set_current_identity(email: str = None):
    _current['email'] = (email or '').strip().lower() or None


# -- LOGIN: loopback + PKCE ---------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    """Riceve il redirect di Google una volta sola e chiude."""

    def do_GET(self):  # noqa: N802 (nome imposto da BaseHTTPRequestHandler)
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        code = (params.get('code') or [None])[0]
        state = (params.get('state') or [None])[0]
        error = (params.get('error') or [None])[0]

        # Il browser bussa piu' di una volta su questa porta: dopo il
        # redirect chiede /favicon.ico, senza parametri. Registrare anche
        # quella cancellerebbe il codice appena ricevuto e il login
        # morirebbe con "state non corrispondente", accusando di CSRF un
        # redirect legittimo. Si registra solo il primo redirect vero.
        if not code and not error:
            self.send_response(204)
            self.end_headers()
            return
        if getattr(self.server, 'oauth_result', None) is None:
            self.server.oauth_result = {'code': code, 'state': state, 'error': error}

        ok = code is not None
        # NON dire "collegato": qui e' arrivato solo il codice di Google, e
        # lo scambio con il token deve ancora avvenire. Una pagina che
        # annuncia il successo troppo presto manda l'utente a cercare il
        # problema dalla parte sbagliata quando lo scambio fallisce.
        body = (
            "<html><body style='font-family:system-ui;padding:3rem;text-align:center'>"
            + ("<h2>Autorizzazione ricevuta.</h2>"
               "<p>Torna a GigaMail: l'esito del collegamento e' scritto li'.</p>"
               if ok else
               "<h2>Accesso non riuscito.</h2><p>Torna a GigaMail e riprova.</p>")
            + "</body></html>"
        ).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # niente rumore sullo stdout: e' il trasporto MCP


_server_lock = threading.Lock()
_server: Optional[HTTPServer] = None


def get_login_url() -> dict:
    """Avvia il listener di loopback e ritorna l'URL da aprire nel browser.
    Gemello di auth.get_login_url(): non blocca, non attende."""
    _require_config()
    global _server

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip('=')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip('=')
    state = secrets.token_urlsafe(24)

    _shutdown_server()
    with _server_lock:
        # porta 0 = il sistema ne sceglie una libera. Un client OAuth
        # "Desktop app" accetta qualsiasi porta su 127.0.0.1.
        srv = HTTPServer(('127.0.0.1', 0), _CallbackHandler)
        srv.oauth_result = None
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        globals()['_server'] = srv
        port = srv.server_address[1]

    redirect_uri = f'http://127.0.0.1:{port}'
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'state': state,
        # offline + consent: senza questi Google non rilascia il refresh
        # token al secondo login, e l'accesso morirebbe dopo un'ora.
        'access_type': 'offline',
        'prompt': 'consent',
    }
    flow = {
        'state': state,
        'verifier': verifier,
        'redirect_uri': redirect_uri,
        'started_at': time.time(),
    }
    store_login_flow(flow)
    return {
        'auth_url': f'{AUTH_URL}?{urllib.parse.urlencode(params)}',
        'flow': flow,
    }


def complete_login(flow: dict = None) -> Optional[Dict]:
    """Completa il login DOPO che l'utente ha autorizzato nel browser.
    Non blocca: un solo controllo, come auth.complete_login. Ritorna
    {email, name} a login riuscito, None se il codice non e' ancora
    arrivato o l'utente ha annullato."""
    _require_config()
    flow = flow or load_login_flow()
    if not flow:
        return None

    with _server_lock:
        result = getattr(_server, 'oauth_result', None) if _server else None
    if not result:
        return None
    if result.get('error'):
        print(f"[GAUTH] login rifiutato: {result['error']}")
        _shutdown_server()
        clear_login_flow()
        return None
    if result.get('state') != flow.get('state'):
        # CSRF: il redirect non appartiene a questa richiesta.
        print('[GAUTH] state non corrispondente: redirect ignorato')
        _shutdown_server()
        clear_login_flow()
        return None

    payload = {
        'client_id': CLIENT_ID,
        'code': result['code'],
        'code_verifier': flow['verifier'],
        'grant_type': 'authorization_code',
        'redirect_uri': flow['redirect_uri'],
    }
    if CLIENT_SECRET:
        payload['client_secret'] = CLIENT_SECRET

    res = None
    try:
        res = requests.post(TOKEN_URL, data=payload, timeout=30)
        res.raise_for_status()
        tok = res.json()
    except Exception as e:
        # Google spiega il rifiuto nel CORPO della risposta, non nello
        # stato HTTP. Nasconderlo dietro un "401 Unauthorized" costringe
        # a indovinare fra secret sbagliato, client di un altro progetto
        # e codice gia' usato: sono errori diversi con rimedi diversi.
        print(f"[GAUTH] scambio codice fallito: {e}")
        print(f"[GAUTH] {spiega_errore_token(res)}")
        clear_login_flow()
        return None
    finally:
        _shutdown_server()

    refresh = tok.get('refresh_token')
    access = tok.get('access_token')
    if not refresh:
        # Senza refresh token l'accesso scadrebbe in un'ora. Meglio
        # fallire subito e chiaro che salvare un'identita' monca.
        print('[GAUTH] Google non ha rilasciato un refresh token: revoca '
              'l accesso a GigaMail dal tuo account Google e rifai il login.')
        clear_login_flow()
        return None

    email, name = _fetch_userinfo(access)
    if not email:
        print('[GAUTH] impossibile leggere l identita: login annullato')
        clear_login_flow()
        return None

    from . import accounts as _acc
    _acc.save_google_identity(email, name, {
        'refresh_token': refresh,
        'scopes': tok.get('scope', ' '.join(SCOPES)),
    })
    _cache_access(email, access, tok.get('expires_in', 3600))
    set_current_identity(email)
    clear_login_flow()
    return {'email': email, 'name': name}


_RIMEDI = {
    'invalid_client': (
        "Google non riconosce la coppia client_id / client_secret. Di "
        "norma il secret appartiene a un client diverso da quello "
        "dell'id, oppure manca del tutto. Riprendili entrambi dalla "
        "stessa scheda del client desktop nel progetto giusto."
    ),
    'invalid_grant': (
        "Il codice di autorizzazione e' scaduto o gia' usato: rifai il "
        "login da capo."
    ),
    'redirect_uri_mismatch': (
        "L'indirizzo di ritorno non e' accettato: il client OAuth deve "
        "essere di tipo 'Desktop app', non 'Web application'."
    ),
    'invalid_scope': (
        "Uno degli scope richiesti non e' abilitato sul progetto: "
        "controlla che le API Calendar e Drive siano attive."
    ),
}


class ApiError(Exception):
    """Errore di una API Google, con dentro la spiegazione che Google ha
    davvero mandato. `raise_for_status()` da solo produce '403 Forbidden',
    che non dice se manchi un permesso, se l'API sia spenta sul progetto o
    se la quota sia esaurita: tre problemi con tre rimedi diversi."""


def check(res):
    """Come raise_for_status, ma non butta via il corpo della risposta."""
    if res.ok:
        return res
    try:
        err = res.json().get('error', {})
    except Exception:
        raise ApiError(f"HTTP {res.status_code}: {str(res.text)[:300]}") from None

    messaggio = err.get('message') or f"HTTP {res.status_code}"
    motivi = {d.get('reason') for d in (err.get('details') or []) if d.get('reason')}
    if 'SERVICE_DISABLED' in motivi:
        messaggio += (" | RIMEDIO: l'API non e' attiva su questo progetto "
                      "Google Cloud. Abilitala dal link qui sopra e riprova "
                      "fra qualche minuto.")
    elif res.status_code == 401:
        messaggio += " | RIMEDIO: accesso scaduto o revocato, rifai il login Google."
    raise ApiError(messaggio)


def spiega_errore_token(res) -> str:
    """Traduce il corpo della risposta di Google in un rimedio. Senza
    questo l'utente vede solo un numero e non sa da che parte guardare."""
    if res is None:
        return "Nessuna risposta da Google: probabile problema di rete."
    try:
        corpo = res.json()
    except Exception:
        return f"Risposta non interpretabile: {str(res.text)[:200]}"
    codice = corpo.get('error') or '(senza codice)'
    dettaglio = corpo.get('error_description') or ''
    rimedio = _RIMEDI.get(codice, "Causa non catalogata: vedi il codice qui sopra.")
    return f"Google dice '{codice}' ({dettaglio}). {rimedio}"


def _shutdown_server():
    with _server_lock:
        srv = globals().get('_server')
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
            globals()['_server'] = None


def _fetch_userinfo(access_token: str):
    try:
        r = requests.get(USERINFO_URL, timeout=20,
                         headers={'Authorization': f'Bearer {access_token}'})
        r.raise_for_status()
        d = r.json()
        return (d.get('email') or '').strip().lower(), d.get('name') or ''
    except Exception as e:
        print(f"[GAUTH] userinfo fallita: {e}")
        return '', ''


# -- TOKEN --------------------------------------------------------------------

def _cache_access(email: str, token: str, expires_in: int):
    with _cache_lock:
        # 60s di margine: meglio un refresh in piu' che una chiamata che
        # muore a meta' per un token scaduto un attimo prima.
        _access_cache[email] = {
            'token': token,
            'exp': time.time() + max(0, int(expires_in) - 60),
        }


def get_token(email: str = None) -> str:
    """Access token valido per l'identita' Google indicata (o la primaria).
    Solo acquisizione silenziosa via refresh token: mai flussi interattivi."""
    _require_config()
    from . import accounts as _acc

    ident = _acc.get_google_identity(email or _current['email'])
    if not ident:
        raise AuthRequired(
            'Nessuna identita Google collegata: esegui il login '
            '(CLI: gigamail google login, oppure dalla console).'
        )
    mail = ident['email']

    with _cache_lock:
        hit = _access_cache.get(mail)
        if hit and hit['exp'] > time.time():
            return hit['token']

    refresh = (ident.get('data') or {}).get('refresh_token')
    if not refresh:
        raise AuthRequired(f'Refresh token assente per {mail}: rifai il login.')

    payload = {
        'client_id': CLIENT_ID,
        'refresh_token': refresh,
        'grant_type': 'refresh_token',
    }
    if CLIENT_SECRET:
        payload['client_secret'] = CLIENT_SECRET
    try:
        res = requests.post(TOKEN_URL, data=payload, timeout=30)
        res.raise_for_status()
        tok = res.json()
    except Exception as e:
        # invalid_grant = l'utente ha revocato l'accesso, o il token e'
        # scaduto per inattivita'. Non e' un errore di rete: va rifatto
        # il login, e dirlo chiaro evita ritentativi inutili dell'agente.
        raise AuthRequired(
            f'Refresh del token Google fallito per {mail} ({e}). '
            'Probabilmente l accesso e stato revocato: rifai il login.'
        ) from e

    access = tok.get('access_token')
    if not access:
        raise AuthRequired(f'Google non ha restituito un access token per {mail}.')
    _cache_access(mail, access, tok.get('expires_in', 3600))
    return access


def auth_headers(email: str = None) -> dict:
    return {
        'Authorization': f'Bearer {get_token(email)}',
        'Content-Type': 'application/json',
    }


def is_logged_in() -> bool:
    """C'e' almeno un'identita' Google utilizzabile."""
    if not CLIENT_ID:
        return False
    try:
        from . import accounts as _acc
        ident = _acc.get_google_identity()
        if not ident:
            return False
        get_token(ident['email'])
        return True
    except Exception:
        return False


def logout(email: str = None) -> bool:
    """Revoca il refresh token presso Google e cancella l'identita' locale.
    La revoca remota e' best effort: se la rete manca, il dato locale
    sparisce comunque, che e' la parte che conta per l'utente."""
    from . import accounts as _acc
    ident = _acc.get_google_identity(email)
    if not ident:
        return False
    mail = ident['email']
    refresh = (ident.get('data') or {}).get('refresh_token')
    if refresh:
        try:
            requests.post(REVOKE_URL, data={'token': refresh}, timeout=20)
        except Exception as e:
            print(f"[GAUTH] revoca remota fallita per {mail}: {e}")
    with _cache_lock:
        _access_cache.pop(mail, None)
    return _acc.delete_google_identity(mail)


# -- FLOW PERSISTENTE ---------------------------------------------------------
# Come in auth.py: tra start e complete il backend puo' riavviarsi o
# cambiare worker, quindi il flow in corso vive su disco.

def store_login_flow(flow: dict) -> None:
    try:
        with open(_FLOW_PATH, 'w', encoding='utf-8') as f:
            json.dump(flow, f)
    except Exception as e:
        print(f"[GAUTH] store_login_flow error: {e}")


def load_login_flow() -> dict:
    try:
        if not os.path.exists(_FLOW_PATH):
            return {}
        with open(_FLOW_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[GAUTH] load_login_flow error: {e}")
        return {}


def clear_login_flow() -> None:
    try:
        if os.path.exists(_FLOW_PATH):
            os.remove(_FLOW_PATH)
    except Exception as e:
        print(f"[GAUTH] clear_login_flow error: {e}")
