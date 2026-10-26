"""Completing approved requests: at once, from whatever channel said yes,
and later for the ones left behind.

A request approved from the console, Telegram or the CLI is sent by
GigaMail here and now, whether the agent asked for it (the tool runs
again with the stored arguments) or a rule drafted it (the watcher's
own send path). Before, a rule's draft waited for the watcher's next
tick, and an agent request whose approval was handled by an older
backend stayed "approved" for good with nothing sending it.

The sweep covers the rest: an approval the console lost half-way (the
app closed, the backend restarted, an exception after the decision) is
found in the store as "approved and valid" and completed, with an audit
line that says so. consume_approved is atomic, so a sweep racing a
click sends once.
"""
from typing import Any, Dict, List

from gigamail import policy

SWEEP_SECONDS = 60


def origin_of(request_id: str) -> str:
    """"watcher" for a draft born from a rule, "agent" for a tool request."""
    try:
        from gigamail.core import rules as rules_mod
        if rules_mod.store().find_by_request(request_id):
            return "watcher"
    except Exception:
        pass
    return "agent"


def _report(request_id: str, origin: str, error: str = "") -> Dict[str, Any]:
    rec = policy.store().get(request_id) or {}
    pr = rec.get("provider_result")
    return {"status": rec.get("status", "approved"),
            "outcome": rec.get("execution_outcome") or ("failed" if error else ""),
            "error": error or (pr.get("error", "") if isinstance(pr, dict) else ""),
            "completed_by": origin}


def complete(request_id: str) -> Dict[str, Any]:
    """Executes an APPROVED request whatever its origin. Returns what was
    recorded: status (executed when consumed), outcome (ok, failed,
    dryrun), error, completed_by."""
    origin = origin_of(request_id)
    if origin == "watcher":
        from gigamail.core import rules as rules_mod
        from gigamail.watcher import execution
        row = rules_mod.store().find_by_request(request_id)
        out = execution.complete_row(row)
        err = ""
        if out.get("status") == "failed":
            err = out.get("reason") or "send-failed"
        return _report(request_id, origin, err)
    from gigamail import server
    try:
        server.execute_approved(request_id)
    except Exception as e:
        return _report(request_id, origin, str(e)[:500])
    return _report(request_id, origin)


def complete_left_behind() -> List[Dict[str, Any]]:
    """Every request approved, still valid and not consumed: completed
    now. Returns one report per request, with the id."""
    try:
        approved = policy.store().list_approved()
    except Exception:
        return []
    out = []
    for rec in approved:
        rid = rec["request_id"]
        policy.audit(rec["tool"], {"request_id": rid, "decided_by": rec.get("decided_by")},
                     "approval_resumed")
        rep = complete(rid)
        rep["request_id"] = rid
        out.append(rep)
    return out
