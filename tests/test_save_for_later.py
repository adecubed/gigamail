""""Save" in the approval window: the person keeps a request waiting and
decides later, instead of watching it expire after fifteen minutes.

It stays a pending request: approving it later needs the same
verification, and only a click in the console can save it.
"""
import importlib
import time

import pytest
from fastapi.testclient import TestClient

from gigamail import policy


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


def _request(ttl=900.0):
    return policy.store().create(
        "send_mail", {"to": "mario.rossi@example.com", "account_id": 1},
        {"to": "mario.rossi@example.com", "subject": "Quote", "body": "hello"},
        ttl=ttl)


def test_a_saved_request_waits_days_and_stays_pending():
    rid = _request(ttl=60)
    assert policy.store().save_for_later(rid, by="console:tester")
    rec = policy.store().get(rid)
    assert rec["status"] == policy.PENDING
    assert rec["saved_at"] is not None
    assert rec["expires_at"] > time.time() + 6 * 86400
    assert rid in [r["request_id"] for r in policy.store().list_pending()]


def test_a_saved_request_is_approved_later_as_usual():
    rid = _request(ttl=60)
    policy.store().save_for_later(rid)
    assert policy.store().approve(rid, by="console:tester")
    assert policy.store().consume_approved(rid, "send_mail")["to"] == "mario.rossi@example.com"


def test_saving_again_does_not_shorten_it(monkeypatch):
    rid = _request()
    policy.store().save_for_later(rid)
    first = policy.store().get(rid)["expires_at"]
    monkeypatch.setattr(policy, "_SAVED_TTL_SECONDS", 60)
    assert policy.store().save_for_later(rid)
    assert policy.store().get(rid)["expires_at"] == first


def test_a_decided_or_expired_request_cannot_be_saved():
    rejected = _request()
    policy.store().reject(rejected)
    assert not policy.store().save_for_later(rejected)
    assert policy.store().get(rejected)["status"] == policy.REJECTED

    expired = _request(ttl=-1)
    assert not policy.store().save_for_later(expired)
    assert policy.store().get(expired)["saved_at"] is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "tok")
    from gigamail import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app, headers={"X-ADE-Token": "tok"}) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


def test_the_route_saves_only_on_a_console_click(client, monkeypatch):
    from gigamail.http_api import console_click
    rid = _request(ttl=60)

    monkeypatch.setattr(console_click, "is_console_click", lambda headers: False)
    assert client.post(f"/approvals/{rid}/save").status_code == 403
    assert policy.store().get(rid)["saved_at"] is None

    monkeypatch.setattr(console_click, "is_console_click", lambda headers: True)
    r = client.post(f"/approvals/{rid}/save")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending" and body["expires_at"] > time.time() + 6 * 86400


def test_the_route_refuses_a_request_already_decided(client, monkeypatch):
    from gigamail.http_api import console_click
    monkeypatch.setattr(console_click, "is_console_click", lambda headers: True)
    rid = _request()
    policy.store().reject(rid)
    assert client.post(f"/approvals/{rid}/save").status_code == 409
