"""A valid console token alone must never authorize a dangerous write."""
import importlib

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent import consent, policy
from ade_mail_agent.http_api import calendar, mail


@pytest.fixture
def client(monkeypatch):
    from ade_mail_agent import http_api
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "local-test-token")
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    monkeypatch.setattr(calendar.calendar_router, "bind_action",
                        lambda operation: getattr(calendar.calendar_router, operation))
    importlib.reload(http_api)
    with TestClient(http_api.app, headers={"X-ADE-Token": "local-test-token"}) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


ACTIONS = [
    ("POST", "/mail/send", {"account_id": 1, "to": "client@example.test", "body": "hello"}, mail.mail_router, "send_message"),
    ("DELETE", "/mail/42?account_id=1", None, mail.mail_router, "delete_message"),
    ("DELETE", "/mail/folders/Leads?account_id=1", None, mail.mail_router, "delete_folder"),
    ("POST", "/mail/42/move?account_id=1", {"folder_id": "Archive"}, mail.mail_router, "move_to_folder"),
    ("POST", "/mail/42/spam?account_id=1", None, mail.mail_router, "move_to_folder"),
    ("POST", "/mail/42/not_spam?account_id=1", None, mail.mail_router, "move_to_folder"),
    ("POST", "/calendar", {"subject": "Meeting", "start": "2026-10-01T10:00", "end": "2026-10-01T11:00"}, calendar.calendar_router, "create_event"),
    ("PATCH", "/calendar/event", {"subject": "Changed"}, calendar.calendar_router, "update_event"),
    ("DELETE", "/calendar/event", None, calendar.calendar_router, "delete_event"),
]


@pytest.mark.parametrize("method,url,body,provider,name", ACTIONS)
@pytest.mark.parametrize("decision,expected", [(False, 403), ("unavailable", 503)])
def test_token_cannot_bypass_human(client, monkeypatch, method, url, body, provider, name, decision, expected):
    calls = []
    monkeypatch.setattr(provider, name, lambda *a, **kw: calls.append(kw) or True)

    def verify(reason):
        if decision == "unavailable":
            raise consent.ConsentUnavailable("No OS verifier")
        return decision

    monkeypatch.setattr(consent, "require_human", verify)
    response = client.request(method, url, json=body)
    assert response.status_code == expected
    assert calls == []


def test_send_keeps_account_selected_before_consent(client, monkeypatch):
    active = [1]
    sent = []
    monkeypatch.setattr(mail, "_active_id", lambda: active[0])
    monkeypatch.setattr(mail, "_save_address", lambda addr: None)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})

    def verify(reason):
        active[0] = 2
        return True

    monkeypatch.setattr(consent, "require_human", verify)
    response = client.post("/mail/send", json={"to": "client@example.test", "body": "hello"})
    assert response.status_code == 200
    assert sent[0]["account_id"] == 1


def test_dryrun_consent_never_sends(client, monkeypatch):
    sent = []
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: sent.append(kw))
    response = client.post("/mail/send", json={"account_id": 1, "to": "client@example.test"})
    assert response.status_code == 200
    assert response.json()["dryrun"] is True
    assert sent == []


def test_popup_account_query_and_attachment_objects_reach_provider(client, monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "_active_id", lambda: 2)
    monkeypatch.setattr(mail, "_save_address", lambda addr: None)
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})
    attachment = {"name": "plan.txt", "data_b64": "aGVsbG8=", "type": "text/plain"}
    response = client.post("/mail/send?account_id=1", json={
        "to": "client@example.test", "attachments": [attachment]})
    assert response.status_code == 200
    assert sent[0]["account_id"] == 1
    assert sent[0]["attachments"] == [attachment]


def test_failed_send_is_audited_as_failed(client, monkeypatch):
    outcomes = []
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: {"success": False, "error": "provider rejected"})
    monkeypatch.setattr(policy, "audit", lambda tool, args, outcome, **kw: outcomes.append(outcome))
    response = client.post("/mail/send", json={"account_id": 1, "to": "client@example.test"})
    assert response.json()["success"] is False
    assert outcomes == ["failed"]


def test_audit_failure_does_not_report_completed_send_as_failed(client, monkeypatch, caplog):
    sent = []
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.setattr(mail, "_save_address", lambda address: None)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})

    def broken_audit(*args, **kwargs):
        raise OSError("volume full")

    monkeypatch.setattr(policy, "audit", broken_audit)
    response = client.post("/mail/send", json={"account_id": 1, "to": "client@example.test"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(sent) == 1
    assert "Cannot record console action outcome" in caplog.text


def test_address_book_failure_preserves_successful_send(client, monkeypatch):
    sent = []
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})

    def broken_address_book(address):
        raise OSError("volume full")

    monkeypatch.setattr(mail, "_save_address", broken_address_book)
    response = client.post("/mail/send", json={"account_id": 1, "to": "client@example.test"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(sent) == 1
