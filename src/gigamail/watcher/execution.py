"""Esecuzione: le richieste approvate nel frattempo e i retry.

Le richieste create dal watcher non hanno un agente che le richiama con
request_id: le chiude il watcher stesso, appena l'umano ha deciso.
"""
from gigamail import policy
from gigamail.core import mail_router
from gigamail.core import rules as rules_mod

from .approvals import _execute_reply
from .ingestion import folder_of
from .log import _log


def complete_row(row, rec=None, verbose: bool = False) -> dict:
    """Closes one handled row whose request is decided: sends it when
    approved, records the outcome of an execution done elsewhere, marks
    rejected or expired. Returns {status, reason} as written on the row,
    or {} when the request is still waiting."""
    rs = rules_mod.store()
    rule_id, message_id = row["rule_id"], row["message_id"]
    if rec is None:
        rec = policy.store().get(row["request_id"])

    def _set(status, reason=""):
        rs.set_status(rule_id, message_id, status, reason)
        return {"status": status, "reason": reason}

    if rec is None:
        return _set("failed", "request-vanished")
    if rec["status"] == policy.PENDING:
        if rec["expired"]:
            return _set("expired", "approval-ttl-expired")
        return {}
    if rec["status"] == policy.REJECTED:
        return _set("rejected")
    if rec["status"] == policy.EXECUTED:
        # Consume precede la chiamata al provider: EXECUTED da solo
        # non prova che una mail sia partita. Se l'altro esecutore e'
        # ancora al lavoro, si aspetta il suo esito senza reinviare.
        outcome = rec.get("execution_outcome")
        if outcome == "ok":
            return _set("sent", "executed-elsewhere")
        if outcome:
            return _set("failed", f"execution-{outcome}-elsewhere")
        return {}
    if rec["expired"]:
        return _set("expired", "approval-ttl-expired")
    # approved → esegue
    try:
        result = _execute_reply(row["request_id"], rec["args"])
    except Exception as e:
        # Qualunque cosa sia andata storta nel provider, lo stato
        # lo registra: la mail non sparisce in un limbo.
        return _set("failed", str(e)[:200])
    ok = bool(result.get("success", True)) if isinstance(result, dict) else bool(result)
    out = _set("sent" if ok else "failed", "" if ok else "send-failed")
    _log(("inviata " if ok else "INVIO FALLITO ")
         + f"{row['request_id']} ({rule_id})", verbose)
    return out


def execute_approved(w) -> int:
    done = 0
    rs = rules_mod.store()
    for row in rs.pending_requests():
        rec = policy.store().get(row["request_id"])
        was_approved = rec is not None and rec["status"] == policy.APPROVED
        out = complete_row(row, rec, verbose=w.verbose)
        if was_approved and out.get("status") == "sent":
            done += 1
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
