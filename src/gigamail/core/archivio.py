# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""L'archivio: la copia di GigaMail di tutta la posta, allegati compresi.

Prima GigaMail non teneva niente di suo. Leggeva il server e basta, e un
server non e' un archivio: Outlook, configurato come quasi sempre, scarica
la posta e dopo un paio di settimane la cancella dal server. Il 28/09/2026
una bolletta della luce arrivata a gennaio esisteva solo nel file di
Outlook sul PC: per GigaMail non c'era, e la ricerca rispondeva "nessun
risultato" con tutta la sicurezza del mondo.

Qui si salva OGNI messaggio per intero, cosi' com'e' arrivato (il MIME
grezzo, compresso), di ogni casella e di ogni cartella. Accanto al file
c'e' una riga in SQLite con i campi che servono a cercare e un indice
full text su oggetto, mittente, destinatari, testo completo e nomi degli
allegati. Da qui si cerca, si legge e si estraggono gli allegati anche
quando il server la mail non ce l'ha piu'.

Da dove arrivano i messaggi:
  imap / graph  la sincronizzazione continua (archivio_sync), a ogni giro
                del watcher;
  outlook       l'import una tantum dello storico che Outlook ha gia'
                tolto dal server (outlook_import). Dopo, Outlook non serve
                piu' a niente.

Un messaggio e' identificato dal suo Message-ID dentro l'account: la
stessa mail vista nel server e nel file di Outlook, o spostata di
cartella, resta UNA riga.
"""
import email
import email.header
import gzip
import hashlib
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from email import policy as email_policy
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gigamail.archivio")

# Il prefisso degli id restituiti dall'archivio. Non puo' collidere con un
# UID IMAP (solo cifre) ne' con un id Graph (base64 senza trattini a
# inizio stringa).
PREFISSO_ID = "arch-"

# Da dove e' arrivata la copia: quella del server e' il MIME originale e
# vince su quella ricostruita da Outlook.
FONTI = ("imap", "graph", "outlook")
_PRIORITA = {"outlook": 0, "imap": 1, "graph": 1}

_TESTO_MAX = 200_000


def _data_root() -> Path:
    from .data_paths import data_root
    return data_root()


def _db_path() -> Path:
    return _data_root() / ".archive.db"


def _dir_messaggi() -> Path:
    p = _data_root() / "archive"
    p.mkdir(parents=True, exist_ok=True)
    return p


class _ClosingConnection(sqlite3.Connection):
    """Come in rules.py: uscire dal `with` chiude la connessione, o su
    Windows il file resta lockato fino al GC."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


# ── LETTURA DEL MIME ─────────────────────────────────────────────────

def _testo_da_html(html: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
          .replace("&quot;", '"'))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _nome_allegato(part) -> str:
    nome = part.get_filename()
    if nome:
        return str(nome)
    disp = str(part.get("Content-Disposition") or "").lower()
    if "attachment" in disp:
        return "allegato"
    return ""


def _e_allegato(part) -> bool:
    if part.is_multipart():
        return False
    disp = str(part.get("Content-Disposition") or "").lower()
    if "attachment" in disp:
        return True
    # Un file con nome e inline: e' un allegato vero solo se non e' un
    # immagine incorporata nel corpo (loghi e firme).
    if part.get_filename():
        return not (disp.startswith("inline") and part.get("Content-ID")
                    and part.get_content_maintype() == "image")
    return False


def _corpo(msg) -> Tuple[str, str, str]:
    """(testo semplice, html, tipo) del corpo, allegati esclusi."""
    piano, html = "", ""
    for part in msg.walk():
        if part.is_multipart() or _e_allegato(part):
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            contenuto = part.get_content()
        except Exception:
            try:
                contenuto = (part.get_payload(decode=True) or b"").decode(
                    part.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                continue
        if ctype == "text/plain" and not piano:
            piano = str(contenuto)
        elif ctype == "text/html" and not html:
            html = str(contenuto)
    if html:
        return piano or _testo_da_html(html), html, "html"
    return piano, "", "text"


def _h(grezzo, nome: str) -> str:
    """Un'intestazione, decodificata, senza mai sollevare.

    Il parser moderno di Python (policy.default) va in IndexError su
    intestazioni malformate come `Message-ID: <>`: il 28/09 una sola mail
    cosi' ha fermato la sincronizzazione di un'intera casella. Qui si
    legge con il parser tollerante (compat32) e si decodificano a mano le
    parole codificate."""
    try:
        v = grezzo.get(nome)
    except Exception:
        return ""
    if v is None:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(str(v))))
    except Exception:
        return str(v)


