# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Regole di risposta (0.2): semi-auto e auto reply.

Una regola dice: per le mail che arrivano DA questi mittenti (o IN questa
cartella), prepara una risposta pescando SOLO da questi documenti, in
questo stile. `mode` decide il finale:
  semi  la bozza diventa una normale richiesta di approvazione (pending,
        notificata): l'umano approva con Hello, poi parte.
  auto  la richiesta nasce gia' approvata, decided_by "automode:<rule_id>":
        la pre-approvazione E' la regola, che l'umano ha creato dietro
        Windows Hello / Touch ID, con scadenza e tetto giornaliero.

Chi puo' creare o riattivare una regola: SOLO la CLI o la console, dietro
verifica dell'utente fisico (consent.require_human). Nessun tool MCP tocca
questo modulo: un'istruzione iniettata in una mail non puo' dire all'agente
"attiva l'automode" — l'agente non ha il tool.

Lo stato vive in .rules.db sotto app_root(), accanto ad approvals.db:
processi diversi (watcher, CLI, console) condividono SQLite, non memoria.
"""
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Trigger possibili, dal meno al piu' rischioso:
#   senders  lista esplicita di indirizzi (match sul From autenticato)
#   folder   una cartella: mittente arbitrario — e' il trigger da cui
#            first_contact:semi e le barriere anti-spam difendono
TRIGGER_KINDS = ("senders", "folder")
MODES = ("semi", "auto")

# Default prudenti. La scadenza e' OBBLIGATORIA: una regola eterna e' una
# pre-approvazione eterna, e nessuna approvazione dovrebbe esserlo.
DEFAULT_EXPIRY_DAYS = 30
DEFAULT_DAILY_CAP = 10
DEFAULT_COOLDOWN_HOURS = 4
# Raffica: piu' di BURST_MAX match sulla stessa regola in BURST_WINDOW
# secondi → la regola si pausa da sola (fail-closed) e riparte solo con
# Hello. Un attacco manda 5 mail, non 200.
BURST_MAX = 5
BURST_WINDOW_SECONDS = 600


def _db_path() -> Path:
    from ade_mail_agent.core.data_paths import app_root
    return app_root() / ".rules.db"


class RuleStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = str(path or _db_path())
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rules (
                    rule_id           TEXT PRIMARY KEY,
                    account_id        INTEGER NOT NULL,
                    trigger_kind      TEXT NOT NULL,
                    trigger_values    TEXT NOT NULL,
                    reply_style       TEXT NOT NULL DEFAULT '',
                    doc_paths         TEXT NOT NULL DEFAULT '[]',
                    mode              TEXT NOT NULL,
                    first_contact     TEXT NOT NULL DEFAULT 'semi',
                    daily_cap         INTEGER NOT NULL,
                    cooldown_hours    REAL NOT NULL,
                    expires_at        REAL NOT NULL,
                    created_at        REAL NOT NULL,
                    created_by        TEXT NOT NULL,
                    hello_verified_at REAL NOT NULL,
                    paused            INTEGER NOT NULL DEFAULT 0,
                    pause_reason      TEXT
                )
            """)
            # Ogni mail che una regola ha guardato, con l'esito: e' insieme
            # l'idempotenza del watcher (mai due bozze per la stessa mail),
            # il contatore del tetto giornaliero, il cooldown per mittente e
            # la finestra del rilevatore di raffica.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS handled (
                    rule_id    TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    message_id TEXT NOT NULL,
                    sender     TEXT NOT NULL DEFAULT '',
                    status     TEXT NOT NULL,
                    reason     TEXT,
                    request_id TEXT,
                    ts         REAL NOT NULL,
                    PRIMARY KEY (rule_id, message_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_handled_rule_ts"
                " ON handled (rule_id, ts)")
            # feedback dell'umano per "rifiuta e riprova con modifica"
            cols = {r[1] for r in conn.execute("PRAGMA table_info(handled)")}
            if "feedback" not in cols:
                conn.execute("ALTER TABLE handled ADD COLUMN feedback TEXT")
            # stato piccolo del watcher (es. offset di getUpdates Telegram)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kv (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

    # ------------------------------------------------------------- rules

    def create(self, *, account_id: int, trigger_kind: str,
               trigger_values: List[str], reply_style: str,
               doc_paths: List[str], mode: str,
               first_contact: str = "semi",
               daily_cap: int = DEFAULT_DAILY_CAP,
               cooldown_hours: float = DEFAULT_COOLDOWN_HOURS,
               expiry_days: float = DEFAULT_EXPIRY_DAYS,
               created_by: str = "unknown",
               hello_verified_at: float = 0.0) -> str:
        """Registra una regola. `hello_verified_at` e' l'istante in cui il
        chiamante ha superato consent.require_human: DEVE essere valorizzato
        (il chiamante e' la CLI/console, mai un tool MCP). Qui e' un dato,
        non un controllo: il controllo sta nel fatto che solo codice con
        accesso a questo modulo — e al prompt OS — puo' arrivarci."""
        if trigger_kind not in TRIGGER_KINDS:
            raise ValueError(f"trigger_kind '{trigger_kind}' non valido")
        if mode not in MODES:
            raise ValueError(f"mode '{mode}' non valido")
        if first_contact not in MODES:
            raise ValueError(f"first_contact '{first_contact}' non valido")
        if not trigger_values:
            raise ValueError("trigger_values vuoto")
        if not hello_verified_at:
            raise ValueError(
                "hello_verified_at mancante: una regola nasce solo dietro "
                "verifica dell'utente fisico (Windows Hello / Touch ID)")
        rule_id = "rule_" + secrets.token_hex(4)
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO rules (rule_id, account_id, trigger_kind,"
                " trigger_values, reply_style, doc_paths, mode, first_contact,"
                " daily_cap, cooldown_hours, expires_at, created_at,"
                " created_by, hello_verified_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rule_id, int(account_id), trigger_kind,
                 json.dumps(trigger_values, ensure_ascii=False),
                 reply_style, json.dumps(doc_paths, ensure_ascii=False),
                 mode, first_contact, int(daily_cap), float(cooldown_hours),
                 now + expiry_days * 86400, now, created_by,
                 float(hello_verified_at)),
            )
        return rule_id

    @staticmethod
    def _row_to_rule(row) -> Dict[str, Any]:
        d = dict(row)
        d["trigger_values"] = json.loads(d["trigger_values"])
        d["doc_paths"] = json.loads(d["doc_paths"])
        d["paused"] = bool(d["paused"])
        d["expired"] = time.time() > d["expires_at"]
        return d

    def get(self, rule_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM rules WHERE rule_id=?", (rule_id,)).fetchone()
        return self._row_to_rule(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM rules ORDER BY created_at DESC").fetchall()
        return [self._row_to_rule(r) for r in rows]

    def active(self) -> List[Dict[str, Any]]:
        """Regole che il watcher deve considerare: non in pausa, non scadute."""
        now = time.time()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM rules WHERE paused=0 AND expires_at > ?"
                " ORDER BY created_at", (now,)).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def pause(self, rule_id: str, reason: str = "") -> bool:
        """Mettere in pausa e' sempre lecito, da chiunque: riduce l'autonomia.
        E' riattivare che richiede l'umano."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE rules SET paused=1, pause_reason=? WHERE rule_id=?",
                (reason or None, rule_id))
            return cur.rowcount == 1

    def resume(self, rule_id: str, hello_verified_at: float) -> bool:
        """Riattivazione: come la creazione, solo dietro verifica umana."""
        if not hello_verified_at:
            raise ValueError("hello_verified_at mancante")
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE rules SET paused=0, pause_reason=NULL,"
                " hello_verified_at=? WHERE rule_id=?",
                (float(hello_verified_at), rule_id))
            return cur.rowcount == 1

    def delete(self, rule_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM rules WHERE rule_id=?", (rule_id,))
            conn.execute("DELETE FROM handled WHERE rule_id=?", (rule_id,))
            return cur.rowcount == 1

    # ----------------------------------------------------------- handled

    def already_handled(self, rule_id: str, message_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM handled WHERE rule_id=? AND message_id=?",
                (rule_id, str(message_id))).fetchone()
        return row is not None

    def record(self, rule_id: str, account_id: int, message_id: str,
               sender: str, status: str, reason: str = "",
               request_id: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO handled (rule_id, account_id,"
                " message_id, sender, status, reason, request_id, ts)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (rule_id, int(account_id), str(message_id),
                 (sender or "").lower(), status, reason or None,
                 request_id or None, time.time()))

    def set_status(self, rule_id: str, message_id: str, status: str,
                   reason: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE handled SET status=?, reason=?, ts=?"
                " WHERE rule_id=? AND message_id=?",
                (status, reason or None, time.time(), rule_id, str(message_id)))

    def get_handled(self, rule_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM handled WHERE rule_id=? AND message_id=?",
                (rule_id, str(message_id))).fetchone()
        return dict(row) if row else None

    def find_by_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """La riga handled che ha generato una certa richiesta di
        approvazione: serve per tradurre un "approva req_x" arrivato da
        Telegram nella mail e nella regola a cui appartiene."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM handled WHERE request_id=?",
                (request_id,)).fetchone()
        return dict(row) if row else None

    def request_retry(self, rule_id: str, message_id: str, feedback: str) -> None:
        """L'umano ha rifiutato la bozza e chiesto una modifica: la mail
        torna in coda con il feedback, e il watcher la rifa' al prossimo
        giro (process_retries) — ripassando dal gate."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE handled SET status='retry', reason=NULL, feedback=?,"
                " ts=? WHERE rule_id=? AND message_id=?",
                (feedback, time.time(), rule_id, str(message_id)))

    def retries(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM handled WHERE status='retry'").fetchall()
        return [dict(r) for r in rows]

    def kv_get(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def kv_set(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?,?)",
                         (key, str(value)))

    def pending_requests(self, rule_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Le mail per cui esiste una richiesta di approvazione creata dal
        watcher e non ancora conclusa (semi in attesa dell'umano)."""
        q = ("SELECT * FROM handled WHERE status='awaiting_approval'"
             " AND request_id IS NOT NULL")
        args: tuple = ()
        if rule_id:
            q += " AND rule_id=?"
            args = (rule_id,)
        with self._conn() as conn:
            rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    # Contatori per le barriere che hanno bisogno di memoria: il tetto
    # giornaliero conta le risposte USCITE, il cooldown guarda l'ultima
    # risposta allo stesso mittente, la raffica conta i MATCH (qualunque
    # esito: e' il volume in ingresso che segnala l'attacco).

    def sent_today(self, rule_id: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM handled WHERE rule_id=?"
                " AND status='sent' AND ts > ?",
                (rule_id, time.time() - 86400)).fetchone()
        return int(row["n"]) if row else 0

    def last_reply_to(self, rule_id: str, sender: str) -> Optional[float]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(ts) AS t FROM handled WHERE rule_id=? AND sender=?"
                " AND status IN ('sent','awaiting_approval')",
                (rule_id, (sender or "").lower())).fetchone()
        return float(row["t"]) if row and row["t"] else None

    def matches_since(self, rule_id: str, since_ts: float) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM handled WHERE rule_id=? AND ts > ?",
                (rule_id, since_ts)).fetchone()
        return int(row["n"]) if row else 0

    def ever_replied_to(self, sender: str, account_id: int) -> bool:
        """Il mittente ha gia' ricevuto una risposta approvata (da qualunque
        regola di questo account)? Serve a first_contact: il primo messaggio
        di un mittente nuovo passa sempre dall'umano; dai successivi in poi
        la fiducia e' progressiva."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM handled WHERE account_id=? AND sender=?"
                " AND status='sent' LIMIT 1",
                (int(account_id), (sender or "").lower())).fetchone()
        return row is not None


_store: Optional[RuleStore] = None


def store() -> RuleStore:
    global _store
    if _store is None:
        _store = RuleStore()
    return _store


def set_store(new_store: RuleStore) -> None:
    """Usata dai test per isolare il database."""
    global _store
    _store = new_store
