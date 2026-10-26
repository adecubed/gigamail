"""GET /mail/{id}: a mail that is no longer there is a 404, not a 500.

A console left open overnight lists mails the watcher has since archived
or moved; opening one raised ValueError, which reached the client as a 500
and printed a full traceback in the console log on every click."""
import importlib

from fastapi.testclient import TestClient


def _client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "tok-read")
    from gigamail import http_api
    importlib.reload(http_api)
    return TestClient(http_api.app)


def test_a_mail_no_longer_on_the_server_is_404(monkeypatch):
    client = _client(monkeypatch)
    from gigamail.http_api import mail as mail_api

    def gone(account_id=None, message_id="", folder=""):
        raise ValueError(f"IMAP message not found for id: '{message_id}'")

    monkeypatch.setattr(mail_api.mail_router, "get_message", gone)
    r = client.get("/mail/42?account_id=2", headers={"X-ADE-Token": "tok-read"})
    assert r.status_code == 404
    assert "42" in r.json()["detail"]


def test_a_mail_found_is_returned_with_its_folder(monkeypatch):
    client = _client(monkeypatch)
    from gigamail.http_api import mail as mail_api
    seen = {}

    def found(account_id=None, message_id="", folder=""):
        seen.update(account_id=account_id, message_id=message_id, folder=folder)
        return {"id": message_id, "subject": "Viewing request"}

    monkeypatch.setattr(mail_api.mail_router, "get_message", found)
    r = client.get("/mail/7?account_id=2&folder=Sent",
                   headers={"X-ADE-Token": "tok-read"})
    assert r.status_code == 200
    assert r.json()["subject"] == "Viewing request"
    assert seen == {"account_id": 2, "message_id": "7", "folder": "Sent"}
