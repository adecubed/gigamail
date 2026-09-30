# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Estensione immobiliare di GigaMail.

Nata in un'agenzia che risponde ogni giorno alle richieste dei portali
(idealista, immobiliare.it) e del proprio sito. Aggiunge al core due cose
che valgono solo per chi vende case:

  - la TIPOLOGIA richiesta (bilocale, trilocale...) letta dall'oggetto
    dell'annuncio, messa nel prompt come vincolo e verificata sulla bozza:
    se l'agente propone un'altra tipologia, la bozza si riscrive una volta
    e poi si ferma;
  - i CODICI delle unita' (A.3.2, B.1.4) citati nel testo, che decidono
    quali schede e planimetrie si allegano.

Si installa accanto a gigamail e si accende esplicitamente:

    pip install ./extras/real_estate
    gigamail extensions enable real_estate
"""
import re
from typing import List, Optional

from gigamail.core.extensions import DraftCheck, Extension

from . import tipologie

__all__ = ["RealEstate", "tipologie"]

# I codici delle unita' come compaiono nel testo: A.3.2, B.1.4.
# Sono l'unico pezzo di corpo che si puo' leggere con una regola fissa
# senza rischiare: o il codice c'e' scritto, o non c'e'.
_CODICE = re.compile(r"\b([AB]\.[0-9]\.[0-9])\b")


class RealEstate(Extension):
    name = "real_estate"

    def draft_constraint(self, subject: str, body: str) -> str:
        return tipologie.vincolo(tipologie.chiesta(subject, body))

    def check_draft(self, subject: str, body: str,
                    draft: str) -> Optional[DraftCheck]:
        chiesta = tipologie.chiesta(subject, body)
        if tipologie.coerente(chiesta, draft):
            return DraftCheck(ok=True)
        dettaglio = tipologie.spiega(chiesta, draft)
        return DraftCheck(
            ok=False,
            detail="tipologia non coerente: " + dettaglio,
            feedback=tipologie.correzione(chiesta, draft),
            notice={
                "it": (f"Nessuna bozza per la mail da {{sender}}: il cliente "
                       f"chiede un {chiesta}, l'agente ha proposto due volte "
                       f"un'altra tipologia ({dettaglio}). Rispondi a mano."),
                "en": (f"No draft for the mail from {{sender}}: the client "
                       f"asks for a {chiesta}, the agent proposed another "
                       f"flat type twice ({dettaglio}). Reply by hand."),
            })

    def cited_codes(self, text: str) -> List[str]:
        visti: List[str] = []
        for m in _CODICE.finditer(str(text or "")):
            c = m.group(1).upper()
            if c not in visti:
                visti.append(c)
        return visti
