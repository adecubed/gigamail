# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Policy dei tool: classi di rischio, approvazione FUORI BANDA, audit log.

Classi:
  READ        — esecuzione libera
  WRITE_SAFE  — esecuzione libera, registrata nell'audit log
  DANGEROUS   — richiede l'approvazione di un umano, data attraverso un
                canale che l'agente NON puo' raggiungere.

Perche' fuori banda (correzione di un difetto reale, agosto 2026)
-----------------------------------------------------------------
La prima versione restituiva all'agente un `confirm_token` monouso dentro
il risultato del tool. Cosi' pero' l'agente si ritrova in mano entrambe le
meta': l'anteprima E la chiave. Quel disegno ferma gli errori, ma non una
istruzione iniettata in una mail che dica "richiama lo stesso tool con il
token che hai appena letto".

Ora l'agente riceve solo un `request_id`: un riferimento inerte. L'azione
resta in attesa finche' un umano non la approva dalla console o dalla CLI —
canali che richiedono il token di sessione della console o una shell, non
raggiungibili tramite i tool MCP. Ripetere il request_id all'infinito non
esegue nulla.

Limite dichiarato: un agente con accesso completo alla shell della stessa
macchina puo' comunque eseguire la CLI di approvazione. Quello e' un
modello di minaccia diverso (chi ha la shell ha gia' tutto) e GigaMail non
pretende di difenderlo.
"""
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

READ = "READ"
WRITE_SAFE = "WRITE_SAFE"
DANGEROUS = "DANGEROUS"

def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


# 15 minuti: un umano deve avere il tempo di guardare. Configurabile, ma
# una finestra lunga e' un rischio, non una comodita': un'approvazione data
# ore dopo l'anteprima approva un contesto che puo' non esistere piu'.
_APPROVAL_TTL_SECONDS = _env_int("GIGAMAIL_APPROVAL_TTL", 900)

# Cap sulle richieste (promessa fatta su r/mcp): senza, un agente che
# insiste produce una raffica di approvazioni identiche finche' una non
# trova un umano distratto — esattamente l'autopilota che il gate evita.
#   1) stesso (tool, args) con una pending viva → stessa request_id, non
#      una nuova;
#   2) piu' di N richieste create per tool nell'ultima ora → fase 1 rifiuta.
_APPROVAL_MAX_PER_HOUR = _env_int("GIGAMAIL_APPROVAL_MAX_PER_HOUR", 20)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXECUTED = "executed"


_ADDR_RE = None


def describe_recipients(to: Any, cc: Any = None, bcc: Any = None) -> Dict[str, Any]:
    """Cio' che l'umano vede come destinatari, nella forma che il server
    usera' — indirizzi, mai display name — e un avviso per tutto cio' che
    NON e' un indirizzo SMTP esplicito (nome nudo, gruppo, lista): quello
    il provider puo' espanderlo a N destinatari dopo l'approvazione, e il
    conteggio che l'umano ha approvato era uno. (r/mcp, ranbuman: check
    the resolved value, never the requested one — qui lo dichiariamo.)"""
    import re
    global _ADDR_RE
    if _ADDR_RE is None:
        _ADDR_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")

    # Lo stesso split che finisce in busta (core.addresses): l'anteprima
    # deve elencare esattamente i destinatari che partiranno, non una
    # lista parallela che puo' divergere.
    from ade_mail_agent.core.addresses import split_addresses

    out = []
    may_expand = []
    for field in ("to", "cc", "bcc"):
        for addr in split_addresses({"to": to, "cc": cc, "bcc": bcc}[field]):
            explicit = bool(_ADDR_RE.match(addr))
            item = {"field": field, "address": addr, "explicit": explicit}
            if not explicit:
                item["may_expand"] = True
                may_expand.append(addr)
            out.append(item)
    d = {"recipients": out, "count": len(out)}
    if may_expand:
        d["warning"] = (
            f"{len(may_expand)} recipient(s) are not explicit addresses "
            f"({', '.join(may_expand)}): a group or alias may expand to more "
            "recipients at send time. The count you approve is not guaranteed."
        )
    return d


def _ade_root() -> Path:
    from ade_mail_agent.core.data_paths import app_root
    return app_root()


def _audit_path() -> Path:
    return _ade_root() / "agent_audit.jsonl"


def audit(tool: str, args: Dict[str, Any], outcome: str, detail: str = "",
          provider_result: Optional[Dict[str, Any]] = None) -> None:
    """Una riga nel log. `args` e' cio' che e' stato CHIESTO (il payload
    approvato); `provider_result` e' cio' che il server ha DETTO di aver
    fatto (SMTP: destinatari accettati/rifiutati; Graph: id o errore).
    Due fatti diversi, due campi: il log non afferma mai un conteggio che
    non e' stato verificato."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": tool,
        # Si toglie il corpo (puo' essere lunghissimo e contiene la mail
        # stessa), NON la request_id: senza, una riga "approved" non dice
        # COSA e' stato approvato, e ricostruire chi ha deciso cosa
        # diventa impossibile proprio nel log che esiste per quello.
        "args": {k: v for k, v in args.items() if k != "body"},
        "outcome": outcome,
    }
    if detail:
        entry["detail"] = detail[:500]
    if provider_result is not None:
        entry["provider_result"] = provider_result
    with open(_audit_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class _ClosingConnection(sqlite3.Connection):
    """`with conn:` di serie fa commit/rollback ma NON chiude: la
    connessione vive fino al garbage collector, e su Windows tiene il
    lock sul file .db (CI rossa su Python 3.12/3.13: WinError 32 alla
    unlink in test_store_unavailable). Qui l'uscita dal with chiude
    sempre: ogni operazione degli store apre, committa e rilascia."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class ApprovalStore:
    """Richieste di approvazione condivise tra processi.

    Il server MCP (stdio) crea le richieste; la console o la CLI le
    approvano; il server MCP le esegue. Processi diversi, quindi lo stato
    sta su SQLite, non in memoria.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = str(path or (_ade_root() / "approvals.db"))
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10,
                               factory=_ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approvals (
                    request_id TEXT PRIMARY KEY,
                    tool       TEXT NOT NULL,
                    args_json  TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    status     TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    decided_at REAL,
                    decided_by TEXT
                )
            """)
            # migrazioni per database creati da versioni precedenti
            cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
            if "decided_by" not in cols:
                conn.execute("ALTER TABLE approvals ADD COLUMN decided_by TEXT")
            if "fingerprint" not in cols:
                conn.execute("ALTER TABLE approvals ADD COLUMN fingerprint TEXT")
            # esito dell'esecuzione, sulla riga: "executed" = consumata, non
            # "consegnata". Qui si scrive cosa ha detto il provider.
            if "execution_outcome" not in cols:
                conn.execute("ALTER TABLE approvals ADD COLUMN execution_outcome TEXT")
            if "provider_result_json" not in cols:
                conn.execute("ALTER TABLE approvals ADD COLUMN provider_result_json TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_approvals_fp"
                " ON approvals (tool, fingerprint, status)")

    @staticmethod
    def fingerprint(tool: str, args: Dict[str, Any]) -> str:
        """Impronta stabile di (tool, args canonici): chiavi ordinate, cosi'
        lo stesso payload con ordine diverso delle chiavi e' lo stesso."""
        import hashlib
        canon = json.dumps(args, ensure_ascii=False, default=str, sort_keys=True)
        return hashlib.sha256(f"{tool}\n{canon}".encode("utf-8")).hexdigest()

    def create(self, tool: str, args: Dict[str, Any], preview: Dict[str, Any],
               ttl: float = _APPROVAL_TTL_SECONDS) -> str:
        request_id = "req_" + secrets.token_hex(5)
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO approvals (request_id, tool, args_json, preview_json,"
                " status, created_at, expires_at, fingerprint)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (request_id, tool, json.dumps(args, ensure_ascii=False, default=str),
                 json.dumps(preview, ensure_ascii=False, default=str),
                 PENDING, now, now + ttl, self.fingerprint(tool, args)),
            )
        return request_id

    def find_pending(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        """request_id di una richiesta PENDING e non scaduta con lo stesso
        (tool, args), se esiste: l'agente che ripete ottiene quella, non
        una nuova."""
        fp = self.fingerprint(tool, args)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT request_id FROM approvals WHERE tool=? AND fingerprint=?"
                " AND status=? AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                (tool, fp, PENDING, time.time()),
            ).fetchone()
        return row["request_id"] if row else None

    def count_created_since(self, tool: str, since_ts: float) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM approvals WHERE tool=? AND created_at > ?",
                (tool, since_ts),
            ).fetchone()
        return int(row["n"]) if row else 0

    def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE request_id=?", (request_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["args"] = json.loads(d.pop("args_json"))
        d["preview"] = json.loads(d.pop("preview_json"))
        d["expired"] = time.time() > d["expires_at"]
        prj = d.pop("provider_result_json", None)
        d["provider_result"] = json.loads(prj) if prj else None
        return d

    def list_pending(self) -> List[Dict[str, Any]]:
        now = time.time()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status=? AND expires_at > ?"
                " ORDER BY created_at DESC", (PENDING, now),
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["args"] = json.loads(d.pop("args_json"))
            d["preview"] = json.loads(d.pop("preview_json"))
            out.append(d)
        return out

    def _decide(self, request_id: str, status: str, by: str) -> bool:
        """Transizione pending -> approved/rejected, atomica: solo la prima
        decisione vince, anche se console e CLI arrivano insieme."""
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status=?, decided_at=?, decided_by=?"
                " WHERE request_id=? AND status=? AND expires_at > ?",
                (status, now, by, request_id, PENDING, now),
            )
            return cur.rowcount == 1

    def approve(self, request_id: str, by: str = "unknown") -> bool:
        """Chiamata SOLO dalla console o dalla CLI — mai da un tool MCP.
        `by` identifica il canale e l'utente di sistema che ha approvato."""
        rec = self.get(request_id)
        ok = self._decide(request_id, APPROVED, by)
        audit("approval", {"request_id": request_id, "by": by,
                           "for_tool": (rec or {}).get("tool")},
              "approved" if ok else "approve_failed")
        return ok

    def reject(self, request_id: str, by: str = "unknown") -> bool:
        rec = self.get(request_id)
        ok = self._decide(request_id, REJECTED, by)
        audit("approval", {"request_id": request_id, "by": by,
                           "for_tool": (rec or {}).get("tool")},
              "rejected" if ok else "reject_failed")
        return ok

    def revoke(self, request_id: str, by: str = "unknown") -> bool:
        """Ritira un'approvazione GIA' DATA ma non ancora eseguita.

        Serve al caso piu' banale e piu' frequente: si approva, e un
        secondo dopo ci si accorge che la mail era sbagliata. Senza
        questo l'unica difesa era aspettare i 15 minuti di scadenza,
        con la richiesta eseguibile per tutta la finestra.

        Va nella direzione sicura — impedisce un'azione, non la
        autorizza — quindi non chiede Hello: e' la stessa asimmetria
        per cui su Telegram si puo' rifiutare ma non approvare.

        Atomica rispetto a consume_approved(): entrambe passano da una
        UPDATE condizionale sullo stato, quindi se revoca ed esecuzione
        arrivano insieme una delle due perde e lo sa. Cio' che e' gia'
        EXECUTED non si tocca: quella mail e' partita, e fingere di
        annullarla sarebbe peggio che dire di no."""
        rec = self.get(request_id)
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status=?, decided_at=?, decided_by=?"
                " WHERE request_id=? AND status IN (?,?)",
                (REJECTED, now, by, request_id, PENDING, APPROVED),
            )
            ok = cur.rowcount == 1
        audit("approval", {"request_id": request_id, "by": by,
                           "was": (rec or {}).get("status"),
                           "for_tool": (rec or {}).get("tool")},
              "revoked" if ok else "revoke_failed")
        return ok

    def consume_approved(self, request_id: str, tool: str) -> Optional[Dict[str, Any]]:
        """Consuma ATOMICAMENTE un'approvazione: la transizione
        approved -> executed avviene in una sola UPDATE condizionale, e solo
        chi la vince ottiene gli argomenti canonici.

        Non e' pedanteria: con SELECT-poi-UPDATE due chiamate concorrenti
        dello stesso request_id vedrebbero entrambe 'approved' ed
        eseguirebbero due volte la stessa azione approvata una volta sola —
        due mail identiche al cliente, o due cancellazioni.
        """
        now = time.time()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE approvals SET status=? WHERE request_id=? AND tool=?"
                " AND status=? AND expires_at > ?",
                (EXECUTED, request_id, tool, APPROVED, now),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            row = conn.execute(
                "SELECT args_json FROM approvals WHERE request_id=?", (request_id,)
            ).fetchone()
            conn.commit()
        finally:
            conn.close()
        return json.loads(row["args_json"])

    def record_outcome(self, request_id: str, outcome: str,
                       provider_result: Optional[Dict[str, Any]] = None) -> None:
        """Scrive sulla riga gia' EXECUTED cosa e' successo davvero:
        outcome in {ok, failed, interrupted, dryrun} + risposta del provider.
        Separato da consume: la riga e' gia' consumata PRIMA della chiamata
        al provider (at-most-once); questo la completa dopo."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE approvals SET execution_outcome=?, provider_result_json=?"
                " WHERE request_id=?",
                (outcome,
                 json.dumps(provider_result, ensure_ascii=False, default=str)
                 if provider_result is not None else None,
                 request_id),
            )

    def purge_expired(self) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM approvals WHERE expires_at < ? AND status IN (?,?)",
                (time.time() - 86400, PENDING, REJECTED),
            )
            return cur.rowcount


_store: Optional[ApprovalStore] = None


def store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store


def set_store(new_store: ApprovalStore) -> None:
    """Usata dai test per isolare il database."""
    global _store
    _store = new_store


def dry_run_active() -> bool:
    """ADE_MAIL_DRYRUN=1: le azioni approvate NON vengono eseguite davvero,
    ma percorrono tutta la policy e finiscono nell'audit come
    'dryrun_executed'. Usata dall'harness anti-injection."""
    return os.environ.get("ADE_MAIL_DRYRUN", "") not in ("", "0", "false")


