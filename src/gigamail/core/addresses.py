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
_QUOTED_RE = re.compile(r'"[^"]*"')
_SEPARATOR_RE = re.compile(r"[;,\r\n]")
_BROKEN_RE = re.compile(r'[\s,;<>"]')


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
    # A list is split element by element too: the console's reply and new
    # mail windows send the CC field as typed, as one element, and "a@x.it,
    # b@y.it" inside a list went to the server as one malformed recipient.
    # The send came back "accepted" and nobody in copy received the mail.
    items = [value] if isinstance(value, str) else [p for p in value if p is not None]
    out = []
    for item in items:
        # The display name is dropped anyway: dropped first, a comma inside
        # a quoted name ("Rossi, Mario" <a@x.it>) is not taken for a separator.
        text = _QUOTED_RE.sub(" ", str(item))
        for raw in _SEPARATOR_RE.split(text):
            raw = raw.strip()
            if not raw:
                continue
            m = _ANGLE_RE.search(raw)
            if m:
                found = [m.group(1).strip()]
            else:
                # Addresses pasted with spaces between them. Words that are
                # not all addresses stay together: malformed() names them.
                words = raw.split()
                found = words if len(words) > 1 and all("@" in w for w in words) else [raw]
            for addr in found:
                if addr.lower().startswith("mailto:"):
                    addr = addr[len("mailto:"):].strip()
                if addr:
                    out.append(addr)
    return out


def malformed(addresses: Any) -> List[str]:
    """The recipients no mail server can deliver to: text with a space, a
    separator, a quote or a bracket left in it. A server may accept such a
    recipient and deliver to nobody, with the send reported as done, so the
    send is refused before it starts. A name without "@" is left alone: a
    local alias or a group is the server's to resolve."""
    return [a for a in split_addresses(addresses) if _BROKEN_RE.search(a)]
