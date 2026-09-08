"""GET /mail/{id}/attachment/{filename}: i byte dell'allegato per la console.

La route mancava: la console la chiamava (preload getAttachmentUrl) e
riceveva 404 su qualunque allegato, Graph o IMAP."""
import importlib

from fastapi.testclient import TestClient


def _client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "tok-att")
    from ade_mail_agent import http_api
    importlib.reload(http_api)
    return TestClient(http_api.app), http_api


def test_allegato_scaricato_con_nome_e_tipo(monkeypatch):
    client, http_api = _client(monkeypatch)
    from ade_mail_agent.http_api import mail as mail_api
    visti = {}

    def finto(account_id=None, message_id="", filename="", folder=""):
        visti.update(account_id=account_id, message_id=message_id, filename=filename, folder=folder)
        return b"%PDF-1.4 finto", "application/pdf"

    monkeypatch.setattr(mail_api.mail_router, "get_attachment", finto)
    r = client.get("/mail/123/attachment/Via%20Acerbi%2030_Richieste%20palestra.pdf?folder=INBOX&account_id=2",
                   headers={"X-ADE-Token": "tok-att"})
    assert r.status_code == 200, r.text
    assert r.content == b"%PDF-1.4 finto"
    assert r.headers["content-type"].startswith("application/pdf")
    assert "Via Acerbi 30_Richieste palestra.pdf" in r.headers["content-disposition"]
    assert visti == {"account_id": 2, "message_id": "123",
                     "filename": "Via Acerbi 30_Richieste palestra.pdf", "folder": "INBOX"}


def test_allegato_inesistente_e_404_con_motivo(monkeypatch):
    client, http_api = _client(monkeypatch)
    from ade_mail_agent.http_api import mail as mail_api

    def manca(**kw):
        raise ValueError('Allegato "x.pdf" non trovato nella mail 9')

    monkeypatch.setattr(mail_api.mail_router, "get_attachment", manca)
    r = client.get("/mail/9/attachment/x.pdf", headers={"X-ADE-Token": "tok-att"})
    assert r.status_code == 404
    assert "non trovato" in r.json()["detail"]


def test_tipo_dedotto_dal_nome_se_il_provider_non_lo_dice(monkeypatch):
    client, http_api = _client(monkeypatch)
    from ade_mail_agent.http_api import mail as mail_api
    monkeypatch.setattr(mail_api.mail_router, "get_attachment", lambda **kw: (b"a,b\n1,2\n", None))
    r = client.get("/mail/1/attachment/dati.csv", headers={"X-ADE-Token": "tok-att"})
    assert r.status_code == 200
    # tabella della libreria standard, non il registro di Windows (che
    # direbbe application/vnd.ms-excel)
    assert r.headers["content-type"].startswith("text/csv")
