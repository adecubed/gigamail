"""Helper condivisi dai router: account, consenso umano e audit."""
import logging
from copy import deepcopy
from typing import Callable, Optional

from fastapi import HTTPException

from gigamail import consent, policy
from gigamail.core import accounts as core_accounts


def _active_id() -> Optional[int]:
    a = core_accounts.get_active_account()
    return a["id"] if a else None

def _who() -> str:
    import getpass
    try:
        return f"console:{getpass.getuser()}"
    except Exception:
        return "console"


def _audit_result(tool, payload, outcome, **kwargs):
    # A logging failure cannot undo a completed provider operation. Preserve
    # its result so the caller does not retry a message that was already sent.
    try:
        policy.audit(tool, payload, outcome, **kwargs)
    except Exception:
        logging.getLogger(__name__).exception("Cannot record console action outcome")


def _human_action(tool: str, args: dict, reason: str, execute: Callable):
    """A console token authenticates a process, not a human at the screen.

    Keep the existing synchronous UI contract, but require OS consent for
    each dangerous action and execute only the payload captured beforehand.
    The consent test override must never turn a dry run into a real write.
    """
    payload = deepcopy(args)
    if "account_id" in payload and payload["account_id"] is None:
        raise HTTPException(400, "Nessun account attivo")
    try:
        approved = consent.require_human(f"GigaMail: {reason}")
    except consent.ConsentUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if not approved:
        motivo = consent.last_reason()
        raise HTTPException(403, "Verifica utente non superata"
                            + (f": {motivo}" if motivo else " o annullata"))
    return _run_action(tool, payload, execute)


def _user_action(tool: str, args: dict, execute: Callable):
    """Tidying the mailbox or the calendar from the console: no OS prompt.

    Windows Hello was asked for every click on Delete, Spam or Move. That
    prompt exists to keep an agent from approving its own mail; a person
    sorting their inbox is not that agent, and a prompt per click made the
    console unusable. What leaves the machine (sending) and what the agent
    asks for still go through `_human_action`. The console asks "are you
    sure?" itself for deletions, and every action is audited as a click.
    """
    payload = deepcopy(args)
    if "account_id" in payload and payload["account_id"] is None:
        raise HTTPException(400, "Nessun account attivo")
    return _run_action(tool, payload, execute, how="click")


def _run_action(tool: str, payload: dict, execute: Callable, how: str = "verified"):
    if policy.dry_run_active():
        policy.audit(tool, payload, "dryrun_executed", detail=_who())
        return {"success": True, "dryrun": True}
    try:
        result = execute(payload)
    except Exception as e:
        _audit_result(tool, payload, "error", detail=str(e))
        raise
    ok = result.get("success", True) if isinstance(result, dict) else bool(result)
    _audit_result(tool, payload, "executed" if ok else "failed",
                  detail=f"{_who()} ({how})",
                  provider_result=result.get("provider_result") if isinstance(result, dict) else None)
    return result
