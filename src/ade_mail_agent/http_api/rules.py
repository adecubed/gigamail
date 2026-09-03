"""Automazioni (0.2.1): regole di risposta e watcher (processo separato)."""
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ade_mail_agent import policy

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


def _require_human_or_http(reason: str) -> None:
    from ade_mail_agent import consent
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if not ok:
        raise HTTPException(403, "Verifica utente non superata o annullata")


def _rule_view(r: dict) -> dict:
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    d = dict(r)
    d["sent_today"] = rs.sent_today(r["rule_id"])
    d["state"] = ("paused" if r["paused"] else
                  "expired" if r["expired"] else "active")
    return d


@router.get("/rules")
def list_rules():
    from ade_mail_agent.core import rules as rules_mod
    return [_rule_view(r) for r in rules_mod.store().list_all()]


@router.post("/rules")
def create_rule(body: RuleCreate):
    """Crea una regola. Hello obbligatorio: e' una pre-approvazione."""
    import time as _t

    from ade_mail_agent.core import rules as rules_mod
    aid = body.account_id or _active_id()
    if not aid:
        raise HTTPException(400, "Nessun account")
    if body.trigger_kind not in rules_mod.TRIGGER_KINDS:
        raise HTTPException(400, "trigger_kind non valido")
    if body.mode not in rules_mod.MODES or body.first_contact not in rules_mod.MODES:
        raise HTTPException(400, "mode/first_contact non validi")
    values = [v.strip().lower() if body.trigger_kind == "senders" else v.strip()
              for v in body.trigger_values if v and v.strip()]
    if not values:
        raise HTTPException(400, "trigger vuoto")
    docs = []
    for pth in body.doc_paths or []:
        pth = os.path.abspath(pth)
        if not os.path.exists(pth):
            raise HTTPException(400, f"Documento inesistente: {pth}")
        docs.append(pth)
    _require_human_or_http(
        f"GigaMail: creare la regola {body.mode.upper()} per {', '.join(values)}?")
    rule_id = rules_mod.store().create(
        account_id=aid, trigger_kind=body.trigger_kind, trigger_values=values,
        reply_style=body.reply_style, doc_paths=docs, mode=body.mode,
        first_contact=body.first_contact, daily_cap=body.daily_cap,
        cooldown_hours=body.cooldown_hours, expiry_days=body.expiry_days,
        created_by=_who(), hello_verified_at=_t.time())
    policy.audit("rule", {"rule_id": rule_id, "mode": body.mode, "trigger": values},
                 "rule_created", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.post("/rules/{rule_id}/pause")
def pause_rule(rule_id: str):
    from ade_mail_agent.core import rules as rules_mod
    if not rules_mod.store().pause(rule_id, "pausa dalla console"):
        raise HTTPException(404, "Regola inesistente")
    policy.audit("rule", {"rule_id": rule_id}, "rule_paused", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.post("/rules/{rule_id}/resume")
def resume_rule(rule_id: str):
    """Riattivare = ri-approvare: Hello."""
    import time as _t

    from ade_mail_agent.core import rules as rules_mod
    if not rules_mod.store().get(rule_id):
        raise HTTPException(404, "Regola inesistente")
    _require_human_or_http(f"GigaMail: riattivare la regola {rule_id}?")
    rules_mod.store().resume(rule_id, _t.time())
    policy.audit("rule", {"rule_id": rule_id}, "rule_resumed", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    from ade_mail_agent.core import rules as rules_mod
    if not rules_mod.store().delete(rule_id):
        raise HTTPException(404, "Regola inesistente")
    policy.audit("rule", {"rule_id": rule_id}, "rule_deleted", detail=_who())
    return {"success": True}


@router.get("/rules/{rule_id}/activity")
def rule_activity(rule_id: str, limit: int = 30):
    """Le mail che la regola ha guardato, con esito."""
    from ade_mail_agent.core import rules as rules_mod
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
    from ade_mail_agent.watcher import running_state
    return running_state()


def _pid_alive(pid: int) -> bool:
    from ade_mail_agent.watcher import pid_alive
    return pid_alive(pid)

@router.get("/watch/status")
def watch_status():
    return _watch_state()


@router.post("/watch/start")
def watch_start(interval: int = 60):
    """Avvia `gigamail watch` come processo staccato (sopravvive alla
    console), log in app_root()/watch.log."""
    import subprocess
    import sys as _sys

    from ade_mail_agent.core.data_paths import app_root
    st = _watch_state()
    if st["running"]:
        return st
    log_path = os.path.join(str(app_root()), "watch.log")
    log = open(log_path, "a", encoding="utf-8")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [_sys.executable, "-u", "-m", "ade_mail_agent.cli", "watch",
         "--verbose", "--interval", str(max(int(interval), 10))],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        env=dict(os.environ), **kwargs)
    from ade_mail_agent.core import rules as rules_mod
    rules_mod.store().kv_set("watch_pid", str(proc.pid))
    policy.audit("watch", {"pid": proc.pid, "interval": interval}, "watch_started",
                 detail=_who())
    return {"running": True, "pid": proc.pid, "interval": interval,
            "last_tick_age_seconds": None, "active_rules": st["active_rules"]}


@router.post("/watch/stop")
def watch_stop():
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    pid = int(rs.kv_get("watch_pid", "0") or 0)
    if pid and _pid_alive(pid):
        try:
            if os.name == "nt":
                import subprocess
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=15)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
        except Exception as e:
            raise HTTPException(500, f"stop fallito: {e}") from e
    rs.kv_set("watch_pid", "0")
    rs.kv_set("watch_heartbeat", "0")
    policy.audit("watch", {"pid": pid}, "watch_stopped", detail=_who())
    return _watch_state()


@router.get("/watch/log")
def watch_log(lines: int = 60):
    from ade_mail_agent.core.data_paths import app_root
    path = os.path.join(str(app_root()), "watch.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ln.rstrip("\n") for ln in f.readlines()[-int(lines):]]
