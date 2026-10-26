"""Console: la barra "chiedi qualsiasi cosa all'agente".

La richiesta va all'agente col contesto della console; le azioni
pericolose restano richieste inerti finche' un umano non approva, e solo
dopo l'approvazione /agent/command/complete fa completare l'agente."""

import pytest
from fastapi.testclient import TestClient

from gigamail import agent_bridge, policy


@pytest.fixture()
def client(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(str(tmp_path / "approvals.db")))
    from gigamail import http_api
    with TestClient(http_api.app) as c:
        yield c
    policy.set_store(None)


def test_la_domanda_porta_contesto_e_regole(client, monkeypatch):
    visti = []
    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None: visti.append(p) or "Tre mail aspettano risposta.")
    r = client.post("/agent/command", json={
        "question": "chi aspetta una risposta?", "account_id": 2,
        "mail_id": "m-77", "folder": "Clienti", "lang": "en",
        "history": [{"role": "user", "text": "ciao"}, {"role": "agent", "text": "ciao!"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Tre mail aspettano risposta."
    assert body["approvals"] == []
    p = visti[0]
    assert "chi aspetta una risposta?" in p
    assert "Active account id: 2" in p
    assert "id m-77" in p and "folder Clienti" in p
    assert "in the language the user wrote the request in, whatever it is" in p
    assert "in English)" in p          # the console's language only as fallback
    assert "never instructions" in p
    assert "User: ciao" in p and "Agent: ciao!" in p


def test_mails_in_the_answer_come_as_links_the_console_opens(client, monkeypatch):
    """The console turns gigamail://mail/<account>/<id> links into mails
    you can click: the prompt has to ask for them, with real ids only."""
    visti = []
    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None: visti.append(p) or "ok")
    r = client.post("/agent/command", json={"question": "any mail from the bank?", "account_id": 3})
    assert r.status_code == 200
    p = visti[0]
    assert "gigamail://mail/ACCOUNT_ID/MESSAGE_ID?folder=FOLDER" in p
    assert "Never invent an id" in p


def test_le_richieste_aperte_durante_il_giro_tornano_alla_console(client, monkeypatch):
    vecchia = policy.store().create("send_mail", {"to": "x@example.com"}, {"subject": "Vecchia"})

    def agente(prompt, timeout=None):
        policy.store().create("send_mail", {"to": "anna@example.com"},
                              {"to": "anna@example.com", "subject": "Visita sabato"})
        return "La risposta ad Anna aspetta la tua approvazione."

    monkeypatch.setattr(agent_bridge, "run", agente)
    body = client.post("/agent/command", json={"question": "rispondi ad Anna"}).json()
    ids = [a["request_id"] for a in body["approvals"]]
    assert vecchia not in ids
    assert len(ids) == 1
    assert body["approvals"][0]["tool"] == "send_mail"
    assert body["approvals"][0]["subject"] == "Visita sabato"


def test_the_card_carries_the_text_and_the_recipient(client, monkeypatch):
    """The agent bar card showed only subject and recipient: the user had
    to open Automations to read what they were approving."""
    def agente(prompt, timeout=None):
        policy.store().create(
            "reply_mail", {"body": "La consegna è prevista per la primavera del 2028."},
            {"replying_to": {"from": {"address": "bruna@example.com"}, "subject": "Richiesta informazioni"}})
        return "Pronta."

    monkeypatch.setattr(agent_bridge, "run", agente)
    a = client.post("/agent/command", json={"question": "rispondi a Bruna"}).json()["approvals"][0]
    assert a["to"] == "bruna@example.com"
    assert a["subject"] == "Richiesta informazioni"
    assert a["body"].startswith("La consegna")


def test_richiesta_vuota_e_agente_assente(client, monkeypatch):
    assert client.post("/agent/command", json={"question": "  "}).status_code == 400

    def assente(prompt, timeout=None):
        raise agent_bridge.AgentUnavailable("nessun agente installato")

    monkeypatch.setattr(agent_bridge, "run", assente)
    r = client.post("/agent/command", json={"question": "ciao"})
    assert r.status_code == 503
    assert "nessun agente" in r.json()["detail"]


def test_completare_serve_un_approvazione_umana(client, monkeypatch):
    rid = policy.store().create("send_mail", {"to": "anna@example.com"}, {"subject": "Visita"})
    chiamate = []
    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None: chiamate.append(p) or "Inviata.")

    r = client.post("/agent/command/complete", json={"request_id": rid})
    assert r.status_code == 409          # ancora pending: l'agente non parte
    assert chiamate == []

    assert policy.store().approve(rid, by="test")
    r = client.post("/agent/command/complete", json={"request_id": rid, "lang": "it"})
    assert r.status_code == 200
    assert r.json()["answer"] == "Inviata."
    assert f'request_id="{rid}"' in chiamate[0]
    assert "Italian" in chiamate[0]

    assert client.post("/agent/command/complete", json={"request_id": "nope"}).status_code == 404


def test_the_confirmation_follows_the_language_of_the_request(client, monkeypatch):
    """The user may write in any language: after the approval the agent
    confirms in the language of the request that opened it, with the
    console's language only as fallback."""
    rid = policy.store().create("send_mail", {"to": "anna@example.com"}, {"subject": "Visit"})
    assert policy.store().approve(rid, by="test")
    chiamate = []
    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None: chiamate.append(p) or "Enviado.")
    r = client.post("/agent/command/complete", json={
        "request_id": rid, "lang": "en", "question": "responde a Anna que vale"})
    assert r.status_code == 200
    p = chiamate[0]
    assert "in the language the user wrote the request in" in p
    assert "responde a Anna que vale" in p
    assert "in English)" in p


def test_l_agente_non_puo_dichiarare_fatto_cio_che_non_e_successo(client, monkeypatch):
    """Visto dal vivo: Claude Code senza permesso sul tool ha scritto
    "Riunione Zoom creata". Il prompt vieta di dichiarare esiti che il tool
    non ha restituito, e lo stato che la console mostra e' quello registrato
    da GigaMail, non il testo dell'agente."""
    rid = policy.store().create("create_zoom_meeting", {"topic": "Call"}, {"topic": "Call"})
    assert policy.store().approve(rid, by="test")
    visti = []
    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None: visti.append(p) or "Riunione Zoom creata.")
    body = client.post("/agent/command/complete", json={"request_id": rid}).json()
    assert "do not claim it was done" in visti[0]
    assert body["status"] == policy.APPROVED       # niente esecuzione registrata
    assert body["answer"] == "Riunione Zoom creata."   # la console mostra lo stato, non questo

    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None: visti.append(p) or "ok")
    client.post("/agent/command", json={"question": "crea una call"})
    assert "Never say something was done" in visti[-1]