def _notify_command() -> Optional[List[str]]:
    """Comando di notifica configurato: JSON array con placeholder
    {request_id}, {tool}, {summary}, {message} ({message} = testo completo
    leggibile, es. per Telegram via curl:
      ["curl","-s","https://api.telegram.org/bot<TOKEN>/sendMessage",
       "-d","chat_id=<ID>","--data-urlencode","text={message}"]).
    Sorgenti, in ordine: env GIGAMAIL_APPROVAL_NOTIFY_CMD, poi il file
    notify.json accanto ad agent.json ({"command": [...]}) — cosi' la
    configurazione sopravvive al riavvio senza env vars.
    Eseguito SENZA shell (argomenti separati: il testo della preview non puo'
    diventare un comando), in background, con timeout, e il suo esito non
    influenza mai la fase 1. SOLO NOTIFICA: non approva, non puo' approvare —
    altrimenti sposterebbe il segreto digitabile dalla shell alla chat."""
    def _valid(cmd):
        return (isinstance(cmd, list) and cmd
                and all(isinstance(c, str) for c in cmd))

    raw = os.environ.get("GIGAMAIL_APPROVAL_NOTIFY_CMD", "").strip()
    if raw:
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return cmd if _valid(cmd) else None
    try:
        # utf-8-sig: Notepad e Out-File di Windows salvano col BOM, e il
        # file lo edita l'utente a mano — non deve rompersi per questo.
        with open(_ade_root() / "notify.json", encoding="utf-8-sig") as f:
            cmd = (json.load(f) or {}).get("command")
        return cmd if _valid(cmd) else None
    except Exception:
        return None


