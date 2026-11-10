"""Automazioni (0.2.1): regole di risposta e watcher (processo separato)."""
import os
import threading
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from gigamail import policy

from .common import _active_id, _who

router = APIRouter()


# ── AUTOMAZIONI (0.2.1): regole, watcher, notifiche ──────────────────
# La console e' la UI umana delle regole di risposta. Stesso vincolo degli
# approvals: creare o riattivare una regola e' una PRE-approvazione, quindi
# passa da consent.require_human (Hello) qui nel backend — il token della
# console sta in un file, il prompt OS no. Pausa/elimina sono liberi.
# Il token Telegram NON passa da qui: solo CLI (`gigamail telegram setup`).

class RuleCreate(BaseModel):
    account_id: Optional[int] = None
    trigger_kind: str            # senders | folder
    trigger_values: List[str]
    reply_style: str = ""
    doc_paths: List[str] = []
    mode: str = "semi"           # semi | auto
    first_contact: str = "semi"
    daily_cap: int = 10
    cooldown_hours: float = 4.0
    expiry_days: float = 30.0
    cc: List[str] = []
    attachments: List[str] = []   # names of files registered in the identity


class RuleUpdate(BaseModel):
    """What Edit on a rule card can change. Every field is optional: only
    the ones sent are changed."""
    trigger_kind: Optional[str] = None
    trigger_values: Optional[List[str]] = None
    reply_style: Optional[str] = None
    doc_paths: Optional[List[str]] = None
    mode: Optional[str] = None
    first_contact: Optional[str] = None
    daily_cap: Optional[int] = None
    cooldown_hours: Optional[float] = None
    cc: Optional[List[str]] = None
    attachments: Optional[List[str]] = None


def _clean_trigger(kind: str, values: List[str]) -> List[str]:
    return [v.strip().lower() if kind == "senders" else v.strip()
            for v in values if v and v.strip()]


def _clean_docs(paths: List[str]) -> List[str]:
    docs = []
    for pth in paths or []:
        pth = os.path.abspath(pth)
        if not os.path.exists(pth):
            raise HTTPException(400, f"Documento inesistente: {pth}")
        docs.append(pth)
    return docs


def _clean_attachments(account_id: int, names: List[str]) -> List[str]:
    """Fixed attachments are names of files registered in the identity:
    a name that resolves to nothing is refused now, not discovered in a
    month when the rule fires and the mail goes without it."""
    names = [n.strip() for n in names or [] if n and n.strip()]
    if not names:
        return []
    from gigamail.core import attachments as attachments_mod
    _resolved, missing = attachments_mod.resolve(account_id, names)
    if missing:
        raise HTTPException(400, "Allegati non registrati nell'identity: "
                            + ", ".join(missing))
    return names


def _require_human_or_http(reason: str) -> None:
    from gigamail import consent
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if not ok:
        raise HTTPException(403, "Verifica utente non superata o annullata")


def _rule_view(r: dict) -> dict:
    from gigamail.core import rules as rules_mod
    rs = rules_mod.store()
    d = dict(r)
    d["sent_today"] = rs.sent_today(r["rule_id"])
    d["state"] = ("paused" if r["paused"] else
                  "expired" if r["expired"] else "active")
    return d


class DocumentsCheck(BaseModel):
    paths: List[str] = []


@router.post("/documents/check")
def check_documents(body: DocumentsCheck):
    """What the agent will not read well in these documents: too long,
    several sheets, no text, unreadable, slow. Numbers only, never the
    content. Asked by the rule form when a document is picked and by the
    rule cards, so a document that gives poor drafts says so at once."""
    from gigamail.core import doc_check
    return doc_check.check_many(body.paths[:50])


@router.get("/rules")
def list_rules():
    from gigamail.core import rules as rules_mod
    return [_rule_view(r) for r in rules_mod.store().list_all()]