def _indirizzi(valore: str) -> List[Tuple[str, str]]:
    try:
        return [(n or "", a or "") for n, a in getaddresses([str(valore or "")]) if a or n]
    except Exception:
        return []


def _data(grezzo: str, ripiego: Optional[float] = None) -> Tuple[str, float]:
    try:
        dt = parsedate_to_datetime(str(grezzo)) if grezzo else None
    except Exception:
        dt = None
    if dt is None:
        ts = ripiego if ripiego is not None else time.time()
        dt = datetime.fromtimestamp(ts, timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds"), dt.timestamp()


def _allegati(msg) -> List[Any]:
    out = []
    try:
        for p in msg.walk():
            try:
                if _e_allegato(p):
                    out.append(p)
            except Exception:
                continue
    except Exception:
        pass
    return out


def analizza(raw: bytes, ripiego_data: Optional[float] = None) -> Dict[str, Any]:
    """I campi di un messaggio MIME, per la riga e per l'indice.

    Non solleva mai: una mail illeggibile diventa una riga con i campi
    vuoti e la chiave calcolata sui byte, e resta comunque archiviata."""
    try:
        return _analizza(raw, ripiego_data)
    except Exception as e:
        logger.info("mail non interpretabile, archiviata grezza: %s", e)
        data_iso, data_ts = _data("", ripiego_data)
        return {
            "message_key": "sha1:" + hashlib.sha1(raw).hexdigest(),
            "subject": "", "from_name": "", "from_addr": "", "to_addrs": "",
            "cc_addrs": "", "to_list": [], "cc_list": [],
            "date_utc": data_iso, "date_ts": data_ts, "has_attachments": 0,
            "attachment_names": "", "body_text": "", "size": len(raw),
        }


def _analizza(raw: bytes, ripiego_data: Optional[float]) -> Dict[str, Any]:
    msg = email.message_from_bytes(raw, policy=email_policy.default)
    grezzo = email.message_from_bytes(raw)
    mid = _h(grezzo, "Message-ID").strip().strip("<>").strip()
    mitt = _indirizzi(_h(grezzo, "From"))
    to = _indirizzo_lista = _indirizzi(_h(grezzo, "To"))
    cc = _indirizzi(_h(grezzo, "Cc"))
    try:
        piano, _html, _tipo = _corpo(msg)
    except Exception:
        piano = ""
    allegati = [_nome_allegato(p) for p in _allegati(msg)]
    data_iso, data_ts = _data(_h(grezzo, "Date"), ripiego_data)
    if mid:
        chiave = mid.lower()
    else:
        # Senza Message-ID non si usano i byte: la stessa mail presa dal
        # server e ricostruita da Outlook ha separatori MIME diversi. Si
        # usa cio' che la mail DICE, che e' uguale nelle due copie.
        impronta = "|".join([
            data_iso, (mitt[0][1] if mitt else "").lower(),
            ",".join(a.lower() for _n, a in _indirizzo_lista),
            _h(grezzo, "Subject"),
            re.sub(r"\s+", " ", piano or "").strip()[:2000]])
        chiave = "h:" + hashlib.sha1(impronta.encode("utf-8")).hexdigest()
    return {
        "message_key": chiave,
        "subject": _h(grezzo, "Subject"),
        "from_name": mitt[0][0] if mitt else "",
        "from_addr": (mitt[0][1] if mitt else "").lower(),
        "to_addrs": ", ".join(a for _n, a in to),
        "cc_addrs": ", ".join(a for _n, a in cc),
        "to_list": to,
        "cc_list": cc,
        "date_utc": data_iso,
        "date_ts": data_ts,
        "has_attachments": 1 if allegati else 0,
        "attachment_names": " | ".join(n for n in allegati if n),
        "body_text": (piano or "")[:_TESTO_MAX],
        "size": len(raw),
    }


# ── STORE ────────────────────────────────────────────────────────────

class ArchiveStore:
    def __init__(self, path: Optional[Path] = None, cartella: Optional[Path] = None):
        self.path = str(path or _db_path())
        self._cartella = Path(cartella) if cartella else None
        self._init()

    @property
    def cartella(self) -> Path:
        if self._cartella is None:
            return _dir_messaggi()
        self._cartella.mkdir(parents=True, exist_ok=True)
        return self._cartella

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30,
                               factory=_ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id               INTEGER PRIMARY KEY,
                    account_id       INTEGER NOT NULL,
                    message_key      TEXT    NOT NULL,
                    folder           TEXT    NOT NULL DEFAULT '',
                    provider_id      TEXT    NOT NULL DEFAULT '',
                    subject          TEXT    NOT NULL DEFAULT '',
                    from_name        TEXT    NOT NULL DEFAULT '',
                    from_addr        TEXT    NOT NULL DEFAULT '',
                    to_addrs         TEXT    NOT NULL DEFAULT '',
                    cc_addrs         TEXT    NOT NULL DEFAULT '',
                    date_utc         TEXT    NOT NULL DEFAULT '',
                    date_ts          REAL    NOT NULL DEFAULT 0,
                    has_attachments  INTEGER NOT NULL DEFAULT 0,
                    attachment_names TEXT    NOT NULL DEFAULT '',
                    body_text        TEXT    NOT NULL DEFAULT '',
                    size             INTEGER NOT NULL DEFAULT 0,
                    raw_path         TEXT    NOT NULL,
                    source           TEXT    NOT NULL,
                    archived_at      REAL    NOT NULL,
                    UNIQUE (account_id, message_key)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS ix_msg_provider"
                         " ON messages(account_id, provider_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_msg_date"
                         " ON messages(account_id, date_ts)")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    subject, from_name, from_addr, to_addrs, cc_addrs,
                    body_text, attachment_names,
                    content='messages', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
            for sql in (
                """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                     INSERT INTO messages_fts(rowid, subject, from_name, from_addr,
                       to_addrs, cc_addrs, body_text, attachment_names)
                     VALUES (new.id, new.subject, new.from_name, new.from_addr,
                       new.to_addrs, new.cc_addrs, new.body_text, new.attachment_names);
                   END""",
                """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                     INSERT INTO messages_fts(messages_fts, rowid, subject, from_name,
                       from_addr, to_addrs, cc_addrs, body_text, attachment_names)
                     VALUES ('delete', old.id, old.subject, old.from_name, old.from_addr,
                       old.to_addrs, old.cc_addrs, old.body_text, old.attachment_names);
                   END""",
                """CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                     INSERT INTO messages_fts(messages_fts, rowid, subject, from_name,
                       from_addr, to_addrs, cc_addrs, body_text, attachment_names)
                     VALUES ('delete', old.id, old.subject, old.from_name, old.from_addr,
                       old.to_addrs, old.cc_addrs, old.body_text, old.attachment_names);
                     INSERT INTO messages_fts(rowid, subject, from_name, from_addr,
                       to_addrs, cc_addrs, body_text, attachment_names)
                     VALUES (new.id, new.subject, new.from_name, new.from_addr,
                       new.to_addrs, new.cc_addrs, new.body_text, new.attachment_names);
                   END""",
            ):
                conn.execute(sql)
            # Fino a dove e' arrivata la sincronizzazione di ogni cartella.
            # cursor: per IMAP l'ultimo UID, per Graph l'ultima data vista.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    account_id  INTEGER NOT NULL,
                    folder      TEXT    NOT NULL,
                    uidvalidity TEXT    NOT NULL DEFAULT '',
                    cursor      TEXT    NOT NULL DEFAULT '',
                    complete    INTEGER NOT NULL DEFAULT 0,
                    updated_at  REAL    NOT NULL,
                    PRIMARY KEY (account_id, folder)
                )
            """)
            # Gli import una tantum (Outlook): fatti, in corso, falliti.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS imports (
                    account_id  INTEGER NOT NULL,
                    source      TEXT    NOT NULL,
                    status      TEXT    NOT NULL,
                    count       INTEGER NOT NULL DEFAULT 0,
                    detail      TEXT    NOT NULL DEFAULT '',
                    pid         INTEGER NOT NULL DEFAULT 0,
                    started_at  REAL    NOT NULL DEFAULT 0,
                    updated_at  REAL    NOT NULL,
                    PRIMARY KEY (account_id, source)
                )
            """)

    # -- scrittura ------------------------------------------------------

    def _percorso(self, account_id: int, chiave: str) -> Path:
        h = hashlib.sha1(f"{account_id}|{chiave}".encode("utf-8")).hexdigest()
        d = self.cartella / str(int(account_id)) / h[:2]
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{h}.eml.gz"

    def salva(self, account_id: int, raw: bytes, *, folder: str = "",
              provider_id: str = "", source: str = "imap",
              ripiego_data: Optional[float] = None) -> Tuple[int, bool]:
        """Archivia un messaggio. Ritorna (id, nuovo).

        Un messaggio gia' archivio si aggiorna solo in cartella e id del
        provider; il file si riscrive solo se la copia nuova e' migliore
        (quella del server vince su quella ricostruita da Outlook)."""
        if source not in FONTI:
            raise ValueError(f"fonte sconosciuta: {source}")
        campi = analizza(raw, ripiego_data)
        chiave = campi["message_key"]
        with self._conn() as conn:
            riga = conn.execute(
                "SELECT id, source, raw_path FROM messages"
                " WHERE account_id=? AND message_key=?",
                (int(account_id), chiave)).fetchone()
            if riga:
                meglio = _PRIORITA[source] > _PRIORITA.get(riga["source"], 0)
                if meglio:
                    percorso = Path(riga["raw_path"])
                    percorso.write_bytes(gzip.compress(raw))
                    conn.execute(
                        "UPDATE messages SET source=?, size=?, body_text=?,"
                        " attachment_names=?, has_attachments=? WHERE id=?",
                        (source, campi["size"], campi["body_text"],
                         campi["attachment_names"], campi["has_attachments"],
                         riga["id"]))
                if provider_id or folder:
                    conn.execute(
                        "UPDATE messages SET"
                        " folder=CASE WHEN ?<>'' THEN ? ELSE folder END,"
                        " provider_id=CASE WHEN ?<>'' THEN ? ELSE provider_id END"
                        " WHERE id=?",
                        (folder, folder, provider_id, provider_id, riga["id"]))
                return int(riga["id"]), False
            percorso = self._percorso(account_id, chiave)
            percorso.write_bytes(gzip.compress(raw))
            cur = conn.execute(
                "INSERT INTO messages (account_id, message_key, folder,"
                " provider_id, subject, from_name, from_addr, to_addrs,"
                " cc_addrs, date_utc, date_ts, has_attachments,"
                " attachment_names, body_text, size, raw_path, source,"
                " archived_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(account_id), chiave, folder, provider_id,
                 campi["subject"], campi["from_name"], campi["from_addr"],
                 campi["to_addrs"], campi["cc_addrs"], campi["date_utc"],
                 campi["date_ts"], campi["has_attachments"],
                 campi["attachment_names"], campi["body_text"],
                 campi["size"], str(percorso), source, time.time()))
            return int(cur.lastrowid), True

    # -- stato della sincronizzazione ------------------------------------

    def stato(self, account_id: int, folder: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM sync_state WHERE account_id=? AND folder=?",
                (int(account_id), folder)).fetchone()
        return dict(r) if r else None

    def aggiorna_stato(self, account_id: int, folder: str, *,
                       uidvalidity: str = "", cursor: str = "",
                       complete: Optional[bool] = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sync_state (account_id, folder, uidvalidity,"
                " cursor, complete, updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(account_id, folder) DO UPDATE SET"
                " uidvalidity=excluded.uidvalidity, cursor=excluded.cursor,"
                " complete=CASE WHEN ? IS NULL THEN sync_state.complete"
                "               ELSE excluded.complete END,"
                " updated_at=excluded.updated_at",
                (int(account_id), folder, uidvalidity, cursor,
                 1 if complete else 0, time.time(),
                 None if complete is None else 1))

    def ha_chiave(self, account_id: int, message_id: str) -> bool:
        """Il messaggio con questo Message-ID e' gia' in archivio?"""
        chiave = str(message_id or "").strip().strip("<>").strip().lower()
        if not chiave:
            return False
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM messages WHERE account_id=? AND message_key=?"
                " LIMIT 1", (int(account_id), chiave)).fetchone() is not None

    def ha_provider_id(self, account_id: int, provider_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM messages WHERE account_id=? AND provider_id=?"
                " LIMIT 1", (int(account_id), str(provider_id))).fetchone() is not None

    # -- import una tantum ------------------------------------------------

    def import_stato(self, account_id: int, source: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM imports WHERE account_id=? AND source=?",
                (int(account_id), source)).fetchone()
        return dict(r) if r else None

    def import_segna(self, account_id: int, source: str, status: str, *,
                     count: int = 0, detail: str = "", pid: int = 0) -> None:
        adesso = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO imports (account_id, source, status, count,"
                " detail, pid, started_at, updated_at) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(account_id, source) DO UPDATE SET"
                " status=excluded.status, count=excluded.count,"
                " detail=excluded.detail, pid=excluded.pid,"
                " started_at=CASE WHEN excluded.status='running'"
                "                 THEN excluded.started_at ELSE imports.started_at END,"
                " updated_at=excluded.updated_at",
                (int(account_id), source, status, int(count), detail[:500],
                 int(pid), adesso, adesso))

    # -- lettura ----------------------------------------------------------

    def riga(self, account_id: Optional[int], message_id: str,
             folder: str = "") -> Optional[Dict[str, Any]]:
        """Per id d'archivio ("arch-12") o per id del provider.

        In IMAP lo stesso UID esiste in cartelle diverse: con la cartella
        si prende quello giusto, senza si prende il piu' recente."""
        mid = str(message_id or "")
        with self._conn() as conn:
            if mid.startswith(PREFISSO_ID):
                try:
                    rowid = int(mid[len(PREFISSO_ID):])
                except ValueError:
                    return None
                q, args = "SELECT * FROM messages WHERE id=?", [rowid]
                if account_id is not None:
                    q += " AND account_id=?"
                    args.append(int(account_id))
                r = conn.execute(q, args).fetchone()
            elif account_id is not None and mid:
                r = None
                if folder:
                    r = conn.execute(
                        "SELECT * FROM messages WHERE account_id=? AND"
                        " provider_id=? AND lower(folder)=lower(?) LIMIT 1",
                        (int(account_id), mid, folder)).fetchone()
                if r is None:
                    r = conn.execute(
                        "SELECT * FROM messages WHERE account_id=? AND"
                        " provider_id=? ORDER BY archived_at DESC LIMIT 1",
                        (int(account_id), mid)).fetchone()
            else:
                r = None
        return dict(r) if r else None

    def raw(self, riga: Dict[str, Any]) -> bytes:
        return gzip.decompress(Path(riga["raw_path"]).read_bytes())

    def with_address(self, account_id: int, address: str,
                     since_ts: float = 0.0, top: int = 50) -> List[Dict[str, Any]]:
        """Mail exchanged with an address, in and out, newest first."""
        addr = (address or "").strip().lower()
        if "@" not in addr:
            return []
        like = f"%{addr}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE account_id=? AND date_ts>=?"
                " AND (lower(from_addr)=? OR lower(to_addrs) LIKE ?"
                "      OR lower(cc_addrs) LIKE ?)"
                " ORDER BY date_ts DESC LIMIT ?",
                (int(account_id), float(since_ts), addr, like, like,
                 int(top))).fetchall()
        return [dict(r) for r in rows]

    def conta(self, account_id: Optional[int] = None) -> Dict[str, int]:
        q = "SELECT source, COUNT(*) n FROM messages"
        args: tuple = ()
        if account_id is not None:
            q += " WHERE account_id=?"
            args = (int(account_id),)
        q += " GROUP BY source"
        with self._conn() as conn:
            return {r["source"]: r["n"] for r in conn.execute(q, args)}

    def cerca(self, account_id: Optional[int], query: str,
              top: int = 20) -> List[Dict[str, Any]]:
        espr = _espressione_fts(query)
        if not espr:
            return []
        q = ("SELECT m.* FROM messages_fts f JOIN messages m ON m.id=f.rowid"
             " WHERE messages_fts MATCH ?")
        args: list = [espr]
        if account_id is not None:
            q += " AND m.account_id=?"
            args.append(int(account_id))
        q += " ORDER BY m.date_ts DESC LIMIT ?"
        args.append(int(top))
        with self._conn() as conn:
            try:
                righe = conn.execute(q, args).fetchall()
            except sqlite3.OperationalError as e:
                logger.info("ricerca nell'archivio non valida (%s): %s", query, e)
                return []
        return [_sommario(dict(r)) for r in righe]


