"""Console API: scheda Google e interruttore del calendario."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent.core import accounts, google_auth


@pytest.fixture()
def client():
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c


@pytest.fixture(autouse=True)
def db_pulito():
    def svuota():
        with sqlite3.connect(accounts.DB_PATH) as conn:
            conn.execute("DELETE FROM google_identity")
            conn.execute("DELETE FROM app_setting WHERE key='calendar_provider'")
            conn.execute("DELETE FROM accounts")
            conn.commit()
    svuota()
    yield
    svuota()


def test_stato_senza_nulla_collegato(client):
    r = client.get("/google/status")
    assert r.status_code == 200
    d = r.json()
    assert d["connected"] is False
    assert d["calendar_provider"] == "microsoft"
    assert any("drive.file" in s for s in d["scopes"])


def test_stato_mostra_l_identita_senza_segreti(client):
    accounts.save_google_identity("mario@example.com", "Mario",
                                  {"refresh_token": "rt-segreto"})
    d = client.get("/google/status").json()
    assert d["connected"] is True
    assert d["identities"][0]["email"] == "mario@example.com"
    assert "rt-segreto" not in json.dumps(d)


def test_login_senza_client_id_risponde_503(client):
    """Build senza progetto Google Cloud: la console deve poter dire
    'non disponibile', non mostrare un errore generico."""
    if google_auth.is_configured():
        pytest.skip("questa build ha gia' un client OAuth Google")
    r = client.get("/google/auth/login")
    assert r.status_code == 503
    assert "google_config.json" in r.json()["detail"]


def test_interruttore_del_calendario(client):
    accounts.add_microsoft_account("MS", "mario@fingroup.it", "{}")
    accounts.save_google_identity("mario@example.com", "Mario", {"refresh_token": "rt"})

    assert client.get("/calendar/provider").json()["provider"] == "microsoft"

    r = client.post("/calendar/provider/google")
    assert r.status_code == 200 and r.json()["provider"] == "google"
    assert client.get("/calendar/provider").json()["provider"] == "google"

    r = client.post("/calendar/provider/yahoo")
    assert r.status_code == 400


def test_logout_senza_identita_404(client):
    assert client.post("/google/auth/logout").status_code == 404
