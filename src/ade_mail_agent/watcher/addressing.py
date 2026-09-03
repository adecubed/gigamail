"""Destinatario e oggetto di una risposta da regola.

Di norma l'indirizzamento e' FISSO (mail_router.reply_message risponde al
From autenticato). L'unica eccezione, esplicita nella regola, e' il relay
dei portali: l'indirizzo della persona vera sta nel corpo.
"""
import re
from typing import Any, Dict, Optional

_MAILTO_RE = re.compile(r'mailto:([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})',
                        re.IGNORECASE)


def body_reply_address(message: Dict[str, Any],
                       sender: str) -> Optional[str]:
    """L'indirizzo della persona vera, quando il mittente e' un relay.

    I portali immobiliari mandano la notifica da un loro robot
    (reply@idealista.it) e mettono l'indirizzo di chi ha scritto
    dentro il corpo, come mailto:. Rispondere al From significa
    rispondere al robot.

    Prende il PRIMO mailto: del corpo e scarta tutto cio' che appare
    del dominio del mittente: i link di servizio del portale
    (privacy, assistenza, disiscrizione) sono mailto: anche loro, e
    senza questo filtro si finirebbe a scrivere all'assistenza.
    Torna None se non trova niente di plausibile: allora la regola
    non propone nulla, invece di indovinare un destinatario.
    """
    corpo = ""
    for chiave in ("body_text", "bodyPreview"):
        corpo = corpo or str(message.get(chiave) or "")
    b = message.get("body")
    if isinstance(b, dict):
        corpo += " " + str(b.get("content") or "")
    dominio = sender.split("@")[-1].lower() if "@" in sender else ""
    for indirizzo in _MAILTO_RE.findall(corpo):
        dest = indirizzo.strip().lower()
        if dominio and dest.endswith(dominio):
            continue
        if dest == (sender or "").lower():
            continue
        return dest
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
