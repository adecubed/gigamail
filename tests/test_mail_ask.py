"""Console API: "Chiedi alle mail" deve trovare le mail anche senza agente."""

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent import agent_bridge
from ade_mail_agent.http_api import agent as agent_api


@pytest.fixture()
def client():
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c


@pytest.fixture()
def caselle(monkeypatch):
    cercate = []
    monkeypatch.setattr(agent_api.core_accounts, "get_accounts", lambda: [
        {"id": 1, "email": "napoli@fingroupspa.com"},
        {"id": 2, "email": "info@20128milano.it"}])

    def _cerca(account_id=None, query="", top=10):
        cercate.append((account_id, query))
        if account_id == 1:
            return [{"id": "24417", "folder": "INBOX",
                     "subject": "I: INTERVENTO EDILIZIO\r\n VIA TREVIGLIO 28",
                     "from": {"emailAddress": {"name": '"Fingroup spa"',
                                               "address": "info@fingroupspa.com"}}}]
        if account_id == 2:
            raise RuntimeError("IMAP irraggiungibile")
        return []
    monkeypatch.setattr(agent_api.mail_router, "search_messages", _cerca)
    return cercate


def _agente_scollegato(monkeypatch):
    def _no(prompt, timeout=None):
        raise agent_bridge.AgentUnavailable("Not logged in · Please run /login")
    monkeypatch.setattr(agent_api.agent_bridge, "run", _no)


def test_senza_agente_cerca_in_tutte_le_caselle(client, monkeypatch, caselle):
    """Il 15/09: 'trova mail di berterame' dava '(nessuna risposta)', e la
    mail c'era nella casella di Fingroup."""
    _agente_scollegato(monkeypatch)
    r = client.post("/mail_ask", json={"question": "trova mail di berterame"})
    assert r.status_code == 200
    d = r.json()
    assert caselle == [(1, "berterame"), (2, "berterame")]
    assert d["engine"] == "search"
    assert "Not logged in" in d["answer"] and "1 mail trovate" in d["answer"]
    assert d["cited_mails"] == [{
        "subject": "I: INTERVENTO EDILIZIO VIA TREVIGLIO 28",
        "sender": "napoli@fingroupspa.com · Fingroup spa",
        "message_id": "24417", "folder": "INBOX", "account_id": 1}]


def test_domanda_senza_parole_utili_dice_il_motivo(client, monkeypatch, caselle):
    _agente_scollegato(monkeypatch)
    r = client.post("/mail_ask", json={"question": "trova le mail"})
    assert r.status_code == 503
    assert "Not logged in" in r.json()["detail"]
    assert caselle == []


def test_con_agente_risponde_lagente(client, monkeypatch, caselle):
    monkeypatch.setattr(agent_api.agent_bridge, "run",
                        lambda prompt, timeout=None: "Ci sono due mail di Berterame.")
    d = client.post("/mail_ask", json={"question": "trova mail di berterame"}).json()
    assert d == {"answer": "Ci sono due mail di Berterame.", "engine": "agent"}
    assert caselle == []


def test_risposta_vuota_dellagente_passa_alla_ricerca(client, monkeypatch, caselle):
    monkeypatch.setattr(agent_api.agent_bridge, "run", lambda prompt, timeout=None: "  ")
    d = client.post("/mail_ask", json={"question": "berterame"}).json()
    assert d["engine"] == "search" and d["cited_mails"]


def test_parole_chiave():
    assert agent_api._parole_chiave("Trova le mail di Berterame") == "berterame"
    assert agent_api._parole_chiave("mail dove ho parlato di Cézanne e Monet") == "cézanne monet"
    assert agent_api._parole_chiave("trova le mail") == ""
