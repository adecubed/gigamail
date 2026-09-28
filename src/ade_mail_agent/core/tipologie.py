# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Che cosa ha chiesto il cliente, e che cosa gli stiamo rispondendo.

Il 27 settembre 2026 un cliente ha scritto per un BILOCALE e si e' visto
rispondere con tre trilocali da 379.000 euro in su, planimetrie comprese.
Non era un guasto degli allegati: gli allegati seguivano fedelmente il
testo. Era il testo a rispondere alla domanda sbagliata.

Il motivo sta nel prompt della bozza: dentro ci finiscono gli esempi
delle ultime risposte inviate e un "template suggerito" scelto per
somiglianza di oggetto. Gli avvisi di idealista hanno oggetti quasi
identici, cambia solo la tipologia, quindi il template era sempre
l'ultima risposta sui trilocali e l'agente la ricopiava.

Qui la tipologia si legge in modo deterministico, senza modello: dal
titolo dell'annuncio, che il portale scrive nell'oggetto, e in seconda
battuta dal corpo. Serve per due cose: dirlo all'agente come vincolo, e
verificare la bozza prima che parta.
"""
import re
from typing import List, Optional, Set

# In ordine di specificita': "quadrilocale" contiene "locale", e un
# confronto ingenuo lo confonderebbe con "monolocale".
TIPOLOGIE = ("monolocale", "bilocale", "trilocale", "quadrilocale",
             "cinquelocale")

_TIPOLOGIA = re.compile("|".join(TIPOLOGIE), re.IGNORECASE)

# Le righe con cui una bozza elenca le soluzioni proposte:
#   "- B.1.3: trilocale di 80,43 mq con balcone..."
#   "- A.3.2 quadrilocale di 103,26 mq"
_RIGA_ELENCO = re.compile(
    r"[-*•]?\s*[AB]\.[0-9]\.[0-9]\s*[:\-]?\s*(" + "|".join(TIPOLOGIE) + r")",
    re.IGNORECASE)


def chiesta(subject: str = "", body: str = "") -> Optional[str]:
    """La tipologia su cui scrive il cliente, o None se non lo dice.

    L'oggetto ha la precedenza: negli avvisi dei portali riporta il
    titolo dell'annuncio ("Nuovo messaggio di X sul tuo immobile,
    Bilocale in Via Treviglio, 28"), cioe' l'immobile che la persona
    stava guardando davvero. Nel corpo la parola puo' comparire dentro
    una citazione del nostro messaggio precedente."""
    for testo in (subject, body):
        m = _TIPOLOGIA.search(str(testo or ""))
        if m:
            return m.group(0).lower()
    return None


def elencate(testo: str) -> Set[str]:
    """Le tipologie delle soluzioni elencate in una bozza."""
    return {m.group(1).lower() for m in _RIGA_ELENCO.finditer(str(testo or ""))}


def coerente(tipologia: Optional[str], bozza: str) -> bool:
    """La bozza parla della tipologia chiesta?

    Vero anche quando la bozza non elenca nessuna soluzione: una risposta
    interlocutoria, una conferma di appuntamento o un preventivo a voce
    non devono essere bloccati. Il controllo scatta solo quando la bozza
    propone appartamenti e NESSUNO e' del tipo richiesto."""
    if not tipologia:
        return True
    proposte = elencate(bozza)
    if not proposte:
        return True
    return tipologia in proposte


def spiega(tipologia: Optional[str], bozza: str) -> str:
    """Una riga per il log e per l'avviso all'umano."""
    proposte = ", ".join(sorted(elencate(bozza))) or "nessuna"
    return f"chiesto {tipologia or 'non dichiarato'}, proposte: {proposte}"


def vincolo(tipologia: Optional[str]) -> str:
    """La riga da mettere nel prompt della bozza."""
    if not tipologia:
        return ("TIPOLOGIA RICHIESTA: non dichiarata. Non dare per scontata "
                "la tipologia dell'ultima risposta che hai visto: se serve, "
                "chiedila.")
    return (f"TIPOLOGIA RICHIESTA: {tipologia}. Le soluzioni che elenchi "
            f"devono essere di questo tipo, prese dai documenti. Se nei "
            f"documenti non ci sono {tipologia}i disponibili, dillo "
            f"chiaramente invece di proporre un'altra tipologia.")


def tipologie_note() -> List[str]:
    return list(TIPOLOGIE)
