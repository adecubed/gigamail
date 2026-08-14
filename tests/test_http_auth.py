"""Console API: middleware token e endpoint base su ambiente isolato."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client_con_token(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "token-test-123")
    from ade_mail_agent import http_api
    importlib.reload(http_api)  # rilegge il token dall'ambiente
    with TestClient(http_api.app) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


H = {"X-ADE-Token": "token-test-123"}


def test_senza_token_401(client_con_token):
    assert client_con_token.get("/accounts").status_code == 401


def test_token_sbagliato_401(client_con_token):
    r = client_con_token.get("/accounts", headers={"X-ADE-Token": "sbagliato"})
    assert r.status_code == 401


def test_token_giusto_passa(client_con_token):
    r = client_con_token.get("/health", headers=H)
    assert r.status_code == 200
    assert r.json()["service"] == "gigamail-console"


def test_options_esente_per_cors(client_con_token):
    r = client_con_token.options(
        "/accounts",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)


def test_accounts_lista_senza_credenziali(client_con_token):
    r = client_con_token.get("/accounts", headers=H)
    assert r.status_code == 200
    for a in r.json():
        assert "data_enc" not in a and "password" not in a and "token_cache" not in a


def test_audit_endpoint_vuoto_o_lista(client_con_token):
    r = client_con_token.get("/audit", headers=H)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_agent_status_forma(client_con_token):
    r = client_con_token.get("/agent/status", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"available", "command", "timeout"}