def _espressione_fts(query: str) -> str:
    """Ogni parola della ricerca come prefisso, tutte obbligatorie.

    Il prefisso e' il punto: "mediocasa" deve trovare
    info@mediocasaimmobiliare.eu, che l'indice spezza nei pezzi
    "info", "mediocasaimmobiliare", "eu"."""
    parole = re.findall(r"\w+", str(query or ""), flags=re.UNICODE)
    return " AND ".join(f'"{p}"*' for p in parole if p)


def _sommario(r: Dict[str, Any]) -> Dict[str, Any]:
    anteprima = re.sub(r"\s+", " ", r.get("body_text") or "").strip()[:300]
    return {
        "id": f"{PREFISSO_ID}{r['id']}",
        "subject": r.get("subject") or "",
        "from": {"emailAddress": {"name": r.get("from_name") or "",
                                  "address": r.get("from_addr") or ""}},
        "receivedDateTime": r.get("date_utc") or "",
        "bodyPreview": anteprima,
        "hasAttachments": bool(r.get("has_attachments")),
        "attachmentNames": [n for n in (r.get("attachment_names") or "").split(" | ") if n],
        "folder": r.get("folder") or "",
        "source": "archive",
    }


def messaggio(riga: Dict[str, Any], raw: bytes) -> Dict[str, Any]:
    """Il messaggio completo nella stessa forma di read_message."""
    msg = email.message_from_bytes(raw, policy=email_policy.default)
    grezzo = email.message_from_bytes(raw)
    try:
        piano, html, tipo = _corpo(msg)
    except Exception:
        piano, html, tipo = "", "", "text"
    allegati = []
    for p in _allegati(msg):
        dati = p.get_payload(decode=True) or b""
        allegati.append({"name": _nome_allegato(p), "size": len(dati),
                         "type": p.get_content_type()})

    def _rec(lista):
        return [{"emailAddress": {"name": n, "address": a}}
                for n, a in _indirizzi(lista)]

    return {
        "id": f"{PREFISSO_ID}{riga['id']}",
        "provider_id": riga.get("provider_id") or "",
        "subject": riga.get("subject") or "",
        "from": {"emailAddress": {"name": riga.get("from_name") or "",
                                  "address": riga.get("from_addr") or ""}},
        "toRecipients": _rec(_h(grezzo, "To")),
        "ccRecipients": _rec(_h(grezzo, "Cc")),
        "receivedDateTime": riga.get("date_utc") or "",
        "body": {"contentType": tipo, "content": html or piano},
        "body_text": (piano or "")[:20000],
        "attachments": allegati,
        "hasAttachments": bool(allegati),
        "folder": riga.get("folder") or "",
        "source": "archive",
    }


