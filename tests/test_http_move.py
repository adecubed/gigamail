"""Console API: spostare una mail in un'altra cartella."""

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent.http_api import mail as mail_api


@pytest.fixture()
def client():
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c


@pytest.fixture()
def spostamenti(monkeypatch):
    fatti = []
    from ade_mail_agent import consent
    monkeypatch.setattr(consent, "require_human", lambda reason: True)

    def _sposta(account_id=None, message_id="", folder_id="", source_folder=None):
        fatti.append((account_id, message_id, folder_id, source_folder))
        return True
    monkeypatch.setattr(mail_api.mail_router, "move_to_folder", _sposta)
    return fatti


def test_cartella_nel_corpo_come_la_manda_la_console(client, spostamenti):
    """Il 15/09 il tasto Sposta si bloccava: la console manda folder_id nel
    corpo JSON, il backend lo voleva in query e rispondeva 422 a ogni clic."""
    r = client.post("/mail/3450/move?account_id=2&source_folder=INBOX",
                    json={"folder_id": "INBOX.idealista"})
    assert r.status_code == 200 and r.json() == {"success": True}
    assert spostamenti == [(2, "3450", "INBOX.idealista", "INBOX")]


def test_cartella_in_query_resta_valida(client, spostamenti):
    r = client.post("/mail/3450/move?account_id=2&folder_id=INBOX.idealista")
    assert r.status_code == 200
    assert spostamenti == [(2, "3450", "INBOX.idealista", None)]


def test_senza_cartella_errore_leggibile(client, spostamenti):
    r = client.post("/mail/3450/move?account_id=2", json={})
    assert r.status_code == 400
    assert isinstance(r.json()["detail"], str)
    assert spostamenti == []


def test_stessa_cartella_non_sposta(client, spostamenti):
    r = client.post("/mail/3450/move?account_id=2&source_folder=INBOX",
                    json={"folder_id": "INBOX"})
    assert r.status_code == 400
    assert "gia'" in r.json()["detail"]
    assert spostamenti == []
