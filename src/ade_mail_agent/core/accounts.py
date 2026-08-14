r"""
accounts.py — Gestione multi-account ADE Mail.
Salva account Microsoft e IMAP in SQLite locale cifrato.
DB e KEY in %APPDATA%\ADE\mail\ per persistenza tra riavvii.
"""
import os
import json
import sqlite3
import base64
from typing import List, Optional, Dict
from cryptography.fernet import Fernet
_ADE_DATA = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ADE', 'mail')
os.makedirs(_ADE_DATA, exist_ok=True)
DB_PATH  = os.path.join(_ADE_DATA, '.accounts.db')
KEY_PATH = os.path.join(_ADE_DATA, '.accounts.key')
KEY_PATH_DPAPI = KEY_PATH + '.dpapi'

try:
    from . import win_dpapi as _dpapi
except ImportError:
    _dpapi = None


def _dpapi_ok() -> bool:
    return _dpapi is not None and _dpapi.available()


def _get_key() -> bytes:
    """Chiave Fernet degli account. Su Windows la chiave su disco è protetta
    con DPAPI (legata all'utente): copiare i file non basta a decifrarla.
    La chiave legacy in chiaro viene migrata al primo accesso."""
    # 1. formato protetto
    if _dpapi_ok() and os.path.exists(KEY_PATH_DPAPI):
        with open(KEY_PATH_DPAPI, 'rb') as f:
            return _dpapi.unprotect(f.read())
    # 2. legacy in chiaro -> migra se possibile
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, 'rb') as f:
            key = f.read()
        if _dpapi_ok():
            with open(KEY_PATH_DPAPI, 'wb') as f:
                f.write(_dpapi.protect(key))
            os.remove(KEY_PATH)
        return key
    # 3. prima esecuzione
    key = Fernet.generate_key()
    if _dpapi_ok():
        with open(KEY_PATH_DPAPI, 'wb') as f:
            f.write(_dpapi.protect(key))
    else:
        with open(KEY_PATH, 'wb') as f:
            f.write(key)
    return key
def _encrypt(text: str) -> str:
    f = Fernet(_get_key())
    return f.encrypt(text.encode()).decode()
def _decrypt(token: str) -> str:
    f = Fernet(_get_key())
    return f.decrypt(token.encode()).decode()
def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                email TEXT,
                data_enc TEXT,
                active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
_init_db()
def get_accounts() -> List[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT id, name, type, email, active FROM accounts ORDER BY id').fetchall()
        return [dict(r) for r in rows]
def get_active_account() -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM accounts WHERE active=1 LIMIT 1').fetchone()
        if not row:
            row = conn.execute('SELECT * FROM accounts LIMIT 1').fetchone()
        if not row:
            return None
        acc = dict(row)
        if acc.get('data_enc'):
            try:
                acc['data'] = json.loads(_decrypt(acc['data_enc']))
            except Exception:
                acc['data'] = {}
        return acc
def get_account_by_id(account_id: int) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        if not row:
            return None
        acc = dict(row)
        if acc.get('data_enc'):
            try:
                acc['data'] = json.loads(_decrypt(acc['data_enc']))
            except Exception:
                acc['data'] = {}
        return acc
def add_microsoft_account(name: str, email: str, token_cache: str) -> int:
    data = json.dumps({'token_cache': token_cache})
    data_enc = _encrypt(data)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            'INSERT INTO accounts (name, type, email, data_enc) VALUES (?,?,?,?)',
            (name, 'microsoft', email, data_enc)
        )
        conn.commit()
        return cur.lastrowid
def add_imap_account(name: str, email: str, password: str,
                     imap_host: str, imap_port: int,
                     smtp_host: str, smtp_port: int) -> int:
    data = json.dumps({
        'password': password,
        'imap_host': imap_host,
        'imap_port': imap_port,
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
    })
    data_enc = _encrypt(data)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            'INSERT INTO accounts (name, type, email, data_enc) VALUES (?,?,?,?)',
            (name, 'imap', email, data_enc)
        )
        conn.commit()
        return cur.lastrowid
