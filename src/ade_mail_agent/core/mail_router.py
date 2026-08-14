"""
mail_router.py — Router che indirizza le chiamate mail/calendar
al backend corretto (Microsoft Graph o IMAP) in base all'account attivo.
Microsoft → usa auth.py (token cache MSAL)
IMAP      → usa email + password cifrata in accounts.py
Calendar  → Google Calendar via OAuth2 (calendar_client.py)
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import accounts as acc
import mail as ms_mail
import imap_client as imap
try:
    import calendar_client as gcal
    _GCAL_OK = True
except ImportError:
    _GCAL_OK = False
def _account(account_id=None):
    """
    Risolve l'account corretto.
    Accetta: int (id), dict (oggetto account), None (usa attivo).
    """
    if account_id is not None:
        # Se è già un dict account, restituiscilo direttamente
        if isinstance(account_id, dict):
            return account_id
        # Normalizza a int
        try:
            aid = int(account_id)
        except (TypeError, ValueError):
            return acc.get_active_account()
        # Id esplicito: se non esiste NON ripiegare sull'account attivo —
        # un chiamante (specie un agente) che chiede l'account X non deve
        # mai ricevere silenziosamente i dati di un altro account.
        return acc.get_account_by_id(aid)
    return acc.get_active_account()
def _is_microsoft(account_id=None) -> bool:
    a = _account(account_id)
    if not a:
        return False
    return a.get('type', 'microsoft') == 'microsoft'
def _imap_credentials(a: dict) -> tuple:
    """Estrae credenziali IMAP/SMTP da un oggetto account."""
    d = a.get('data', a)
    return (
        d.get('imap_host', a.get('imap_host', '')),
        d.get('imap_port', a.get('imap_port', 993)),
        a.get('email', ''),
        d.get('password', a.get('password', '')),
    )
def _smtp_credentials(a: dict) -> tuple:
    """Estrae credenziali SMTP da un oggetto account."""
    d = a.get('data', a)
    return (
        d.get('smtp_host', a.get('smtp_host', '')),
        d.get('smtp_port', a.get('smtp_port', 465)),
        a.get('email', ''),
        d.get('password', a.get('password', '')),
    )


def _normalize_send_result(result) -> Dict:
    if isinstance(result, dict):
        return {
            'success': bool(result.get('success')),
            'provider': result.get('provider'),
            'sent_copy_saved': bool(result.get('sent_copy_saved', result.get('success'))),
            'warning': result.get('warning'),
            'error': result.get('error'),
        }
    ok = bool(result)
    return {
        'success': ok,
        'provider': None,
        'sent_copy_saved': ok,
        'warning': None,
        'error': None,
    }
# ── MAIL ──────────────────────────────────────────────────────────────────────
def get_messages(
    account_id=None,
    folder: str = 'inbox',
    top: int = 20,
    skip: int = 0,
    priority: bool = False,
) -> List[Dict]:
    a = _account(account_id)
    if not a:
        return []
    f = (folder or 'inbox').lower()
    # Microsoft Graph
    if a.get('type', 'microsoft') == 'microsoft':
        if f in ('inbox',):
            target = 'inbox'
        elif f in ('deleteditems', 'trash', 'cestino', 'deleted'):
            target = 'deleteditems'
        elif f in ('junkemail', 'spam', 'postaindesiderata', 'posta_indesiderata', 'junk'):
            target = 'junkemail'
        elif f in ('sentitems', 'sent', 'postainviata', 'posta_inviata'):
            target = 'sentitems'
        elif f in ('draft', 'drafts', 'bozze'):
            target = 'drafts'
        else:
            target = folder
        if priority:
            return ms_mail.get_priority_messages(top=top)
        return ms_mail.get_messages(folder=target, top=top, skip=skip)
    # IMAP
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    # Normalizza nomi cartella stile Graph → alias IMAP usati da imap_client._resolve_folder
    if f in ('inbox',):
        target = 'INBOX'
    elif f in ('deleteditems', 'trash', 'cestino', 'deleted'):
        target = 'trash'
    elif f in ('junkemail', 'spam', 'postaindesiderata', 'posta_indesiderata'):
        target = 'junk'
    elif f in ('sentitems', 'sent', 'postainviata', 'posta_inviata'):
        target = 'sent'
    else:
        target = folder
    return imap.get_messages(
        imap_host,
        imap_port,
        email_addr,
        password,
        folder=target,
        top=top,
    )
def get_message(account_id=None, message_id: str = '', folder: str = '') -> Dict:
    a = _account(account_id)
    if not a:
        return {}
    if a.get('type', 'microsoft') == 'microsoft':
        # Guardia: se l'ID è puramente numerico è un UID IMAP — non appartiene a questo account
        if str(message_id).isdigit():
            raise ValueError(f"ID numerico '{message_id}' non valido per account Microsoft (account_id={account_id})")
        return ms_mail.get_message(message_id)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.get_message(imap_host, imap_port, email_addr, password, message_id, folder=folder or "INBOX")
def send_message(
    account_id=None,
    to: str = '',
    subject: str = '',
    body: str = '',
    reply_to_id: str = None,
    attachments: list = None,
    cc: list = None,
    bcc: list = None,
) -> Dict:
    a = _account(account_id)
    if not a:
        return {
            'success': False,
            'provider': None,
            'sent_copy_saved': False,
            'warning': None,
            'error': 'Account non trovato',
        }
    if a.get('type', 'microsoft') == 'microsoft':
        return _normalize_send_result(ms_mail.send_message(
            to,
            subject,
            body,
            reply_to_id=reply_to_id,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        ))
    imap_host, imap_port, _, imap_password = _imap_credentials(a)
    smtp_host, smtp_port, email_addr, password = _smtp_credentials(a)
    return _normalize_send_result(imap.send_message(
        smtp_host,
        smtp_port,
        email_addr,
        password,
        to,
        subject,
        body,
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        imap_host=imap_host,
        imap_port=imap_port,
        imap_password=imap_password,
    ))
def reply_message(account_id=None, message_id: str = '', body: str = '') -> bool:
    """
    Risponde a una mail esistente.
    Recupera mittente e oggetto originale, poi invia la risposta
    con il reply_to_id impostato (thread corretto su Microsoft).
    """
    a = _account(account_id)
    if not a:
        return False
    msg = get_message(account_id, message_id)
    if not msg:
        return False
    # Estrai mittente originale
    from_field = msg.get('from', {})
    if isinstance(from_field, dict):
        to_addr = from_field.get('emailAddress', {}).get('address', '')
        if not to_addr:
            to_addr = from_field.get('address', '')
    else:
        to_addr = str(from_field)
    original_subject = msg.get('subject', '')
    if original_subject.lower().startswith('re:'):
        reply_subject = original_subject
    else:
        reply_subject = f"Re: {original_subject}"
    result = send_message(
        account_id=account_id,
        to=to_addr,
        subject=reply_subject,
        body=body,
        reply_to_id=message_id,
    )
    return bool(result.get('success')) if isinstance(result, dict) else bool(result)

def get_priority_messages(account_id=None, top: int = 20) -> List[Dict]:
    a = _account(account_id)
    if not a:
        return []
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.get_priority_messages(top=top)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.get_messages(imap_host, imap_port, email_addr, password, top=top)

def search_messages(account_id=None, query: str = '', top: int = 10) -> List[Dict]:
    a = _account(account_id)
    if not a:
        return []
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.search_messages(query, top=top)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.search_messages(
        imap_host,
        imap_port,
        email_addr,
        password,
        query,
        top=top,
    )

def set_read_status(account_id=None, message_id: str = '', folder: str = 'inbox', is_read: bool = True) -> bool:
    a = _account(account_id)
    if not a:
        return False
    if a.get('type', 'microsoft') == 'microsoft':
        try:
            ms_mail.set_read_status(message_id, is_read)
            return True
        except Exception as e:
            print(f"[mail_router set_read_status] ms error: {e}")
            return False
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    target = 'INBOX' if folder.lower() == 'inbox' else folder
    return imap.set_read_status(imap_host, imap_port, email_addr, password, message_id, target, is_read)


def _message_datetime(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except Exception:
            continue
    try:
        dt = parsedate_to_datetime(raw)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None
    
def get_all_uids(account_id=None, folder: str = 'inbox') -> List[str]:
    """Ritorna tutti gli UID IMAP di una cartella. Solo per account IMAP."""
    a = _account(account_id)
    if not a or a.get('type', 'microsoft') == 'microsoft':
        return []
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    target = folder if folder not in ('inbox',) else 'INBOX'
    return imap.get_all_uids(imap_host, imap_port, email_addr, password, folder=target)


def fetch_messages_by_uids(account_id=None, uids: List[str] = None, folder: str = 'inbox') -> List[Dict]:
    """Fetcha mail per lista UID. Solo per account IMAP."""
    a = _account(account_id)
    if not a or a.get('type', 'microsoft') == 'microsoft':
        return []
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    target = folder if folder not in ('inbox',) else 'INBOX'
    return imap.fetch_messages_by_uids(imap_host, imap_port, email_addr, password, uids or [], folder=target)


def get_unread_messages(
    account_id=None,
    folder: str = 'inbox',
    top: int = 20,
    days: int = 5,
) -> List[Dict]:
    sample_top = max(int(top or 20) * 5, 50)
    source = get_messages(account_id=account_id, folder=folder, top=sample_top)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(int(days or 5), 1))
    filtered: List[Dict] = []
    for msg in source:
        if not isinstance(msg, dict):
            continue
        if bool(msg.get('isRead')):
            continue
        msg_dt = _message_datetime(str(msg.get('receivedDateTime') or ''))
        if msg_dt is None or msg_dt >= cutoff:
            filtered.append(msg)
    filtered.sort(
        key=lambda item: _message_datetime(str(item.get('receivedDateTime') or '')) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return filtered[: max(int(top or 20), 1)]


def move_to_folder(account_id=None, message_id: str = '', folder_id: str = '', source_folder: str = None) -> bool:
    a = _account(account_id)
    if not a:
        return False
    f = (folder_id or '').lower()
    if f in ('inbox', 'posta_in_arrivo', 'postainarrivo'):
        normalized = 'inbox'
    elif f in ('deleteditems', 'trash', 'cestino', 'deleted'):
        normalized = 'deleteditems'
    elif f in ('junkemail', 'spam', 'postaindesiderata', 'posta_indesiderata', 'junk'):
        normalized = 'junkemail'
    elif f in ('sentitems', 'sent', 'postainviata', 'posta_inviata'):
        normalized = 'sentitems'
    elif f in ('draft', 'drafts', 'bozze'):
        normalized = 'drafts'
    else:
        normalized = folder_id
    # Microsoft Graph
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.move_to_folder(message_id, normalized)
    # IMAP
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    if f in ('inbox', 'posta_in_arrivo', 'postainarrivo'):
        dest = 'INBOX'
    elif f in ('deleteditems', 'trash', 'cestino'):
        dest = 'trash'
    elif f in ('junkemail', 'spam', 'postaindesiderata', 'posta_indesiderata'):
        dest = 'junk'
    elif f in ('sentitems', 'sent', 'postainviata', 'posta_inviata'):
        dest = 'sent'
    else:
        dest = folder_id
    # Se source_folder non passato e stiamo muovendo verso inbox, assumiamo venga da junk
    effective_source = source_folder
    if not effective_source and f in ('inbox', 'posta_in_arrivo', 'postainarrivo'):
        effective_source = 'junk'
    return imap.move_to_folder(
        imap_host,
        imap_port,
        email_addr,
        password,
        message_id,
        folder=dest,
        source_folder=effective_source,
    )

def list_folders(account_id=None) -> List[Dict]:
    a = _account(account_id)
    if not a:
        return []
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.list_folders()
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.list_folders(imap_host, imap_port, email_addr, password)

def create_folder(account_id=None, name: str = '') -> Dict:
    a = _account(account_id)
    if not a:
        return {}
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.create_folder(name)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.create_folder(imap_host, imap_port, email_addr, password, name)

def delete_folder(account_id=None, folder_id: str = '') -> bool:
    a = _account(account_id)
    if not a:
        return False
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.delete_folder(folder_id)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.delete_folder(imap_host, imap_port, email_addr, password, folder_id)

def delete_message(account_id=None, message_id: str = '', folder: str = None) -> bool:
    a = _account(account_id)
    if not a:
        return False
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.delete_message(message_id)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.delete_message(
        imap_host,
        imap_port,
        email_addr,
        password,
        message_id,
        folder=folder,
    )
def get_attachment(account_id=None, message_id: str = '', filename: str = '', folder: str = '') -> tuple:
    a = _account(account_id)
    if not a:
        raise ValueError('Account non trovato')
    if a.get('type', 'microsoft') == 'microsoft':
        return ms_mail.get_attachment(message_id, filename)
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    return imap.get_attachment(
        imap_host,
        imap_port,
        email_addr,
        password,
        message_id,
        filename,
        folder=folder or "INBOX",
    )


def debug_imap_folders(account_id=None) -> Dict:
    a = _account(account_id)
    if not a:
        return {}
    if a.get('type', 'microsoft') == 'microsoft':
        return {
            'type': 'microsoft',
            'note': 'Debug cartelle IMAP non applicabile agli account Microsoft Graph',
        }
    imap_host, imap_port, email_addr, password = _imap_credentials(a)
    result = imap.debug_folders(imap_host, imap_port, email_addr, password)
    result['account'] = {
        'id': a.get('id'),
        'name': a.get('name'),
        'email': a.get('email'),
        'type': a.get('type'),
    }
    return result
# ── GOOGLE CALENDAR ───────────────────────────────────────────────────────────
def calendar_get_events(
    calendar_id: str = 'primary',
    max_results: int = 20,
    time_min: str = None,
    time_max: str = None,
) -> List[Dict]:
    if not _GCAL_OK:
        return []
    return gcal.get_events(
        calendar_id=calendar_id,
        max_results=max_results,
        time_min=time_min,
        time_max=time_max,
    )
def calendar_get_event(event_id: str, calendar_id: str = 'primary') -> Dict:
    if not _GCAL_OK:
        return {}
    return gcal.get_event(event_id, calendar_id=calendar_id)
def calendar_create_event(
    summary: str,
    start: str,
    end: str,
    description: str = '',
    location: str = '',
    attendees: list = None,
    calendar_id: str = 'primary',
    timezone: str = 'Europe/Rome',
) -> Dict:
    if not _GCAL_OK:
        return {}
    return gcal.create_event(
        summary,
        start,
        end,
        description=description,
        location=location,
        attendees=attendees,
        calendar_id=calendar_id,
        timezone=timezone,
    )
def calendar_update_event(event_id: str, **kwargs) -> Dict:
    if not _GCAL_OK:
        return {}
    return gcal.update_event(event_id, **kwargs)
def calendar_delete_event(event_id: str, calendar_id: str = 'primary') -> bool:
    if not _GCAL_OK:
        return False
    return gcal.delete_event(event_id, calendar_id=calendar_id)
def calendar_list_calendars() -> List[Dict]:
    if not _GCAL_OK:
        return []
    return gcal.list_calendars()
