"""Ingestion: la posta recente della cartella di una regola, e il match.

L'idempotenza non sta qui ma nella tabella handled (rules.db): questo
modulo dice solo "queste mail sono candidate per questa regola".
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from ade_mail_agent.core import mail_guard, mail_router

from .log import _log


def folder_of(rule: Dict[str, Any]) -> str:
    return rule["trigger_values"][0] if rule["trigger_kind"] == "folder" else "inbox"


def matches(rule: Dict[str, Any], message: Dict[str, Any]) -> bool:
    if rule["trigger_kind"] == "folder":
        return True  # la cartella E' il trigger
    sender = mail_guard.sender_address(message)
    wanted = {str(v).strip().lower() for v in rule["trigger_values"]}
    return sender in wanted


def poll_folder(rule: Dict[str, Any], *, top: int, unread_days: int,
                verbose: bool) -> List[Dict[str, Any]]:
    """Le mail recenti della cartella della regola, LETTE O NON LETTE:
    misurato dal vivo (22/08) che filtrare sulle non lette e' fragile —
    se l'utente ha il thread aperto nel client, la mail nasce letta e
    la regola non scatta mai. L'idempotenza la da' la tabella handled;
    il perimetro temporale e' "arrivata dopo la creazione della regola"
    (mai rispondere a posta vecchia quando nasce una regola) e
    comunque entro unread_days. Una mail gia' letta non va mai in
    auto: l'umano l'ha vista, si propone (vedi pipeline)."""
    folder = folder_of(rule)
    try:
        msgs = mail_router.get_messages(
            account_id=rule["account_id"], folder=folder, top=top) or []
    except Exception as e:
        _log(f"poll fallito ({rule['rule_id']}, {folder}): {e}", verbose)
        return []
    now = datetime.now(timezone.utc)
    floor = max(
        datetime.fromtimestamp(float(rule.get("created_at") or 0), timezone.utc),
        now - timedelta(days=unread_days))
    out = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        dt = mail_router._message_datetime(str(m.get("receivedDateTime") or ""))
        if dt is not None and dt < floor:
            continue
        out.append(m)
    return out
