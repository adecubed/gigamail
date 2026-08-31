# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Indirizzi: da quello che l'umano scrive a quello che va in busta.

Vive da solo, senza dipendenze, per un motivo preciso: lo usano sia
l'anteprima che l'umano approva sia i due percorsi di invio (SMTP e
Graph). Se lo split fosse duplicato, i tre potrebbero divergere — ed e'
esattamente la divergenza che non si vede: l'anteprima elenca due
destinatari, la busta ne porta uno, e la mail sembra partita.
"""
import re
from typing import Any, List

_ANGLE_RE = re.compile(r"<([^<>]+)>")


def split_addresses(value: Any) -> List[str]:
    """'a@x.it, Nome <b@y.it>; c@z.it' -> ['a@x.it', 'b@y.it', 'c@z.it'].

    Una stringa con piu' indirizzi NON e' un destinatario. Passata intera
    a smtplib diventa un solo `RCPT TO:<a@x.it, b@y.it>` — un indirizzo
    malformato, non due destinatari — e a Graph un solo toRecipients. Il
    server puo' anche non rifiutarla: allora l'invio torna success con
    "accepted: 1" e nessuno si accorge che meta' dei destinatari non e'
    mai stata in busta.

    Accetta stringa (separatori , e ;) o lista, e riduce 'Nome <a@x.it>'
    all'indirizzo: e' quello che il server usa davvero.
    """
    if not value:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[;,]", value) if p.strip()]
    else:
        parts = [str(p).strip() for p in value if str(p).strip()]
    out = []
    for raw in parts:
        m = _ANGLE_RE.search(raw)
        addr = (m.group(1) if m else raw).strip()
        if addr:
            out.append(addr)
    return out
