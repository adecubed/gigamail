# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Quando Hello dice di no, deve dire anche perche'."""
import pytest

from ade_mail_agent import consent


class _Esito(int):
    """Finto UserConsentVerificationResult: e' un int, come quello vero."""


def _finto_win(monkeypatch, codice):
    class _R:
        VERIFIED = 0

    class _V:
        @staticmethod
        def request_verification_async(reason):
            return reason

    mod = type("m", (), {"UserConsentVerificationResult": _R,
                         "UserConsentVerifier": _V})
    import sys
    sys.modules["winrt.windows.security.credentials.ui"] = mod
    monkeypatch.setattr(consent, "_run_winrt", lambda x: _Esito(codice))


@pytest.mark.parametrize("codice,atteso", [
    (5, "annullata"),
    (1, "Hello"),          # nessun metodo configurato
    (3, "occupato"),
    (4, "tentativi"),
])
def test_ogni_rifiuto_ha_il_suo_motivo(monkeypatch, codice, atteso):
    """"Annullata dall'utente" e "su questo PC Hello non e' configurato"
    portano a due azioni diverse: appiattirli sulla stessa frase lascia
    chi legge a indovinare quale dei due sia. Visto dal vivo il
    2026-09-04 su un'approvazione rifiutata senza spiegazione."""
    _finto_win(monkeypatch, codice)
    assert consent._win_ask("motivo") is False
    assert atteso.lower() in consent.last_reason().lower()


def test_dopo_un_si_non_resta_nessun_motivo(monkeypatch):
    """Un motivo vecchio lasciato in giro finirebbe su una schermata di
    successo."""
    _finto_win(monkeypatch, 5)
    consent._win_ask("motivo")
    assert consent.last_reason()
    _finto_win(monkeypatch, 0)
    assert consent._win_ask("motivo") is True
    assert consent.last_reason() == ""


def test_un_esito_sconosciuto_non_diventa_silenzio(monkeypatch):
    """Windows puo' aggiungere codici: meglio dire "esito 9" che niente."""
    _finto_win(monkeypatch, 9)
    assert consent._win_ask("motivo") is False
    assert "9" in consent.last_reason()
