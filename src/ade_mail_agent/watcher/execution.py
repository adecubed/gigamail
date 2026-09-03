"""Esecuzione: le richieste approvate nel frattempo e i retry.

Le richieste create dal watcher non hanno un agente che le richiama con
request_id: le chiude il watcher stesso, appena l'umano ha deciso.
"""
from ade_mail_agent import policy
from ade_mail_agent.core import mail_router
from ade_mail_agent.core import rules as rules_mod

from .approvals import _execute_reply
from .ingestion import folder_of
from .log import _log


def execute_approved(w) -> int:
    done = 0
    rs = rules_mod.store()
    for row in rs.pending_requests():
        rec = policy.store().get(row["request_id"])
        rule_id, message_id = row["rule_id"], row["message_id"]
        if rec is None:
            rs.set_status(rule_id, message_id, "failed", "request-vanished")
            continue
        if rec["status"] == policy.PENDING:
            if rec["expired"]:
                rs.set_status(rule_id, message_id, "expired",
                              "approval-ttl-expired")
            continue
        if rec["status"] == policy.REJECTED:
            rs.set_status(rule_id, message_id, "rejected")
            continue
        if rec["status"] == policy.EXECUTED:
            # eseguita da qualcun altro (es. l'agente col request_id)
            rs.set_status(rule_id, message_id, "sent", "executed-elsewhere")
            continue
        # approved → esegue
        try:
            result = _execute_reply(row["request_id"], rec["args"])
            ok = bool(result.get("success", True)) if isinstance(result, dict) else bool(result)
            rs.set_status(rule_id, message_id, "sent" if ok else "failed",
                          "" if ok else "send-failed")
            done += 1
            _log(("inviata " if ok else "INVIO FALLITO ")
                 + f"{row['request_id']} ({rule_id})", w.verbose)
        except Exception as e:
            # Qualunque cosa sia andata storta nel provider, lo stato
            # lo registra: la mail non sparisce in un limbo.
            rs.set_status(rule_id, message_id, "failed", str(e)[:200])
    return done


def process_retries(w) -> int:
    """Le mail per cui l'umano ha chiesto "rifai la bozza cosi'":
    non passano dal filtro unread (magari l'ha gia' letta), si
    ripescano per id e si riprocessano col feedback."""
    n = 0
    rs = rules_mod.store()
    for row in rs.retries():
        rule = rs.get(row["rule_id"])
        if not rule or rule["paused"] or rule["expired"]:
            rs.set_status(row["rule_id"], row["message_id"], "failed",
                          "rule-inactive")
            continue
        previous = None
        rec = policy.store().get(row["request_id"]) if row.get("request_id") else None
        if rec:
            previous = (rec.get("args") or {}).get("body")
        try:
            message = mail_router.get_message(
                account_id=rule["account_id"], message_id=row["message_id"],
                folder=folder_of(rule)) or {}
        except Exception as e:
            rs.set_status(row["rule_id"], row["message_id"], "failed",
                          f"refetch:{e}"[:200])
            continue
        if not message:
            rs.set_status(row["rule_id"], row["message_id"], "failed",
                          "message-vanished")
            continue
        w.process_message(rule, message,
                          retry_feedback=row.get("feedback") or "",
                          previous_body=previous)
        n += 1
    return n
