"""Console API 0.2.1: regole, watcher, notifiche. Creare/riattivare una
regola passa da consent.require_human anche dal backend (il token della
console non basta); pausa/elimina sono liberi."""
import importlib

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent import policy
from ade_mail_agent.core import rules as rules_mod

H = {"X-ADE-Token": "t-rules"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "t-rules")
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    from ade_mail_agent import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app) as c:
        yield c
    rules_mod.set_store(None)
    policy.set_store(None)
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


BODY = {"account_id": 1, "trigger_kind": "senders",
        "trigger_values": ["Cliente@Fidato.it"], "reply_style": "cordiale",
        "doc_paths": [], "mode": "semi"}


def test_create_senza_consenso_403(client):
    # conftest: GIGAMAIL_CONSENT_BACKEND=deny
    r = client.post("/rules", json=BODY, headers=H)
    assert r.status_code == 403
    assert client.get("/rules", headers=H).json() == []


def test_create_con_consenso_dryrun(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    r = client.post("/rules", json=BODY, headers=H)
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["trigger_values"] == ["cliente@fidato.it"]  # normalizzato
    assert rule["state"] == "active" and rule["sent_today"] == 0
    assert rule["created_by"].startswith("console")


def test_pause_libera_resume_con_hello(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    rid = client.post("/rules", json=BODY, headers=H).json()["rule_id"]
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert client.post(f"/rules/{rid}/pause", headers=H).json()["state"] == "paused"
    assert client.post(f"/rules/{rid}/resume", headers=H).status_code == 403
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    assert client.post(f"/rules/{rid}/resume", headers=H).json()["state"] == "active"
    assert client.delete(f"/rules/{rid}", headers=H).json()["success"]
    assert client.get("/rules", headers=H).json() == []


def test_validazioni(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    bad = dict(BODY, doc_paths=["C:/nonexistent/listino.pdf"])
    assert client.post("/rules", json=bad, headers=H).status_code == 400
    assert client.post("/rules", json=dict(BODY, mode="yolo"), headers=H).status_code == 400
    assert client.post("/rules", json=dict(BODY, trigger_values=[" "]), headers=H).status_code == 400


def test_watch_status_senza_processo(client):
    st = client.get("/watch/status", headers=H).json()
    assert st["running"] is False and st["pid"] is None
    assert client.get("/watch/log", headers=H).json() == []


def test_notify_status_forma(client):
    st = client.get("/notify/status", headers=H).json()
    assert set(st) >= {"agent", "consent_backend", "desktop", "telegram", "lang"}
    assert st["telegram"]["configured"] is False
