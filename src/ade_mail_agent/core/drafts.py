"""
drafts.py — Bozze della console: salvate in locale, copiate nella casella.

La console salva mentre si scrive (ogni pochi secondi e alla chiusura della
finestra): la bozza sopravvive a una finestra chiusa per sbaglio, a un
crash, a un riavvio. Una bozza ha un id stabile, cosi' i salvataggi
successivi la AGGIORNANO invece di accumulare copie; all'invio la console
la cancella.

Il DB locale e' il salvataggio veloce. La copia nella cartella Bozze della
casella (IMAP o Graph, vedi mail_router.save_draft) e' piu' lenta e si fa
meno spesso, su richiesta della console, in un thread: e' quella che fa
ritrovare la mail su Outlook o sul telefono. `synced_at` ricorda QUALE
versione e' arrivata nella casella (il suo updated_at), non quando: una
modifica fatta durante la copia resta cosi' da copiare.

Gli allegati NON si salvano: sono base64 anche da decine di MB, e una
bozza deve restare leggera da riscrivere ogni pochi secondi.
"""

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Oltre questa misura il corpo e' quasi certamente un incollaggio sbagliato
# (un PDF convertito, un log): meglio rifiutare che gonfiare il DB.
MAX_BODY_CHARS = 500_000

_FIELDS = ("to", "cc", "bcc", "subject", "body", "reply_to_id")

# Colonne della copia nella casella, aggiunte dopo la prima versione del DB.
_REMOTE_COLUMNS = {
    "remote_id": "TEXT",        # UID IMAP o id Graph della copia in Bozze
    "remote_folder": "TEXT",
    "synced_at": "REAL",        # updated_at della versione copiata
    "sync_error": "TEXT",
}


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
            have = {r["name"] for r in conn.execute("PRAGMA table_info(drafts)")}
            for name, kind in _REMOTE_COLUMNS.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE drafts ADD COLUMN {name} {kind}")

    def save(self, draft_id: Optional[str] = None,
             account_id: Optional[int] = None,
             remote_id: Optional[str] = None,
             remote_folder: Optional[str] = None, **fields) -> Dict:
        """Crea la bozza o, se `draft_id` esiste gia', la aggiorna.

        Un id sconosciuto non e' un errore: la console puo' averlo generato
        prima che il DB esistesse (o dopo un reset), e perdere il testo per
        questo sarebbe peggio di crearne una nuova con quell'id.

        `remote_id` si passa solo riprendendo una bozza gia' nella casella
        (nata su Outlook o sul telefono): la prossima copia la sostituisce.
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
            if remote_id:
                conn.execute("UPDATE drafts SET remote_id=?, remote_folder=? "
                             "WHERE draft_id=?",
                             (remote_id, remote_folder, draft_id))
        return self.get(draft_id)

    def mark_synced(self, draft_id: str, version: float,
                    remote_id: Optional[str], remote_folder: Optional[str]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE drafts SET remote_id=?, remote_folder=?, synced_at=?, "
                "sync_error=NULL WHERE draft_id=?",
                (remote_id, remote_folder, version, draft_id))

    def mark_sync_error(self, draft_id: str, error: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE drafts SET sync_error=? WHERE draft_id=?",
                         (error[:500], draft_id))

    def get(self, draft_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id=?",
                               (draft_id,)).fetchone()
        return _view(row) if row else None

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
        return [_view(r) for r in rows]

    def delete(self, draft_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM drafts WHERE draft_id=?",
                               (draft_id,))
        return cur.rowcount > 0


def _view(row) -> Dict:
    d = dict(row)
    # "in_mailbox": la versione che si vede qui e' anche nella casella.
    d["in_mailbox"] = bool(d.get("synced_at")) and d["synced_at"] >= d["updated_at"]
    return d


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


# ── COPIA NELLA CASELLA ──────────────────────────────────────────────
# Un lock per bozza: copia e cancellazione della stessa bozza non si
# incrociano. Senza, un invio fatto mentre la copia e' in volo lascerebbe
# nelle Bozze della casella una mail gia' partita.

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(draft_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(draft_id, threading.Lock())


def sync(draft_id: str) -> Optional[Dict]:
    """Copia nella casella la versione attuale, se non c'e' gia'."""
    from ade_mail_agent.core import mail_router
    with _lock(draft_id):
        d = store().get(draft_id)
        if not d or d["in_mailbox"] or d["account_id"] is None:
            return d
        r = mail_router.save_draft(d["account_id"], d, remote_id=d.get("remote_id"))
        if r.get("success"):
            store().mark_synced(draft_id, d["updated_at"],
                                r.get("remote_id"), r.get("remote_folder"))
        else:
            store().mark_sync_error(draft_id, r.get("error") or "copia non riuscita")
        return store().get(draft_id)


def sync_in_background(draft_id: str) -> None:
    threading.Thread(target=_sync_quietly, args=(draft_id,), daemon=True,
                     name=f"draft-sync-{draft_id[:8]}").start()


def _sync_quietly(draft_id: str) -> None:
    try:
        sync(draft_id)
    except Exception as e:
        print(f"[DRAFTS] sync {draft_id}: {e}")
        try:
            store().mark_sync_error(draft_id, str(e))
        except Exception:
            pass


def discard(draft_id: str) -> Optional[Dict]:
    """Toglie la bozza dal DB locale e ne restituisce l'ultima versione,
    per cancellarla anche dalla casella (vedi remove_from_mailbox).
    Aspetta un'eventuale copia in corso: finita quella, remote_id e' giusto."""
    with _lock(draft_id):
        d = store().get(draft_id)
        if d:
            store().delete(draft_id)
        return d


def remove_from_mailbox(d: Dict) -> None:
    """La copia nella casella di una bozza gia' tolta in locale."""
    from ade_mail_agent.core import mail_router
    if d.get("account_id") is None or not (d.get("remote_id") or d.get("synced_at")):
        return
    try:
        r = mail_router.delete_draft(d["account_id"], d["draft_id"], d.get("remote_id"))
        if not r.get("success"):
            print(f"[DRAFTS] delete {d['draft_id']} dalla casella: {r.get('error')}")
    except Exception as e:
        print(f"[DRAFTS] delete {d['draft_id']} dalla casella: {e}")


def remove_from_mailbox_in_background(d: Dict) -> None:
    threading.Thread(target=remove_from_mailbox, args=(d,), daemon=True,
                     name=f"draft-delete-{d['draft_id'][:8]}").start()