def allegato(raw: bytes, filename: str) -> Tuple[bytes, str]:
    """(contenuto, tipo) dell'allegato con quel nome."""
    msg = email.message_from_bytes(raw, policy=email_policy.default)
    for p in _allegati(msg):
        if _nome_allegato(p) == filename:
            return p.get_payload(decode=True) or b"", p.get_content_type()
    raise ValueError(f"Allegato non trovato nell'archivio: {filename}")


# ── ACCESSO CONDIVISO ────────────────────────────────────────────────

_store: Optional[ArchiveStore] = None


def store() -> ArchiveStore:
    global _store
    if _store is None:
        _store = ArchiveStore()
    return _store


def set_store(nuovo: Optional[ArchiveStore]) -> None:
    """Usata dai test per isolare database e cartella."""
    global _store
    _store = nuovo


def cerca(account_id: Optional[int], query: str, top: int = 20) -> List[Dict[str, Any]]:
    try:
        return store().cerca(account_id, query, top=top)
    except Exception as e:
        logger.warning("archivio non consultabile: %s", e)
        return []


def leggi(account_id: Optional[int], message_id: str,
          folder: str = "") -> Optional[Dict[str, Any]]:
    riga = store().riga(account_id, message_id, folder)
    if not riga:
        return None
    return messaggio(riga, store().raw(riga))


def leggi_allegato(account_id: Optional[int], message_id: str,
                   filename: str, folder: str = "") -> Optional[Tuple[bytes, str]]:
    riga = store().riga(account_id, message_id, folder)
    if not riga:
        return None
    return allegato(store().raw(riga), filename)
