"""
drafts.py — Bozze della console, salvate in locale finche' non partono.

La console salva mentre si scrive (ogni pochi secondi e alla chiusura della
finestra): la bozza sopravvive a una finestra chiusa per sbaglio, a un
crash, a un riavvio. Una bozza ha un id stabile, cosi' i salvataggi
successivi la AGGIORNANO invece di accumulare copie; all'invio la console
la cancella.

Gli allegati NON si salvano qui: sono base64 anche da decine di MB, e una
bozza deve restare leggera da riscrivere ogni pochi secondi.

La sincronizzazione con la cartella Bozze della casella (IMAP APPEND,
Graph) e' il passo successivo e partira' da questo archivio.
"""

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Oltre questa misura il corpo e' quasi certamente un incollaggio sbagliato
# (un PDF convertito, un log): meglio rifiutare che gonfiare il DB.
MAX_BODY_CHARS = 500_000

_FIELDS = ("to", "cc", "bcc", "subject", "body", "reply_to_id")


def _db_path() -> Path:
    from ade_mail_agent.core.data_paths import app_root
    return app_root() / ".drafts.db"


class _ClosingConnection(sqlite3.Connection):
    """Come in rules.py: l'uscita dal `with` chiude la connessione, o su
    Windows il file resta lockato fino al GC."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class DraftStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = str(path or _db_path())
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10,
                               factory=_ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id    TEXT PRIMARY KEY,
                    account_id  INTEGER,
                    "to"        TEXT NOT NULL DEFAULT '',
                    cc          TEXT NOT NULL DEFAULT '',
                    bcc         TEXT NOT NULL DEFAULT '',
                    subject     TEXT NOT NULL DEFAULT '',
                    body        TEXT NOT NULL DEFAULT '',
                    reply_to_id TEXT,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS drafts_account "
                         "ON drafts(account_id, updated_at)")

    def save(self, draft_id: Optional[str] = None,
             account_id: Optional[int] = None, **fields) -> Dict:
        """Crea la bozza o, se `draft_id` esiste gia', la aggiorna.

        Un id sconosciuto non e' un errore: la console puo' averlo generato
        prima che il DB esistesse (o dopo un reset), e perdere il testo per
        questo sarebbe peggio di crearne una nuova con quell'id.
        """
        values = {k: (fields.get(k) or "") for k in _FIELDS}
        values["reply_to_id"] = fields.get("reply_to_id") or None
        if len(values["body"]) > MAX_BODY_CHARS:
            raise ValueError(
                f"Testo troppo lungo per una bozza ({len(values['body'])} "
                f"caratteri, massimo {MAX_BODY_CHARS})")
        now = time.time()
        draft_id = draft_id or uuid.uuid4().hex
        with self._conn() as conn:
            cur = conn.execute(
                'UPDATE drafts SET account_id=?, "to"=?, cc=?, bcc=?, '
                'subject=?, body=?, reply_to_id=?, updated_at=? '
                'WHERE draft_id=?',
                (account_id, values["to"], values["cc"], values["bcc"],
                 values["subject"], values["body"], values["reply_to_id"],
                 now, draft_id))
            if cur.rowcount == 0:
                conn.execute(
                    'INSERT INTO drafts (draft_id, account_id, "to", cc, bcc, '
                    'subject, body, reply_to_id, created_at, updated_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (draft_id, account_id, values["to"], values["cc"],
                     values["bcc"], values["subject"], values["body"],
                     values["reply_to_id"], now, now))
        return self.get(draft_id)

    def get(self, draft_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id=?",
                               (draft_id,)).fetchone()
        return dict(row) if row else None

    def list(self, account_id: Optional[int] = None) -> List[Dict]:
        """Piu' recenti prima. Con `account_id`, solo quelle dell'account
        (piu' quelle senza account: nate prima di sceglierne uno)."""
        with self._conn() as conn:
            if account_id is None:
                rows = conn.execute(
                    "SELECT * FROM drafts ORDER BY updated_at DESC, rowid DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drafts WHERE account_id=? "
                    "OR account_id IS NULL ORDER BY updated_at DESC, rowid DESC",
                    (account_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete(self, draft_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM drafts WHERE draft_id=?",
                               (draft_id,))
        return cur.rowcount > 0


_store: Optional[DraftStore] = None


def store() -> DraftStore:
    global _store
    if _store is None:
        _store = DraftStore()
    return _store


def set_store(new_store: Optional[DraftStore]) -> None:
    """Usata dai test per isolare il database."""
    global _store
    _store = new_store
