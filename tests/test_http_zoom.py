"""Console API: collegamento Zoom. Il segreto entra e non esce."""

import json

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent.core import zoom


@pytest.fixture()
def client():
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c


@pytest.fixture(autouse=True)
def senza_zoom():
    zoom.rimuovi_config()
    yield
    zoom.rimuovi_config()


def _rifiuta():
    raise zoom.ZoomErrore("credenziali Zoom rifiutate (400): invalid_client")


CODICI = {"account_id": "acc1", "client_id": "cid-12345678",
          "client_secret": "segretissimo"}


def test_stato_senza_zoom(client):
    d = client.get("/zoom/status").json()
    assert d == {"configured": False, "account_id": "", "client_id": ""}


def test_collegare_verifica_e_non_restituisce_il_segreto(client, monkeypatch):
    monkeypatch.setattr(zoom, "verifica", lambda: "me@example.com")
    r = client.post("/zoom/setup", json=CODICI)
    assert r.status_code == 200
    assert r.json() == {"success": True, "email": "me@example.com"}
    stato = client.get("/zoom/status").json()
    assert stato["configured"] is True and stato["account_id"] == "acc1"
    testo = json.dumps(stato)
    assert "segretissimo" not in testo and "cid-12345678" not in testo
    assert zoom.config()["client_secret"] == "segretissimo"


def test_credenziali_rifiutate_non_restano_salvate(client, monkeypatch):
    """Altrimenti la scheda direbbe 'collegato' e il primo cliente
    scoprirebbe che non lo e'."""
    monkeypatch.setattr(zoom, "verifica", _rifiuta)
    r = client.post("/zoom/setup", json=CODICI)
    assert r.status_code == 400
    assert "invalid_client" in r.json()["detail"]
    assert zoom.configurato() is False


def test_credenziali_rifiutate_tengono_quelle_buone(client, monkeypatch):
    zoom.salva_config("buono", "cid-buono", "sec-buono")
    monkeypatch.setattr(zoom, "verifica", _rifiuta)
    client.post("/zoom/setup", json=CODICI)
    assert zoom.config()["account_id"] == "buono"
    assert zoom.config()["client_secret"] == "sec-buono"


def test_campi_mancanti(client):
    r = client.post("/zoom/setup", json=dict(CODICI, client_secret="  "))
    assert r.status_code == 400
    assert zoom.configurato() is False


def test_verifica_senza_zoom(client):
    assert client.post("/zoom/test").status_code == 404


def test_scollega(client):
    zoom.salva_config("acc1", "cid", "sec")
    assert client.post("/zoom/remove").json() == {"success": True}
    assert zoom.configurato() is False
