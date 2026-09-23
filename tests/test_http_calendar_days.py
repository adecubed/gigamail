"""Console API: il calendario restituisce i giorni che la console chiede."""

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent.http_api import calendar as calendar_api


@pytest.fixture()
def richieste(monkeypatch):
    fatte = []
    monkeypatch.setattr(calendar_api.calendar_router, "get_events",
                        lambda days_ahead=7, days_back=0: fatte.append((days_ahead, days_back)) or [])
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c, fatte


def test_days_della_console_viene_rispettato(richieste):
    """Il 15/09 la finestra calendario chiedeva days=60 e riceveva 7 giorni:
    l'appuntamento del 25, gia' in calendario, non compariva."""
    c, fatte = richieste
    assert c.get("/calendar?days=60").status_code == 200
    assert fatte == [(60, 0)]


def test_days_ahead_resta_valido_e_default_sette(richieste):
    c, fatte = richieste
    c.get("/calendar?days_ahead=14")
    c.get("/calendar")
    assert fatte == [(14, 0), (7, 0)]
