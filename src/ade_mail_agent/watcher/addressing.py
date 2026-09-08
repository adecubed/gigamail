"""Destinatario e oggetto di una risposta da regola.

Di norma l'indirizzamento e' FISSO (mail_router.reply_message risponde al
From autenticato). L'unica eccezione, esplicita nella regola, e' il relay
dei portali: l'indirizzo della persona vera sta nel corpo.
"""
import re
from typing import Any, Dict, Optional

_MAILTO_RE = re.compile(r'mailto:([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})',
                        re.IGNORECASE)


# Caselle di servizio dei portali: a queste non si risponde mai.
# L'elenco e' di local-part, non di domini, perche' il dominio del
# portale ospita ANCHE gli alias personali dei clienti.
_SERVIZIO = ("privacy", "assistenza", "support", "help", "info",
             "noreply", "no-reply", "nonrispondere", "reply",
             "unsubscribe", "disiscriviti", "marketing", "news",
             "newsletter", "postmaster", "mailer-daemon")


def _e_di_servizio(indirizzo: str) -> bool:
    local = indirizzo.split("@")[0].lower()
    return any(local == s or local.startswith(s + "-") or
               local.startswith(s + ".") for s in _SERVIZIO)


def body_reply_address(message: Dict[str, Any],
                       sender: str) -> Optional[str]:
    """L'indirizzo della persona vera, quando il mittente e' un relay.

    I portali immobiliari mandano la notifica da un loro robot
    (reply@idealista.it) e mettono nel corpo l'indirizzo di chi ha
    scritto. Rispondere al From significa rispondere al robot.

    Si scartano le caselle di SERVIZIO del portale (privacy@,
    assistenza@, disiscriviti@...), non tutto il suo dominio: quando
    il cliente non condivide la propria email, idealista fornisce un
    alias opaco su un suo sottodominio, e quell'alias e' l'unico modo
    di raggiungerlo. Scartarlo perche' 'e' del portale' significa non
    rispondere a un cliente che ha lasciato un recapito valido —
    successo il 2026-09-08 con una richiesta saltata come
    'no-body-address'.

    Si preferisce comunque un indirizzo fuori dal dominio del mittente:
    l'alias e' il ripiego, non la prima scelta.
    """
    corpo = ""
    for chiave in ("body_text", "bodyPreview"):
        corpo = corpo or str(message.get(chiave) or "")
    b = message.get("body")
    if isinstance(b, dict):
        corpo += " " + str(b.get("content") or "")
    mittente = (sender or "").lower()
    dominio = mittente.split("@")[-1] if "@" in mittente else ""
    fuori, alias = [], []
    for trovato in _MAILTO_RE.findall(corpo):
        dest = trovato.strip().lower()
        if dest == mittente or _e_di_servizio(dest):
            continue
        (alias if dominio and dest.endswith(dominio) else fuori).append(dest)
    for elenco in (fuori, alias):
        if elenco:
            return elenco[0]
    return None

def _reply_subject(message: Dict[str, Any]) -> str:
    """`send_message` non ricostruisce l'oggetto come fa reply_message:
    qui lo mettiamo noi, cosi' il destinatario vede un "Re:" sensato."""
    originale = str(message.get("subject") or "").strip()
    if not originale:
        return "Re:"
    if originale.lower().startswith("re:"):
        return originale
    return f"Re: {originale}"
