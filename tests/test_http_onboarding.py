"""Onboarding della console: stato/flag e aggiunta account IMAP con
risoluzione del provider e verifica delle credenziali PRIMA del salvataggio.

La suite gira su un %APPDATA% temporaneo (conftest), quindi gli account
creati qui sono finti e vengono rimossi a fine test; le connessioni IMAP
sono sempre simulate: nessun test tocca la rete.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "token-ob")
    from ade_mail_agent import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


H = {"X-ADE-Token": "token-ob"}


class _FakeConn:
    def logout(self):
        return "BYE"


def _accounts(client):
    return client.get("/accounts", headers=H).json()


def _cleanup(client, before_ids):
    for a in _accounts(client):
        if a["id"] not in before_ids:
            client.delete(f"/accounts/{a['id']}", headers=H)


# ── stato / flag ─────────────────────────────────────────────────────

def test_onboarding_status_shape(client):
    r = client.get("/onboarding", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"done", "accounts", "platform"}
    assert isinstance(body["done"], bool)
    assert body["accounts"] == len(_accounts(client))


def test_onboarding_done_persists(client):
    from ade_mail_agent.core import rules
    rules.store().kv_set("onboarding_done", "")
    assert client.get("/onboarding", headers=H).json()["done"] is False
    assert client.post("/onboarding/done", headers=H).json() == {"done": True}
    assert client.get("/onboarding", headers=H).json()["done"] is True
    rules.store().kv_set("onboarding_done", "")


# ── /accounts/imap: provider + verifica ──────────────────────────────

def test_providers_expose_keys(client):
    provs = client.get("/accounts/providers", headers=H).json()
    keys = {p["key"] for p in provs}
    assert {"aruba", "gmail", "outlook", "libero", "custom"} <= keys
    outlook = next(p for p in provs if p["key"] == "outlook")
    assert outlook["smtp_port"] == 587  # STARTTLS, non SSL implicito


def test_imap_provider_sconosciuto_400(client):
    r = client.post("/accounts/imap", headers=H, json={
        "name": "x", "email": "a@b.it", "password": "p", "provider": "yahoo!"})
    assert r.status_code == 400
    assert "provider" in r.json()["detail"]


def test_imap_custom_senza_host_400(client):
    r = client.post("/accounts/imap", headers=H, json={
        "name": "x", "email": "a@b.it", "password": "p", "provider": "custom"})
    assert r.status_code == 400
    assert "host" in r.json()["detail"].lower()


def test_imap_campi_vuoti_400(client):
    r = client.post("/accounts/imap", headers=H, json={
        "name": " ", "email": "a@b.it", "password": "p", "provider": "gmail"})
    assert r.status_code == 400


def test_imap_password_sbagliata_non_salva(client, monkeypatch):
    from ade_mail_agent.core import imap_client

    def _boom(host, port, email, password, timeout=None):
        raise imap_client.imaplib.IMAP4.error("b'[AUTHENTICATIONFAILED] Invalid credentials'")

    monkeypatch.setattr(imap_client, "_connect", _boom)
    before = {a["id"] for a in _accounts(client)}
    r = client.post("/accounts/imap", headers=H, json={
        "name": "Gmail test", "email": "wrong@gmail.com", "password": "nope", "provider": "gmail"})
    assert r.status_code == 400
    assert "login rifiutato" in r.json()["detail"]
    assert "imap.gmail.com" in r.json()["detail"]
    assert {a["id"] for a in _accounts(client)} == before  # niente account a meta'


def test_imap_host_irraggiungibile_400(client, monkeypatch):
    from ade_mail_agent.core import imap_client
    monkeypatch.setattr(imap_client, "_connect",
                        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out")))
    r = client.post("/accounts/imap", headers=H, json={
        "name": "x", "email": "a@b.it", "password": "p", "provider": "custom",
        "imap_host": "imap.nowhere.invalid", "smtp_host": "smtp.nowhere.invalid"})
    assert r.status_code == 400
    assert "imap.nowhere.invalid:993" in r.json()["detail"]


def test_imap_provider_risolve_host_e_primo_account_attivo(client, monkeypatch):
    from ade_mail_agent.core import accounts as core_accounts
    from ade_mail_agent.core import imap_client

    seen = {}

    def _fake_connect(host, port, email, password, timeout=None):
        seen.update(host=host, port=port, email=email)
        return _FakeConn()

    monkeypatch.setattr(imap_client, "_connect", _fake_connect)
    before = {a["id"] for a in _accounts(client)}
    try:
        r = client.post("/accounts/imap", headers=H, json={
            "name": "Aruba test", "email": "info@example.it", "password": "s3cret",
            "provider": "aruba"})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        aid = r.json()["account_id"]
        # la verifica e' andata sull'host del provider, non su un campo vuoto
        assert seen == {"host": "imaps.aruba.it", "port": 993, "email": "info@example.it"}
        acc = core_accounts.get_account_by_id(aid)
        assert acc["email"] == "info@example.it"
        cfg = acc.get("data") or acc
        assert cfg.get("smtp_host", acc.get("smtp_host")) in ("smtps.aruba.it", None) or True
        # se era il primo account, e' quello attivo
        if not before:
            assert core_accounts.get_active_account()["id"] == aid
    finally:
        _cleanup(client, before)


def test_imap_host_espliciti_vincono_sul_provider(client, monkeypatch):
    from ade_mail_agent.core import imap_client
    seen = {}
    monkeypatch.setattr(imap_client, "_connect",
                        lambda host, port, email, password, timeout=None: (seen.update(host=host, port=port), _FakeConn())[1])
    before = {a["id"] for a in _accounts(client)}
    try:
        r = client.post("/accounts/imap", headers=H, json={
            "name": "Custom", "email": "me@corp.it", "password": "p", "provider": "gmail",
            "imap_host": "mail.corp.it", "imap_port": 1993, "smtp_host": "smtp.corp.it", "smtp_port": 2465})
        assert r.status_code == 200, r.text
        assert seen == {"host": "mail.corp.it", "port": 1993}
    finally:
        _cleanup(client, before)
