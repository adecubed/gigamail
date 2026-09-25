"""Console API: bozze salvate in locale mentre si scrive.

Fino al 25/09 la console chiamava /mail/draft/save ma il backend non
l'aveva: Features lo vedeva assente, il salvataggio automatico non partiva
e una finestra chiusa per sbaglio si portava via il testo.
"""

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent.core import drafts


@pytest.fixture()
def client(tmp_path):
    drafts.set_store(drafts.DraftStore(tmp_path / "drafts.db"))
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c
    drafts.set_store(None)


def test_endpoint_dichiarato_per_la_console(client):
    """Features.has('/mail/draft/save') accende il salvataggio automatico."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/mail/draft/save" in paths
    assert "/mail/draft/local" in paths
    assert "/mail/draft/local/{draft_id}" in paths


def test_salvataggi_successivi_aggiornano_la_stessa_bozza(client):
    r = client.post("/mail/draft/save", json={
        "to": "anna@example.com", "subject": "Visita", "body": "Buongiorno",
        "account_id": 2})
    assert r.status_code == 200
    draft_id = r.json()["id"]

    r = client.post("/mail/draft/save", json={
        "id": draft_id, "to": "anna@example.com", "cc": "luca@example.com",
        "subject": "Visita", "body": "Buongiorno Anna,", "account_id": 2})
    assert r.json()["id"] == draft_id

    elenco = client.get("/mail/draft/local?account_id=2").json()
    assert len(elenco) == 1
    assert elenco[0]["body"] == "Buongiorno Anna,"
    assert elenco[0]["cc"] == "luca@example.com"


def test_id_scelto_dalla_console_viene_creato(client):
    """La finestra genera l'id prima del primo salvataggio: se il DB non la
    conosce la crea, non perde il testo."""
    r = client.post("/mail/draft/save", json={"id": "abc123", "body": "x"})
    assert r.status_code == 200 and r.json()["id"] == "abc123"
    assert client.get("/mail/draft/local/abc123").json()["body"] == "x"


def test_elenco_filtrato_per_account_e_piu_recenti_prima(client):
    client.post("/mail/draft/save", json={"body": "vecchia", "account_id": 1})
    client.post("/mail/draft/save", json={"body": "altro account", "account_id": 3})
    client.post("/mail/draft/save", json={"body": "nuova", "account_id": 1})
    corpi = [d["body"] for d in client.get("/mail/draft/local?account_id=1").json()]
    assert corpi == ["nuova", "vecchia"]


def test_cancellazione_idempotente(client):
    draft_id = client.post("/mail/draft/save", json={"body": "ciao"}).json()["id"]
    assert client.delete(f"/mail/draft/local/{draft_id}").json() == {
        "success": True, "deleted": True}
    assert client.delete(f"/mail/draft/local/{draft_id}").json() == {
        "success": True, "deleted": False}
    assert client.get(f"/mail/draft/local/{draft_id}").status_code == 404


def test_id_malformato_rifiutato(client):
    assert client.post("/mail/draft/save",
                       json={"id": "../x", "body": "a"}).status_code == 422
    assert client.get("/mail/draft/local/a%20b").status_code == 422


def test_corpo_enorme_rifiutato_con_messaggio(client):
    r = client.post("/mail/draft/save",
                    json={"body": "x" * (drafts.MAX_BODY_CHARS + 1)})
    assert r.status_code == 413
    assert "troppo lungo" in r.json()["detail"]


def test_la_bozza_sopravvive_a_un_nuovo_store(tmp_path):
    """Il punto di tutto: riaprire la console ritrova il testo."""
    db = tmp_path / "persist.db"
    d = drafts.DraftStore(db).save(None, account_id=1, subject="Preventivo",
                                   body="Gentile cliente")
    riletta = drafts.DraftStore(db).get(d["draft_id"])
    assert riletta["subject"] == "Preventivo"
    assert riletta["body"] == "Gentile cliente"
