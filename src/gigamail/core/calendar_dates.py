"""
calendar_dates.py — Date degli eventi di un giorno intero.

Chi crea l'evento (console o agente) passa il primo e l'ultimo giorno,
entrambi compresi: "fuori ufficio il 16" e' start=end=2026-10-16. Graph e
Google vogliono invece la fine esclusiva, il giorno dopo l'ultimo: la
conversione sta qui, in un posto solo.
"""

from datetime import date, timedelta
from typing import Tuple


def _giorno(valore) -> date:
    testo = str(valore or '').strip()[:10]
    return date.fromisoformat(testo)


def all_day_range(start, end=None) -> Tuple[str, str]:
    """(primo giorno, giorno dopo l'ultimo) in formato YYYY-MM-DD.

    Accetta date o datetime ISO (conta solo la parte di data). Un end
    mancante o prima dello start vale un giorno solo."""
    primo = _giorno(start)
    ultimo = _giorno(end) if end else primo
    if ultimo < primo:
        ultimo = primo
    return primo.isoformat(), (ultimo + timedelta(days=1)).isoformat()