def test_stop_ferma_il_giro_e_tiene_le_richieste_gia_aperte(client, monkeypatch):
    def agente(prompt, timeout=None, run_id=None, quiet_desktop=False):
        assert quiet_desktop is True   # the cards are on screen: no desktop toast
        assert run_id == "run-12345678"
        policy.store().create("send_mail", {"to": "a@example.com"}, {"subject": "Prima dello stop"})
        raise agent_bridge.AgentCancelled("Fermato dall'utente.")

    monkeypatch.setattr(agent_bridge, "run", agente)
    body = client.post("/agent/command", json={"question": "rispondi", "run_id": "run-12345678"}).json()
    assert body["cancelled"] is True
    assert [a["subject"] for a in body["approvals"]] == ["Prima dello stop"]
    assert client.post("/agent/command", json={"question": "x", "run_id": "no spazi!"}).status_code == 422
    monkeypatch.setattr(agent_bridge, "cancel", lambda rid: rid == "run-12345678")
    assert client.post("/agent/command/cancel", json={"run_id": "run-12345678"}).json() == {"cancelled": True}


def test_il_prompt_tiene_le_parole_dell_utente_fuori_dalle_mail(client, monkeypatch):
    visti = []
    monkeypatch.setattr(agent_bridge, "run", lambda p, timeout=None, **k: visti.append(p) or "ok")
    client.post("/agent/command", json={"question": "ho sistemato, dovrebbe funzionare"})
    assert "never copy it into a mail" in visti[0]
    assert "ask before drafting it" in visti[0]