def _summarize_preview(preview: Dict[str, Any], limit: int = 160) -> str:
    parts = []
    for k in ("to", "subject", "replying_to", "action", "folder_id", "event_id", "start"):
        v = preview.get(k)
        if v:
            parts.append(f"{k}={v}")
    s = "; ".join(str(p) for p in parts) or json.dumps(preview, ensure_ascii=False, default=str)
    return s[:limit]


def user_lang() -> str:
    """Lingua in cui GigaMail parla ALL'UMANO (notifiche): quella del suo
    sistema, override con GIGAMAIL_LANG. Oggi 'it' o 'en' (default).
    La lingua delle RISPOSTE email non c'entra: quella la sceglie l'agente
    dalla mail in arrivo."""
    forced = os.environ.get("GIGAMAIL_LANG", "").strip().lower()
    if forced:
        return "it" if forced.startswith("it") else "en"
    try:
        import locale
        loc = (locale.getlocale()[0] or "")
        if not loc:
            loc = locale.getdefaultlocale()[0] or ""
        return "it" if str(loc).lower().startswith("it") else "en"
    except Exception:
        return "en"


def toast_actions(request_id: str) -> List[tuple]:
    """I bottoni della toast di approvazione: [(etichetta, url)].

    Ogni bottone APRE soltanto un URL gigamail:// che lancia la CLI —
    "Approva" fa comunque passare da Windows Hello. Nessun bottone decide
    da solo. Sono qui, e non nel chiamante, perche' ogni richiesta di
    approvazione (tool MCP o regola del watcher) deve mostrare gli stessi
    quattro: senza `actions` la toast esce muta e l'umano vede l'avviso ma
    non ha niente da premere."""
    it = user_lang() == "it"
    return [
        ("👁 " + ("Leggi" if it else "Read"),
         f"gigamail://show/{request_id}"),
        ("✅ " + ("Approva" if it else "Approve"),
         f"gigamail://approve/{request_id}"),
        ("✏️ " + ("Modifica" if it else "Edit"),
         f"gigamail://edit/{request_id}"),
        ("❌ " + ("Rifiuta" if it else "Reject"),
         f"gigamail://reject/{request_id}"),
    ]


