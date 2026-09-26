"""Helper condivisi dai router: account, consenso umano e audit."""
import logging
from copy import deepcopy
from typing import Callable, Optional

from fastapi import HTTPException

from ade_mail_agent import consent, policy
from ade_mail_agent.core import accounts as core_accounts


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
        raise HTTPException(403, "Verifica utente non superata o annullata")
    if policy.dry_run_active():
        policy.audit(tool, payload, "dryrun_executed", detail=_who())
        return {"success": True, "dryrun": True}
    try:
        result = execute(payload)
    except Exception as e:
        _audit_result(tool, payload, "error", detail=str(e))
        raise
    ok = result.get("success", True) if isinstance(result, dict) else bool(result)
    _audit_result(tool, payload, "executed" if ok else "failed", detail=_who(),
                  provider_result=result.get("provider_result") if isinstance(result, dict) else None)
    return result