def set_active_account(account_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('UPDATE accounts SET active=0')
        conn.execute('UPDATE accounts SET active=1 WHERE id=?', (account_id,))
        conn.commit()
def delete_account(account_id: int):
    """Cancella account + dati correlati nello stesso DB (identity, caldav).
    NB: le mail indicizzate sono in mail_memory.db (DB separato): vedi
    mail_memory.delete_account_data() per quelle."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM accounts WHERE id=?', (account_id,))
        # Pulisci tabelle correlate (se esistono — try/except per migrazioni)
        for sql in (
            'DELETE FROM account_identity WHERE account_id=?',
            'DELETE FROM caldav_config WHERE account_id=?',
        ):
            try:
                conn.execute(sql, (account_id,))
            except Exception:
                pass
        conn.commit()
def update_microsoft_token(account_id: int, token_cache: str):
    data = json.dumps({'token_cache': token_cache})
    data_enc = _encrypt(data)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('UPDATE accounts SET data_enc=? WHERE id=?', (data_enc, account_id))
        conn.commit()
PROVIDERS = {
    'aruba': {
        'imap_host': 'imaps.aruba.it', 'imap_port': 993,
        'smtp_host': 'smtps.aruba.it', 'smtp_port': 465,
    },
    'gmail': {
        'imap_host': 'imap.gmail.com', 'imap_port': 993,
        'smtp_host': 'smtp.gmail.com',  'smtp_port': 587,
    },
    'outlook': {
        'imap_host': 'outlook.office365.com', 'imap_port': 993,
        'smtp_host': 'smtp.office365.com',    'smtp_port': 587,
    },
    'libero': {
        'imap_host': 'imapmail.libero.it', 'imap_port': 993,
        'smtp_host': 'smtp.libero.it',     'smtp_port': 465,
    },
    'custom': {
        'imap_host': '', 'imap_port': 993,
        'smtp_host': '', 'smtp_port': 465,
    },
}

# ── IDENTITY PER ACCOUNT ─────────────────────────────────────────────────────

def _init_identity_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_identity (
                account_id        INTEGER PRIMARY KEY,
                who_am_i          TEXT DEFAULT '',
                what_i_do         TEXT DEFAULT '',
                tone              TEXT DEFAULT '',
                key_info          TEXT DEFAULT '',
                file_paths        TEXT DEFAULT '[]',
                folder_identities TEXT DEFAULT '{}',
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrazione: aggiungi colonna se non esiste
        try:
            conn.execute("ALTER TABLE account_identity ADD COLUMN folder_identities TEXT DEFAULT '{}'")
            conn.commit()
        except Exception:
            pass
        conn.commit()

_init_identity_db()

def _init_caldav_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS caldav_config (
                account_id   INTEGER PRIMARY KEY,
                caldav_url   TEXT NOT NULL,
                calendar_url TEXT DEFAULT '',
                enabled      INTEGER DEFAULT 1,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

_init_caldav_db()


def get_caldav_config(account_id: int) -> Optional[Dict]:
    """Ritorna config CalDAV per un account, o None se non configurato."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT * FROM caldav_config WHERE account_id=? AND enabled=1',
            (account_id,)
        ).fetchone()
        return dict(row) if row else None


def set_caldav_config(account_id: int, caldav_url: str, calendar_url: str = '') -> Dict:
    """Salva/aggiorna config CalDAV per un account."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO caldav_config (account_id, caldav_url, calendar_url, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(account_id) DO UPDATE SET
                caldav_url   = excluded.caldav_url,
                calendar_url = excluded.calendar_url,
                enabled      = 1,
                updated_at   = CURRENT_TIMESTAMP
        """, (account_id, caldav_url, calendar_url or ''))
        conn.commit()
    return get_caldav_config(account_id)


