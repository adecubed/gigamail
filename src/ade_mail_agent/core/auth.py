"""
auth.py — Microsoft Graph OAuth2 via MSAL.
Gestisce login, token refresh, persistenza token in locale.
"""

import os
import json
import msal
from dotenv import load_dotenv

from data_paths import token_path as _token_path

load_dotenv()
try:
    from data_paths import env_path as _user_env_path
    load_dotenv(str(_user_env_path()))
except Exception:
    pass


def _load_ms_config() -> dict:
    """
    Legge ms_config.json accanto a questo file. Contiene SOLO identificatori
    pubblici dell'app Azure (client_id, tenant_id, redirect_uri) - nessun segreto.
    Serve come fallback in produzione, dove il .env (con i segreti dev) non viene
    spedito. In sviluppo le variabili del .env hanno comunque la precedenza.
    """
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ms_config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[AUTH] ms_config.json non leggibile: {e}")
    return {}


_MS_CFG = _load_ms_config()

# Precedenza: variabile d'ambiente (.env, dev) -> ms_config.json (prod) -> default
CLIENT_ID     = os.getenv('MS_CLIENT_ID')     or _MS_CFG.get('client_id')
CLIENT_SECRET = os.getenv('MS_CLIENT_SECRET')  # solo dev/confidential; device flow non lo usa
TENANT_ID     = os.getenv('MS_TENANT_ID')     or _MS_CFG.get('tenant_id')    or 'common'
REDIRECT_URI  = os.getenv('MS_REDIRECT_URI')  or _MS_CFG.get('redirect_uri') or 'http://localhost'

if not CLIENT_ID:
    print("[AUTH] ATTENZIONE: CLIENT_ID assente (né MS_CLIENT_ID né ms_config.json) — il login Microsoft fallira con 400")
TOKEN_PATH = str(_token_path('.token_cache.json'))

SCOPES = [
    'Mail.Read',
    'Mail.Send',
    'Mail.ReadWrite',
    'Calendars.ReadWrite',
    'Files.ReadWrite',
    'User.Read',
]

AUTHORITY = f'https://login.microsoftonline.com/{TENANT_ID}'


def _get_app() -> msal.PublicClientApplication:
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'r') as f:
            cache.deserialize(f.read())

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        token_cache=cache,
    )
    return app, cache


def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        with open(TOKEN_PATH, 'w') as f:
            f.write(cache.serialize())


def get_token() -> str:
    """Ritorna access token valido. Usa cache se disponibile."""
    app, cache = _get_app()

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        _save_cache(cache)
        if result and 'access_token' in result:
            return result['access_token']

    # Nessun token in cache — device flow login
    flow = app.initiate_device_flow(scopes=SCOPES)
    if 'user_code' not in flow:
        raise Exception(f'[AUTH] Device flow fallito: {flow}')

    print(f'\n[AUTH] Vai su: {flow["verification_uri"]}')
    print(f'[AUTH] Inserisci il codice: {flow["user_code"]}\n')

    result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache)

    if 'access_token' not in result:
        raise Exception(f'[AUTH] Login fallito: {result.get("error_description")}')

    print('[AUTH] Login completato.')
    return result['access_token']


def get_login_url() -> dict:
    """Ritorna url e user_code per il device flow — usato dalla console."""
    app, _ = _get_app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    return {
        'verification_uri': flow.get('verification_uri'),
        'user_code': flow.get('user_code'),
        'message': flow.get('message'),
        'flow': flow,
    }


def complete_login(flow: dict) -> bool:
    """
    Completa il device flow DOPO che l'utente ha autorizzato nel browser.
    NON deve bloccare: l'utente ha gia inserito il codice, quindi facciamo
    un solo controllo non-bloccante invece del polling infinito di
    acquire_token_by_device_flow (che altrimenti occupa il worker e martella
    Microsoft con "Attempted too soon" -> 400 in loop).
    """
    import time
    app, cache = _get_app()

    # NON rimuovere expires_in/interval: MSAL li usa per il timing del polling.
    # Rispetta l'intervallo minimo richiesto da Microsoft prima di interrogare.
    try:
        interval = int(flow.get('interval', 5))
    except Exception:
        interval = 5
    time.sleep(min(interval, 5))

    # exit_condition fa uscire dopo UN giro: se l'utente ha gia autorizzato
    # il token c'e subito; altrimenti esce senza bloccare il backend.
    try:
        result = app.acquire_token_by_device_flow(
            flow,
            exit_condition=lambda f: True,
        )
    except Exception as e:
        print(f"[AUTH] complete_login eccezione: {e}")
        return False

    _save_cache(cache)
    if 'access_token' not in result:
        print(f"[AUTH] complete_login: token non ancora pronto — "
              f"{result.get('error')} — {result.get('error_description')}")
    return 'access_token' in result


def is_logged_in() -> bool:
    """Verifica se c'è un token valido in cache."""
    try:
        app, cache = _get_app()
        accounts = app.get_accounts()
        if not accounts:
            return False
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        return result is not None and 'access_token' in result
    except Exception:
        return False


def logout():
    """Rimuove il token cache."""
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
        print('[AUTH] Logout completato.')

def store_login_flow(flow: dict) -> None:
    """Salva il device flow in corso su disco. Serve a /auth/complete:
    tra start e complete il backend può riavviarsi o cambiare worker."""
    try:
        path = str(_token_path('.ms_login_flow.json'))
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(flow, f)
    except Exception as e:
        print(f"[AUTH] store_login_flow error: {e}")

def load_login_flow() -> dict:
    try:
        path = str(_token_path('.ms_login_flow.json'))
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[AUTH] load_login_flow error: {e}")
        return {}

def clear_login_flow() -> None:
    try:
        path = str(_token_path('.ms_login_flow.json'))
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"[AUTH] clear_login_flow error: {e}")