"""
calendar_router.py — Sceglie il backend del calendario.

Prima di questo modulo il calendario era cablato: server.py, l'API HTTP e
il ponte verso l'agente chiamavano ms_calendar direttamente, in nove punti.
Quello e' il vero motivo per cui il calendario Google non esisteva: non
mancava il codice per parlare con Google, mancava il posto dove metterlo.

Il router e' volutamente sottile. Non normalizza e non riformatta: e'
google_calendar che restituisce gia' eventi in forma Microsoft Graph, cosi'
availability.py, find_free_slots e la finestra della console non sanno
nemmeno quale provider hanno davanti.

Il default resta Microsoft. Vedi accounts.get_calendar_provider(): passare
a Google e' una scelta esplicita dell'utente, mai un effetto collaterale
del login.
"""

from typing import Dict, List

from . import accounts as core_accounts
from . import auth as ms_auth
from . import ms_calendar


class _CalendarioDemo:
    """L'account demo non ha un calendario collegato.

    Senza questo ramo il router cadeva su Microsoft e chiedeva un login
    che per un account finto non esiste mai: la finestra del calendario
    mostrava un errore di autenticazione. Zero eventi e' la verita', e in
    ripresa e' anche l'unica cosa presentabile."""

    @staticmethod
    def get_events(days_ahead: int = 7, days_back: int = 0) -> List[Dict]:
        return []

    @staticmethod
    def get_today_summary() -> str:
        return "Nessun calendario collegato."

    @staticmethod
    def _no(*_a, **_k):
        raise RuntimeError("L'account demo non ha un calendario collegato.")

    create_event = _no
    update_event = _no
    delete_event = _no


def provider() -> str:
    """'demo', 'google' o 'microsoft', per chi deve mostrarlo o spiegare
    un errore."""
    try:
        a = core_accounts.get_active_account()
        if a and a.get('type') == 'demo':
            return 'demo'
    except Exception:
        pass
    try:
        return core_accounts.get_calendar_provider()
    except Exception:
        return 'microsoft'


def _backend():
    p = provider()
    if p == 'demo':
        return _CalendarioDemo
    if p == 'google':
        from . import google_calendar
        return google_calendar
    account = _microsoft_primary()
    _select_microsoft(account)
    return ms_calendar


def _microsoft_primary():
    # Il contesto mail puo' appartenere a un'altra casella. Il calendario
    # usa sempre l'account primario scelto dall'utente (o il primo Microsoft
    # risolto da get_calendar_primary), anche nei thread del watcher.
    account_id = core_accounts.get_calendar_primary()
    account = (core_accounts.get_account_by_id(account_id)
               if account_id is not None else None)
    if (not account or account.get('type') != 'microsoft'
            or not str(account.get('email') or '').strip()):
        ms_auth.clear_current_account()
        raise ms_auth.AuthRequired(
            "Nessun account Microsoft valido per il calendario primario.")
    return account


def _select_microsoft(account):
    ms_auth.set_current_account(
        account['email'], account['id'],
        (account.get('data') or {}).get('token_cache'))


def capture_destination() -> Dict:
    """Serializable calendar identity for approval payloads, without tokens."""
    p = provider()
    if p == 'demo':
        return {'provider': 'demo'}
    if p == 'google':
        identity = core_accounts.get_google_identity() or {}
        email = str(identity.get('email') or '').strip().lower()
        if not email:
            raise ValueError('Nessuna identita Google per il calendario')
        return {'provider': 'google', 'email': email}
    account = _microsoft_primary()
    return {'provider': 'microsoft', 'account_id': account['id'],
            'email': account['email'].strip().lower()}


def bind_action(operation: str, destination: Dict = None):
    """Bind a captured destination, or capture one for an HTTP confirmation."""
    if operation not in ('create_event', 'update_event', 'delete_event'):
        raise ValueError('Operazione calendario non valida')
    target = capture_destination() if destination is None else dict(destination)
    p = target.get('provider')
    if p == 'demo':
        return getattr(_CalendarioDemo, operation)
    email = str(target.get('email') or '').strip().lower()
    if p not in ('google', 'microsoft') or not email:
        raise ValueError('Approvazione senza destinazione calendario fissata: '
                         'creare una nuova richiesta')
    if p == 'google':
        from . import google_calendar
        method = getattr(google_calendar, operation)

        def execute_google(**args):
            identity = core_accounts.get_google_identity(email) or {}
            if str(identity.get('email') or '').strip().lower() != email:
                raise ValueError('Identita Google approvata non piu disponibile')
            return method(**{**args, 'email': email, 'calendar_id': 'primary'})

        return execute_google
    account_id = target.get('account_id')
    if type(account_id) is not int:
        raise ValueError('Approvazione senza account calendario fissato')
    method = getattr(ms_calendar, operation)

    def execute(**args):
        account = core_accounts.get_account_by_id(account_id)
        if (not account or account.get('type') != 'microsoft'
                or str(account.get('email') or '').strip().lower() != email):
            raise ValueError('Account Microsoft approvato non piu disponibile')
        _select_microsoft(account)
        return method(**args)

    return execute


def get_events(days_ahead: int = 7, days_back: int = 0) -> List[Dict]:
    return _backend().get_events(days_ahead=days_ahead, days_back=days_back)


def create_event(subject: str, start: str, end: str,
                 location: str = '', body: str = '',
                 attendees: List[str] = None) -> Dict:
    return _backend().create_event(
        subject, start, end,
        location=location, body=body, attendees=attendees,
    )


def update_event(event_id: str, **kwargs) -> Dict:
    return _backend().update_event(event_id, **kwargs)


def delete_event(event_id: str) -> bool:
    return _backend().delete_event(event_id)


def get_today_summary() -> str:
    """Riassunto degli appuntamenti di oggi. Google non ha un equivalente
    dedicato, quindi lo si ricava dagli eventi: la logica sta in
    ms_calendar e vale per entrambi perche' la forma degli eventi e' la
    stessa."""
    backend = _backend()
    fn = getattr(backend, 'get_today_summary', None)
    if fn is not None:
        return fn()
    return _today_from(backend.get_events(days_ahead=1))


def _today_from(all_events: List[Dict]) -> str:
    from datetime import datetime
    today = datetime.now().date()
    events = []
    for e in all_events:
        raw = (e.get('start') or {}).get('dateTime') or ''
        try:
            if datetime.fromisoformat(raw[:19]).date() == today:
                events.append(e)
        except Exception:
            pass
    if not events:
        return 'Nessun appuntamento oggi.'
    righe = [f'Hai {len(events)} appuntamenti oggi:']
    for e in events:
        quando = (e['start']['dateTime'])[:16].replace('T', ' alle ')
        righe.append(f'- {e["subject"]} — {quando}')
    return '\n'.join(righe)
