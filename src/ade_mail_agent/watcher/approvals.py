"""Richiesta di approvazione per una bozza da regola, ed esecuzione.

Le regole non scavalcano policy: dedup, cap orario, TTL, consume→execute
at-most-once sono gli stessi dei tool MCP. Qui si costruisce la preview
che l'umano legge e si chiama policy con il request_id.
"""
import time
from typing import Any, Dict, List, Optional

from ade_mail_agent import policy
from ade_mail_agent.core import attachments as attachments_mod
from ade_mail_agent.core import mail_guard, mail_router

TOOL = "reply_mail"

# TTL delle richieste semi create dal watcher: piu' lungo dei 15 minuti
# standard, perche' qui nessuno sta guardando la chat — la notifica puo'
# raggiungere l'umano ore dopo. Il payload approvato resta identico e
# congelato alla creazione; scaduta la finestra, la richiesta muore e la
# mail resta semplicemente da leggere (nessun retry automatico).
_RULE_TTL_SECONDS = policy._env_int("GIGAMAIL_RULE_APPROVAL_TTL", 4 * 3600)


def _preview_for(rule: Dict[str, Any], message: Dict[str, Any],
                 body: str, mode: str,
                 to_address: Optional[str] = None,
                 allegati: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    preview = {
        "replying_to": {
            "from": mail_guard.sender_address(message),
            "subject": message.get("subject"),
        },
        "body": body,
        "rule_id": rule["rule_id"],
        "rule_mode": mode,
    }
    if to_address:
        # In evidenza, perche' e' l'unico dato che NON viene dal
        # mittente autenticato ma dal corpo: e' quello che l'umano
        # deve guardare prima di approvare.
        preview["to"] = to_address
        preview["to_source"] = ("indirizzo preso dal CORPO del "
                                "messaggio, non dal mittente")
    if rule.get("cc"):
        preview["cc"] = rule["cc"]
    if allegati:
        preview["attachments"] = attachments_mod.preview(allegati)
    return preview


def _execute_reply(request_id: str, args: Dict[str, Any]) -> Any:
    """Esegue una richiesta reply_mail APPROVATA, con lo stesso percorso
    consume→execute dei tool MCP (at-most-once, provider_result, audit).
    Le risposte da regola escono marcate RFC 3834 (anti-loop, barriera 4)."""
    return policy.execute_dangerous(
        TOOL, args, request_id,
        preview_fn=lambda: {},  # mai usata: request_id presente
        execute_fn=lambda a: (
            mail_router.send_message(
                account_id=a["account_id"], to=a["to"],
                subject=a.get("subject") or "",
                body=a["body"], auto_submitted=True,
                cc=a.get("cc") or None,
                attachments=attachments_mod.payload(a.get("attachments")),
            )
            if a.get("to") else
            mail_router.reply_message(
                account_id=a["account_id"], message_id=a["message_id"],
                body=a["body"], auto_submitted=True,
            )
        ),
    )


def _create_request(rule: Dict[str, Any], args: Dict[str, Any],
                    preview: Dict[str, Any]) -> tuple:
    """Crea la richiesta di approvazione per una bozza da regola, con il
    dedup e il cap orario di policy (le regole non li scavalcano).
    Ritorna (request_id, created): su dedup created=False, cosi' il
    chiamante non notifica due volte la stessa richiesta."""
    s = policy.store()
    existing = s.find_pending(TOOL, args)
    if existing:
        return existing, False
    if s.count_created_since(TOOL, time.time() - 3600) >= policy._APPROVAL_MAX_PER_HOUR:
        policy.audit(TOOL, {"rule_id": rule["rule_id"]}, "approval_rate_limited",
                     detail="watcher")
        return None, False
    request_id = s.create(TOOL, args, preview, ttl=_RULE_TTL_SECONDS)
    policy.audit(TOOL, args, "approval_requested",
                 detail=f"rule:{rule['rule_id']}")
    return request_id, True