# Telegram taglia a 4096 caratteri; sotto quel tetto ci sta una mail
# vera con intestazioni e corpo.
_TG_TEXT_MAX = 3500


def full_preview_text(tool: str, preview: Dict[str, Any],
                      limit: int = _TG_TEXT_MAX) -> str:
    """L'anteprima INTERA, per i canali che possono mostrarla.

    La toast resta corta perche' ha il bottone Leggi, che apre tutto.
    Telegram quel secondo passo non ce l'ha: se il corpo non e' nel
    messaggio non lo si vede da nessuna parte, e si finisce ad
    approvare una mail di cui si e' letto solo l'oggetto.
    """
    it = user_lang() == "it"
    righe = []
    intestazioni = (("from", "Da"), ("to", "A"), ("cc", "Cc"),
                    ("bcc", "Ccn"), ("subject", "Oggetto"))
    for chiave, etichetta in intestazioni:
        v = preview.get(chiave)
        if v:
            righe.append(f"{etichetta}: {v if not isinstance(v, list) else ', '.join(map(str, v))}")
    allegati = preview.get("attachments") or []
    if allegati:
        nomi = [a.get("name", "?") if isinstance(a, dict) else str(a)
                for a in allegati]
        righe.append(("Allegati: " if it else "Attachments: ")
                     + ", ".join(nomi))
    rispondendo = preview.get("replying_to")
    if rispondendo:
        righe.append(f"In risposta a: {rispondendo}")
    testa = chr(10).join(righe)
    corpo = str(preview.get("body") or "")
    if not testa and not corpo:
        return _summarize_preview(preview)
    avanzo = max(200, limit - len(testa) - 40)
    if len(corpo) > avanzo:
        corpo = corpo[:avanzo] + ("… [troncato]" if it else "… [truncated]")
    if corpo:
        return testa + chr(10) + chr(10) + corpo
    return testa


