"""Il testo che l'umano legge sulla notifica (toast e/o Telegram).

Deve dire CHI ha scritto, COSA rispondiamo e COME approvare — senza aprire
nulla. Nella LINGUA DELL'UTENTE (policy.user_lang: sistema o
GIGAMAIL_LANG); il corpo della bozza dentro il messaggio resta nella
lingua che l'agente ha scelto dalla mail in arrivo — sono due destinatari
diversi.
"""
from typing import Any, Dict

from ade_mail_agent import policy
from ade_mail_agent.core import mail_guard

_NOTIFY_BODY_CHARS = 400


def _sender_subject(message: Dict[str, Any]) -> tuple:
    sender = mail_guard.sender_address(message)
    subject = str(message.get("subject") or "")
    if not subject:
        subject = "(senza oggetto)" if policy.user_lang() == "it" else "(no subject)"
    return sender, subject


def _semi_notify_text(rule: Dict[str, Any], message: Dict[str, Any],
                      body: str, request_id: str) -> str:
    sender, subject = _sender_subject(message)
    draft = body[:_NOTIFY_BODY_CHARS]
    if policy.user_lang() == "it":
        return (
            f"E' arrivata una mail da {sender} — «{subject}».\n"
            f"Propongo questa risposta (regola {rule['rule_id']}):\n{draft}\n\n"
            f"Approvi? → gigamail approvals approve {request_id}"
        )
    return (
        f"New email from {sender} — “{subject}”.\n"
        f"I propose this reply (rule {rule['rule_id']}):\n{draft}\n\n"
        f"Approve? → gigamail approvals approve {request_id}"
    )


def _auto_notify_text(rule: Dict[str, Any], message: Dict[str, Any],
                      body: str, ok: bool) -> str:
    sender, subject = _sender_subject(message)
    draft = body[:_NOTIFY_BODY_CHARS]
    if policy.user_lang() == "it":
        if not ok:
            return (f"INVIO FALLITO (regola {rule['rule_id']}, automode) — "
                    f"mail da {sender}, «{subject}». Vedi audit/console.")
        return (f"Inviata in automode (regola {rule['rule_id']}) a {sender} — "
                f"«{subject}»:\n{draft}")
    if not ok:
        return (f"SEND FAILED (rule {rule['rule_id']}, automode) — email "
                f"from {sender}, “{subject}”. Check the audit/console.")
    return (f"Sent in automode (rule {rule['rule_id']}) to {sender} — "
            f"“{subject}”:\n{draft}")