@router.post("/rules")
def create_rule(body: RuleCreate):
    """Crea una regola. Hello obbligatorio: e' una pre-approvazione."""
    import time as _t

    from gigamail.core import rules as rules_mod
    aid = body.account_id or _active_id()
    if not aid:
        raise HTTPException(400, "Nessun account")
    if body.trigger_kind not in rules_mod.TRIGGER_KINDS:
        raise HTTPException(400, "trigger_kind non valido")
    if body.mode not in rules_mod.MODES or body.first_contact not in rules_mod.MODES:
        raise HTTPException(400, "mode/first_contact non validi")
    values = _clean_trigger(body.trigger_kind, body.trigger_values)
    if not values:
        raise HTTPException(400, "trigger vuoto")
    docs = _clean_docs(body.doc_paths)
    attachments = _clean_attachments(aid, body.attachments)
    cc = [v.strip() for v in body.cc or [] if v and v.strip()]
    _require_human_or_http(
        f"GigaMail: creare la regola {body.mode.upper()} per {', '.join(values)}?")
    rule_id = rules_mod.store().create(
        account_id=aid, trigger_kind=body.trigger_kind, trigger_values=values,
        reply_style=body.reply_style, doc_paths=docs, mode=body.mode,
        first_contact=body.first_contact, daily_cap=body.daily_cap,
        cooldown_hours=body.cooldown_hours, expiry_days=body.expiry_days,
        created_by=_who(), hello_verified_at=_t.time(),
        cc=cc, attachments=attachments)
    policy.audit("rule", {"rule_id": rule_id, "mode": body.mode, "trigger": values},
                 "rule_created", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdate):
    """Edit on a rule card: the instruction, trigger, documents, fixed
    attachments or limits change in place, so a wrong detail in a rule
    (a phone number, the floor plans it always attaches) is corrected
    without deleting the rule and losing what it handled. Changing a rule
    is approving another one: Hello, as for creating it. The rule keeps
    its state and expiry."""
    import time as _t

    from gigamail.core import rules as rules_mod
    rule = rules_mod.store().get(rule_id)
    if not rule:
        raise HTTPException(404, "Regola inesistente")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "nothing to change")
    kind = fields.get("trigger_kind", rule["trigger_kind"])
    if kind not in rules_mod.TRIGGER_KINDS:
        raise HTTPException(400, "trigger_kind non valido")
    if "trigger_values" in fields or "trigger_kind" in fields:
        fields["trigger_kind"] = kind
        fields["trigger_values"] = _clean_trigger(
            kind, fields.get("trigger_values", rule["trigger_values"]))
        if not fields["trigger_values"]:
            raise HTTPException(400, "trigger vuoto")
    for key in ("mode", "first_contact"):
        if fields.get(key, "semi") not in rules_mod.MODES:
            raise HTTPException(400, "mode/first_contact non validi")
    if "doc_paths" in fields:
        fields["doc_paths"] = _clean_docs(fields["doc_paths"])
    if "attachments" in fields:
        fields["attachments"] = _clean_attachments(rule["account_id"], fields["attachments"])
    if "cc" in fields:
        fields["cc"] = [v.strip() for v in fields["cc"] if v and v.strip()]
    _require_human_or_http(
        f"GigaMail: modificare la regola {rule_id} ({', '.join(sorted(fields))})?"
        if policy.user_lang() == "it" else
        f"GigaMail: change rule {rule_id} ({', '.join(sorted(fields))})?")
    try:
        rules_mod.store().update(rule_id, _t.time(), **fields)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    policy.audit("rule", {"rule_id": rule_id, "fields": sorted(fields)},
                 "rule_updated", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.post("/rules/{rule_id}/pause")
def pause_rule(rule_id: str):
    from gigamail.core import rules as rules_mod
    if not rules_mod.store().pause(rule_id, "pausa dalla console"):
        raise HTTPException(404, "Regola inesistente")
    policy.audit("rule", {"rule_id": rule_id}, "rule_paused", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.post("/rules/{rule_id}/resume")
def resume_rule(rule_id: str):
    """Riattivare = ri-approvare: Hello."""
    import time as _t

    from gigamail.core import rules as rules_mod
    if not rules_mod.store().get(rule_id):
        raise HTTPException(404, "Regola inesistente")
    _require_human_or_http(f"GigaMail: riattivare la regola {rule_id}?")
    rules_mod.store().resume(rule_id, _t.time())
    policy.audit("rule", {"rule_id": rule_id}, "rule_resumed", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.post("/rules/{rule_id}/renew")
def renew_rule(rule_id: str):
    """Another period of the rule's length from now. Renewing is approving
    again: Hello, as for creating it."""
    import time as _t

    from gigamail.core import rules as rules_mod
    rule = rules_mod.store().get(rule_id)
    if not rule:
        raise HTTPException(404, "Regola inesistente")
    days = int(rule["expiry_days"])
    _require_human_or_http(
        f"GigaMail: rinnovare la regola {rule_id} per {days} giorni?"
        if policy.user_lang() == "it" else
        f"GigaMail: renew rule {rule_id} for {days} days?")
    expires_at = rules_mod.store().renew(rule_id, _t.time())
    policy.audit("rule", {"rule_id": rule_id, "expires_at": expires_at},
                 "rule_renewed", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    from gigamail.core import rules as rules_mod
    if not rules_mod.store().delete(rule_id):
        raise HTTPException(404, "Regola inesistente")
    policy.audit("rule", {"rule_id": rule_id}, "rule_deleted", detail=_who())
    return {"success": True}


@router.get("/rules/{rule_id}/activity")
def rule_activity(rule_id: str, limit: int = 30):
    """Le mail che la regola ha guardato, con esito."""
    from gigamail.core import rules as rules_mod
    rs = rules_mod.store()
    with rs._conn() as conn:
        rows = conn.execute(
            "SELECT message_id, sender, status, reason, request_id, ts"
            " FROM handled WHERE rule_id=? ORDER BY ts DESC LIMIT ?",
            (rule_id, int(limit))).fetchall()
    return [dict(r) for r in rows]


# --- watcher: processo separato, avviato/fermato dal backend ---------------

def _watch_state() -> dict:
    """Delega al watcher: la console non tiene una sua idea di "attivo"."""
    from gigamail.watcher import running_state
    return {**running_state(), "archive_accounts": _archive_accounts()}


def _archive_accounts() -> int:
    """Accounts the watcher archives on every tick: all but the demo."""
    from gigamail.core import accounts as core_accounts
    try:
        return sum(1 for a in core_accounts.get_accounts() if a.get("type") != "demo")
    except Exception:
        return 0


def _pid_alive(pid: int) -> bool:
    from gigamail.watcher import pid_alive
    return pid_alive(pid)

@router.get("/watch/status")
def watch_status():
    return _watch_state()


def _spawn_watch(interval: int) -> int:
    """`gigamail watch` come processo staccato (sopravvive alla console),
    log in app_root()/watch.log. Ritorna il pid."""
    import subprocess
    import sys as _sys

    from gigamail.core import rules as rules_mod
    from gigamail.core.data_paths import app_root
    log_path = os.path.join(str(app_root()), "watch.log")
    log = open(log_path, "a", encoding="utf-8")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [_sys.executable, "-u", "-m", "gigamail.cli", "watch",
         "--verbose", "--interval", str(max(int(interval), 10))],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        env=dict(os.environ), **kwargs)
    rules_mod.store().kv_set("watch_pid", str(proc.pid))
    _SPAWNED[proc.pid] = proc
    _SPAWNED_AT[proc.pid] = time.time()
    return proc.pid


# Every watcher this backend started and may still be running. The handle,
# not just the pid: Windows reuses pids, and a stale pid in rules.db could
# name somebody else's process by the time it gets killed.
_SPAWNED: dict = {}
_SPAWNED_AT: dict = {}
# A new watcher has no heartbeat yet: imports alone take many seconds on a
# slow disk. Taken for hung, it was ended every eleven seconds and never ran.
WATCH_START_GRACE_SECONDS = 180


def _forget_spawned(pid: int) -> None:
    _SPAWNED.pop(pid, None)
    _SPAWNED_AT.pop(pid, None)


def _still_starting() -> Optional[int]:
    """The pid of a watcher started moments ago and still running."""
    for pid, proc in _SPAWNED.items():
        if proc.poll() is None \
                and time.time() - _SPAWNED_AT.get(pid, 0) < WATCH_START_GRACE_SECONDS:
            return pid
    return None


def _stop_left_behind() -> bool:
    """Ends the watchers this backend started that are still running, before
    it starts another. A watcher stuck inside a tick stops beating and looks
    dead, but it only checks whether to give way between ticks, so it never
    leaves: the guard started a new one every few minutes, and seven of them
    were found working the same mail. False when one could not be ended: no
    new watcher then, the guard tries again in a minute."""
    for pid, proc in list(_SPAWNED.items()):
        if proc.poll() is None:
            try:
                _stop_watch_process(pid)
            except Exception as e:
                policy.audit("watch", {"pid": pid}, "watch_stop_failed", detail=str(e)[:200])
                return False
            policy.audit("watch", {"pid": pid}, "watch_hung_stopped")
        _forget_spawned(pid)
    return True


# kv flag: the user pressed Stop. The guard that restarts a dead watcher
# must not undo a stop someone chose; only an explicit start (the button,
# or `gigamail watch` by hand) clears it. Written BEFORE the process is
# ended, under the same lock the guard takes: a guard that woke up between
# the kill and the flag used to start a watcher again.
USER_STOPPED_KEY = "watch_user_stopped"
_WATCH_LOCK = threading.RLock()


@router.post("/watch/start")
def watch_start(interval: int = 60):
    from gigamail.core import rules as rules_mod
    with _WATCH_LOCK:
        rules_mod.store().kv_set(USER_STOPPED_KEY, "0")
        st = _watch_state()
        if st["running"]:
            return st
        starting = _still_starting()
        if starting:
            return {**st, "running": True, "pid": starting}
        if not _stop_left_behind():
            raise HTTPException(500, "a previous watcher could not be stopped")
        pid = _spawn_watch(interval)
        policy.audit("watch", {"pid": pid, "interval": interval}, "watch_started",
                     detail=_who())
        return {"running": True, "pid": pid, "interval": interval,
                "last_tick_age_seconds": None, "active_rules": st["active_rules"]}


def watch_autostart() -> Optional[int]:
    """A watcher that should be running, and is not, is started; one that
    runs OLD code (its code stamp differs from the sources on disk: an
    update, a git pull) is stopped and started again, so the new code
    runs without anyone pressing Stop and Start. The watcher is its own
    process: before, only the button in Automations brought it back, and
    a mail a rule should have answered waited until someone noticed.
    Returns the new pid, or None when nothing was started."""
    with _WATCH_LOCK:
        return _watch_autostart_locked()


def _watch_autostart_locked() -> Optional[int]:
    from gigamail.core import rules as rules_mod
    from gigamail.core.code_stamp import code_stamp
    st = _watch_state()
    # Rules are not the only job: every tick also fills the local archive
    # that search and the agents read.
    if not st["active_rules"] and not st.get("archive_accounts"):
        return None
    if rules_mod.store().kv_get(USER_STOPPED_KEY, "0") == "1":
        return None    # stopped on purpose: Start is the user's to press
    reason = "backend start"
    if st["running"]:
        stamp = st.get("code_stamp") or ""
        if not stamp or stamp == code_stamp():
            return None
        try:
            _stop_watch_process(int(st["pid"]))
        except Exception as e:
            policy.audit("watch", {"pid": st["pid"]}, "watch_restart_failed", detail=str(e)[:200])
            return None
        _forget_spawned(int(st["pid"]))
        rules_mod.store().kv_set("watch_heartbeat", "0")
        reason = "code changed"
    elif _still_starting():
        return None
    if not _stop_left_behind():
        return None
    interval = int(rules_mod.store().kv_get("watch_interval", "60") or 60)
    pid = _spawn_watch(interval)
    policy.audit("watch", {"pid": pid, "interval": interval},
                 "watch_restarted" if reason == "code changed" else "watch_autostarted",
                 detail=reason)
    return pid


WATCH_GUARD_SECONDS = 60


def start_watch_guard(interval: int = WATCH_GUARD_SECONDS) -> None:
    """A daemon thread of the backend: watch_autostart now and every
    minute, and the sweep of approved requests nobody sent. Covers the
    watcher dying at any time, an update landing while the backend keeps
    running (the console reuses a live backend), and an approval that
    an older backend recorded without executing it."""
    import threading

    from gigamail import completion

    def _loop():
        while True:
            try:
                pid = watch_autostart()
                if pid:
                    print(f"[console] watcher started (pid {pid})", flush=True)
            except Exception as e:
                print(f"[console] watcher guard: {e}", flush=True)
            # Approved and never sent (an approval an older backend took,
            # or one lost half-way): completed here, not left for good.
            try:
                for rep in completion.complete_left_behind():
                    print(f"[console] approved request {rep['request_id']} resumed:"
                          f" {rep.get('outcome') or rep.get('status')}"
                          f"{' ' + rep['error'] if rep.get('error') else ''}", flush=True)
            except Exception as e:
                print(f"[console] approvals sweep: {e}", flush=True)
            time.sleep(interval)

    threading.Thread(target=_loop, name="watch-guard", daemon=True).start()


def _stop_watch_process(pid: int, wait: float = 10.0) -> None:
    """Ends the watcher and its children (on Windows the venv's python.exe
    is a launcher: without /T its child kept running, and the restarted
    watcher ran next to the old one), then waits for it to be gone."""
    if os.name == "nt":
        import subprocess
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=15)
    else:
        import signal
        os.kill(pid, signal.SIGTERM)
    deadline = time.time() + wait
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.2)


@router.post("/watch/stop")
def watch_stop():
    from gigamail.core import rules as rules_mod
    with _WATCH_LOCK:
        rs = rules_mod.store()
        rs.kv_set(USER_STOPPED_KEY, "1")   # first: the guard reads it before it starts anything
        pid = int(rs.kv_get("watch_pid", "0") or 0)
        if pid and _pid_alive(pid):
            try:
                _stop_watch_process(pid)
            except Exception as e:
                raise HTTPException(500, f"stop fallito: {e}") from e
        _forget_spawned(pid)
        if not _stop_left_behind():
            raise HTTPException(500, "a previous watcher could not be stopped")
        rs.kv_set("watch_pid", "0")
        rs.kv_set("watch_heartbeat", "0")
        policy.audit("watch", {"pid": pid}, "watch_stopped", detail=_who())
        return _watch_state()


@router.get("/watch/log")
def watch_log(lines: int = 60):
    from gigamail.core.data_paths import app_root
    path = os.path.join(str(app_root()), "watch.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ln.rstrip("\n") for ln in f.readlines()[-int(lines):]]