def telegram_buttons(request_id: str):
    """Gli stessi tre bottoni delle bozze da regola, anche per le
    richieste nate da un tool: senza, il messaggio Telegram arrivava
    muto e l'unica cosa tappabile era l'indirizzo del destinatario.
    None se Telegram non e' configurato."""
    try:
        from ade_mail_agent.core import telegram_channel
        tg = telegram_channel.channel()
        if not tg:
            return None
        return tg.action_buttons(request_id, user_lang(),
                                 bool(getattr(tg, "approve_enabled", False)))
    except Exception:
        return None


def notify_approval_requested(request_id: str, tool: str, preview: Dict[str, Any],
                              message: Optional[str] = None,
                              buttons: Optional[List[List[Dict[str, str]]]] = None,
                              actions: Optional[List[tuple]] = None) -> bool:
    """Notifica l'umano su TUTTI i canali configurati: desktop (toast di
    sistema, attiva di default), Telegram nativo (blocco "telegram" in
    notify.json, con `buttons` = tastiera inline sotto il messaggio) e il
    comando generico configurato (openclaw, curl...). `message` e' il testo
    completo leggibile ("e' arrivata una mail da X, propongo questa
    risposta... approvi?"); se assente si genera dal riassunto della
    preview. Ritorna True se almeno un canale e' partito. Mai eccezioni
    verso il chiamante, mai bloccante."""
    summary = _summarize_preview(preview)
    if message:
        text = message
    elif user_lang() == "it":
        text = f"GigaMail: {tool} in attesa di approvazione — {summary}"
    else:
        text = f"GigaMail: {tool} awaiting approval — {summary}"

    fired = False
    try:
        from ade_mail_agent.core import desktop_notify
        # `actions` = bottoni sulla toast: aprono gigamail://approve/<id>
        # (→ CLI → Hello), non approvano da soli. `expires_in` e' la
        # scadenza VERA della richiesta: la notifica dura quanto
        # l'approvazione, non un tempo suo scelto altrove.
        if desktop_notify.notify("GigaMail", text, actions=actions,
                                 expires_in=_APPROVAL_TTL_SECONDS):
            fired = True
    except Exception:
        pass

    try:
        from ade_mail_agent.core import telegram_channel
        tg = telegram_channel.channel()
        if tg:
            import threading
            # safe_html: in un'approvazione l'unica cosa tappabile non
            # deve essere il mailto' del destinatario (apre il client di
            # posta e chiede un login). Tappabili solo i bottoni.
            # Su Telegram va l'anteprima intera: `text` e' il riassunto
            # per la toast, che pero' ha Leggi. Se una regola ha gia'
            # scritto il suo messaggio (`message`), quello vince.
            lungo = text if message else full_preview_text(tool, preview)
            testo_tg = telegram_channel.Telegram.safe_html(lungo)
            threading.Thread(
                target=lambda: tg.send(testo_tg, buttons=buttons,
                                       html=True),
                daemon=False).start()
            audit(tool, {"request_id": request_id}, "approval_notified",
                  detail="telegram")
            fired = True
    except Exception:
        pass

    cmd = _notify_command()
    if cmd:
        argv = [c.replace("{request_id}", request_id).replace("{tool}", tool)
                 .replace("{summary}", summary).replace("{message}", text)
                for c in cmd]
        try:
            import subprocess
            import threading

            def _run():
                try:
                    subprocess.run(argv, timeout=30, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass  # la notifica e' best-effort

            # NON daemon: il comando di notifica deve sopravvivere all'uscita
            # di un processo breve (watch --once, CLI) — un daemon thread
            # verrebbe ucciso a meta' curl.
            threading.Thread(target=_run, daemon=False).start()
            audit(tool, {"request_id": request_id}, "approval_notified",
                  detail=argv[0])
            fired = True
        except Exception:
            pass
    return fired


# Diniego ESPLICITO quando lo store delle approvazioni non e' raggiungibile.
#
# Perche' non basta lasciar propagare l'eccezione (r/mcp, ranbuman, 2026-08-21):
# un'eccezione nuda da uno store mancante sembra esattamente un bug, e il
# prossimo che la vede nei log la avvolge in un try/except per zittire il
# rumore — cosi' il gate diventa fail-open dentro un commit che si legge come
# pulizia. Un diniego con un suo codice non e' sicurezza migliore oggi: e'
# cio' che impedisce a quel commit di essere scritto l'anno prossimo.
# I test in tests/test_store_unavailable.py lo tengono vero.
STORE_UNAVAILABLE = "store_unavailable"


def _deny_store_unavailable(tool: str, err: Exception) -> Dict[str, Any]:
    """Risposta deliberata, non un crash: nessuna richiesta creata, nessuna
    azione eseguita. Il chiamante NON deve mai proseguire dopo questo."""
    try:
        audit(tool, {}, "approval_store_unavailable", detail=str(err))
    except Exception:
        pass  # se non si puo' nemmeno scrivere l'audit, il diniego resta
    return {
        "status": STORE_UNAVAILABLE,
        "request_id": None,
        "instructions": (
            "Archivio delle approvazioni non raggiungibile: NIENTE e' stato "
            "creato ne' eseguito, di proposito. Non e' un errore transitorio "
            "da riprovare in loop: avvisa l'utente, che deve controllare "
            "l'installazione di GigaMail. Senza archivio non esiste "
            "approvazione, quindi non esiste esecuzione."
        ),
    }


def request_approval(tool: str, args: Dict[str, Any],
                     preview: Dict[str, Any]) -> Dict[str, Any]:
    """Fase 1: registra la richiesta e restituisce all'agente un riferimento
    INERTE. Nessun segreto attraversa il contesto del modello.

    Cap (promesso su r/mcp): lo stesso payload con una pending viva non
    crea una seconda richiesta — torna la stessa request_id; e oltre N
    richieste per tool nell'ultima ora la fase 1 rifiuta. Un agente che
    insiste non puo' produrre una raffica di approvazioni identiche."""
    s = store()
    try:
        existing = s.find_pending(tool, args)
    except Exception as e:
        return _deny_store_unavailable(tool, e)
    if existing:
        audit(tool, {"request_id": existing}, "approval_request_deduplicated")
        return {
            "status": "approval_required",
            "request_id": existing,
            "preview": preview,
            "deduplicated": True,
            "expires_in_seconds": _APPROVAL_TTL_SECONDS,
            "instructions": (
                "Questa identica richiesta e' GIA' in attesa di approvazione "
                "umana (stessa request_id). Non ricrearla: chiedi all'utente "
                "di approvare dalla console GigaMail o con `gigamail approvals "
                "approve " + existing + "`."
            ),
        }
    try:
        recenti = s.count_created_since(tool, time.time() - 3600)
    except Exception as e:
        return _deny_store_unavailable(tool, e)
    if recenti >= _APPROVAL_MAX_PER_HOUR:
        audit(tool, args, "approval_rate_limited")
        return {
            "status": "rate_limited",
            "request_id": None,
            "instructions": (
                f"Troppe richieste di approvazione per {tool} nell'ultima ora "
                f"(limite {_APPROVAL_MAX_PER_HOUR}). Nessuna nuova richiesta "
                "creata. Fermati e chiedi all'utente cosa vuole fare: insistere "
                "non produce approvazioni."
            ),
        }
    try:
        request_id = s.create(tool, args, preview)
    except Exception as e:
        return _deny_store_unavailable(tool, e)
    audit(tool, args, "approval_requested")
    notify_approval_requested(request_id, tool, preview,
                              actions=toast_actions(request_id),
                              buttons=telegram_buttons(request_id))
    return {
        "status": "approval_required",
        "request_id": request_id,
        "preview": preview,
        "expires_in_seconds": _APPROVAL_TTL_SECONDS,
        "instructions": (
            "AZIONE NON ESEGUITA. Non puoi approvarla tu: serve un umano, dalla "
            "console GigaMail o con `gigamail approvals approve " + request_id +
            "`. Mostra l'anteprima all'utente, chiedi che approvi, poi richiama "
            "questo tool con request_id per completare. Finche' non approva, "
            "richiamarlo non esegue nulla."
        ),
    }


def execute_dangerous(
    tool: str,
    args: Dict[str, Any],
    request_id: Optional[str],
    preview_fn: Callable[[], Dict[str, Any]],
    execute_fn: Callable[[Dict[str, Any]], Any],
) -> Any:
    """Orchestrazione di un tool DANGEROUS con approvazione fuori banda."""
    if not request_id:
        return request_approval(tool, args, preview_fn())

    try:
        record = store().get(request_id)
    except Exception as e:
        return _deny_store_unavailable(tool, e)
    if record is None or record["tool"] != tool:
        audit(tool, {"request_id": request_id}, "approval_invalid")
        raise ValueError(
            f"request_id '{request_id}' inesistente o di un altro tool. "
            "Richiama il tool senza request_id per creare una nuova richiesta."
        )
    if record["expired"] and record["status"] not in (EXECUTED,):
        audit(tool, {"request_id": request_id}, "approval_expired")
        raise ValueError("Richiesta scaduta: creane una nuova e falla approvare.")
    if record["status"] == PENDING:
        audit(tool, {"request_id": request_id}, "approval_still_pending")
        return {
            "status": "awaiting_approval",
            "request_id": request_id,
            "preview": record["preview"],
            "instructions": (
                "Ancora in attesa di approvazione umana. NON e' stato eseguito "
                "nulla. Non insistere: chiedi all'utente di approvare dalla "
                "console GigaMail o con `gigamail approvals approve " +
                request_id + "`."
            ),
        }
    if record["status"] == REJECTED:
        audit(tool, {"request_id": request_id}, "approval_rejected")
        return {"status": "rejected", "request_id": request_id,
                "instructions": "L'utente ha rifiutato questa azione. Non riproporla."}
    if record["status"] == EXECUTED:
        audit(tool, {"request_id": request_id}, "approval_already_used")
        raise ValueError("Questa richiesta e' gia' stata eseguita.")

    try:
        canonical_args = store().consume_approved(request_id, tool)
    except Exception as e:
        return _deny_store_unavailable(tool, e)
    if canonical_args is None:
        audit(tool, {"request_id": request_id}, "approval_invalid")
        raise ValueError("Approvazione non piu' valida.")

    if dry_run_active():
        store().record_outcome(request_id, "dryrun")
        audit(tool, canonical_args, "dryrun_executed")
        return {"dryrun": True, "tool": tool,
                "note": "ADE_MAIL_DRYRUN attivo: azione NON eseguita"}
    # La riga e' gia' EXECUTED (consumata) da consume_approved: at-most-once.
    # Da qui in poi registriamo cosa e' successo DAVVERO — sulla riga e
    # nell'audit — perche' "consumata" non vuol dire "consegnata".
    try:
        result = execute_fn(canonical_args)
    except Exception as e:
        store().record_outcome(request_id, "failed", {"error": str(e)})
        audit(tool, canonical_args, "error", str(e))
        raise
    provider_result = result.get("provider_result") if isinstance(result, dict) else None
    ok = (result.get("success", True) if isinstance(result, dict) else bool(result))
    store().record_outcome(request_id, "ok" if ok else "failed", provider_result)
    audit(tool, canonical_args, "executed" if ok else "executed_with_error",
          detail="" if ok else str((result or {}).get("error", "")),
          provider_result=provider_result)
    return result