def delete_caldav_config(account_id: int):
    """Disabilita CalDAV per un account."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'UPDATE caldav_config SET enabled=0 WHERE account_id=?',
            (account_id,)
        )
        conn.commit()


def get_identity(account_id: int) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT * FROM account_identity WHERE account_id=?', (account_id,)
        ).fetchone()
        if not row:
            return {
                'account_id': account_id,
                'who_am_i': '', 'what_i_do': '',
                'tone': '', 'key_info': '', 'file_paths': [],
                'folder_identities': {},
            }
        d = dict(row)
        try:
            d['file_paths'] = json.loads(d.get('file_paths') or '[]')
        except Exception:
            d['file_paths'] = []
        try:
            d['folder_identities'] = json.loads(d.get('folder_identities') or '{}')
        except Exception:
            d['folder_identities'] = {}
        return d


def set_identity(account_id: int, who_am_i: str = '', what_i_do: str = '',
                 tone: str = '', key_info: str = '', file_paths=None) -> dict:
    fp_json = json.dumps(file_paths or [], ensure_ascii=False)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO account_identity
                (account_id, who_am_i, what_i_do, tone, key_info, file_paths, updated_at)
            VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)
            ON CONFLICT(account_id) DO UPDATE SET
                who_am_i   = excluded.who_am_i,
                what_i_do  = excluded.what_i_do,
                tone       = excluded.tone,
                key_info   = excluded.key_info,
                file_paths = excluded.file_paths,
                updated_at = CURRENT_TIMESTAMP
        """, (account_id, who_am_i, what_i_do, tone, key_info, fp_json))
        conn.commit()
    return get_identity(account_id)


def get_folder_identity(account_id: int, folder_id: str) -> dict:
    """Restituisce l'identity specifica per una cartella."""
    identity = get_identity(account_id)
    folder_identities = identity.get('folder_identities') or {}
    return folder_identities.get(folder_id, {})


def set_folder_identity(account_id: int, folder_id: str,
                        who_am_i: str = '', what_i_do: str = '',
                        tone: str = '', key_info: str = '',
                        file_paths=None) -> dict:
    """Salva identity specifica per una cartella."""
    identity = get_identity(account_id)
    folder_identities = identity.get('folder_identities') or {}
    folder_identities[folder_id] = {
        'who_am_i': who_am_i,
        'what_i_do': what_i_do,
        'tone': tone,
        'key_info': key_info,
        'file_paths': file_paths or [],
    }
    fi_json = json.dumps(folder_identities, ensure_ascii=False)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO account_identity (account_id, folder_identities, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(account_id) DO UPDATE SET
                folder_identities = excluded.folder_identities,
                updated_at = CURRENT_TIMESTAMP
        """, (account_id, fi_json))
        conn.commit()
    return get_identity(account_id)


def delete_folder_identity(account_id: int, folder_id: str) -> dict:
    """Rimuove identity specifica per una cartella."""
    identity = get_identity(account_id)
    folder_identities = identity.get('folder_identities') or {}
    folder_identities.pop(folder_id, None)
    fi_json = json.dumps(folder_identities, ensure_ascii=False)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE account_identity SET folder_identities=?, updated_at=CURRENT_TIMESTAMP
            WHERE account_id=?
        """, (fi_json, account_id))
        conn.commit()
    return get_identity(account_id)

# ── CALENDARIO PRINCIPALE ─────────────────────────────────────────────────────

def _init_calendar_primary_db():
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute("ALTER TABLE accounts ADD COLUMN calendar_primary INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass

_init_calendar_primary_db()


def set_calendar_primary(account_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE accounts SET calendar_primary=0")
        conn.execute("UPDATE accounts SET calendar_primary=1 WHERE id=?", (account_id,))
        conn.commit()


def get_calendar_primary() -> Optional[int]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id FROM accounts WHERE calendar_primary=1 LIMIT 1"
        ).fetchone()
        if row:
            return row[0]
        row = conn.execute(
            "SELECT id FROM accounts WHERE type='microsoft' LIMIT 1"
        ).fetchone()
        return row[0] if row else None
