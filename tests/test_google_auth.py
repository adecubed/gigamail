"""Flusso OAuth Google: PKCE, difesa CSRF, errori che non vanno ritentati."""

import base64
import hashlib
import sqlite3
import urllib.parse

import pytest

from ade_mail_agent.core import accounts, google_auth


@pytest.fixture()
def configurato(monkeypatch):
    monkeypatch.setattr(google_auth, "CLIENT_ID", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(google_auth, "CLIENT_SECRET", "")
    yield
    google_auth._shutdown_server()
    google_auth.clear_login_flow()


@pytest.fixture(autouse=True)
def senza_identita():
    with sqlite3.connect(accounts.DB_PATH) as conn:
        conn.execute("DELETE FROM google_identity")
        conn.commit()
    google_auth.set_current_identity(None)


def test_senza_client_id_nessun_login():
    """Finche' il progetto Google Cloud non esiste, l'errore deve dire
    esattamente questo invece di fallire in profondita' su una 400."""
    assert google_auth.is_configured() is False
    with pytest.raises(google_auth.NotConfigured):
        google_auth.get_login_url()
    with pytest.raises(google_auth.NotConfigured):
        google_auth.get_token()


def test_url_di_login_ben_formato(configurato):
    dati = google_auth.get_login_url()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(dati["auth_url"]).query)

    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    # Senza questi due Google non rilascia il refresh token e l'accesso
    # morirebbe dopo un'ora.
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    # Loopback su 127.0.0.1 con porta effimera: nessuna porta da registrare.
    assert q["redirect_uri"][0].startswith("http://127.0.0.1:")

    scope = q["scope"][0]
    assert "calendar.events" in scope
    assert "drive.file" in scope
    assert "auth/drive " not in scope + " ", "mai lo scope drive completo"


def test_challenge_derivato_dal_verifier(configurato):
    dati = google_auth.get_login_url()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(dati["auth_url"]).query)
    atteso = base64.urlsafe_b64encode(
        hashlib.sha256(dati["flow"]["verifier"].encode()).digest()
    ).decode().rstrip("=")
    assert q["code_challenge"] == [atteso]


def test_stato_diverso_viene_rifiutato(configurato, monkeypatch):
    """Un redirect con state non corrispondente e' un tentativo di CSRF:
    il codice non deve essere scambiato."""
    dati = google_auth.get_login_url()

    class FintoServer:
        oauth_result = {"code": "codice-iniettato", "state": "non-mio", "error": None}

    monkeypatch.setitem(google_auth.__dict__, "_server", FintoServer())

    chiamate = []
    monkeypatch.setattr(google_auth.requests, "post",
                        lambda *a, **k: chiamate.append(a) or None)

    assert google_auth.complete_login(dati["flow"]) is None
    assert chiamate == [], "il codice non doveva essere scambiato"


def test_senza_redirect_ancora_pending(configurato):
    """La console interroga in loop: finche' l'utente non ha autorizzato
    la risposta e' None, non un errore."""
    dati = google_auth.get_login_url()
    assert google_auth.complete_login(dati["flow"]) is None


def test_token_senza_identita_collegata(configurato):
    with pytest.raises(google_auth.AuthRequired):
        google_auth.get_token()


def test_identita_senza_refresh_token(configurato):
    accounts.save_google_identity("mario@example.com", "Mario", {})
    with pytest.raises(google_auth.AuthRequired):
        google_auth.get_token("mario@example.com")


def test_access_token_in_cache_non_richiama_google(configurato, monkeypatch):
    accounts.save_google_identity("mario@example.com", "Mario",
                                  {"refresh_token": "rt"})
    google_auth._cache_access("mario@example.com", "at-valido", 3600)

    def vietato(*a, **k):
        raise AssertionError("refresh inutile: il token in cache era valido")

    monkeypatch.setattr(google_auth.requests, "post", vietato)
    assert google_auth.get_token("mario@example.com") == "at-valido"


def test_refresh_fallito_chiede_un_nuovo_login(configurato, monkeypatch):
    """invalid_grant significa accesso revocato: va detto come tale,
    altrimenti l'agente ritenta all'infinito."""
    accounts.save_google_identity("mario@example.com", "Mario",
                                  {"refresh_token": "rt-revocato"})
    google_auth._access_cache.pop("mario@example.com", None)

    def esplode(*a, **k):
        raise google_auth.requests.RequestException("400 invalid_grant")

    monkeypatch.setattr(google_auth.requests, "post", esplode)
    with pytest.raises(google_auth.AuthRequired) as e:
        google_auth.get_token("mario@example.com")
    assert "revocato" in str(e.value)


def test_il_favicon_non_cancella_il_codice(configurato):
    """Regressione: il browser, dopo il redirect, chiede /favicon.ico sulla
    stessa porta. Registrare quella richiesta azzerava code e state, e il
    login moriva con 'state non corrispondente' accusando di CSRF un
    redirect legittimo."""
    import urllib.request

    dati = google_auth.get_login_url()
    porta = urllib.parse.urlparse(dati["flow"]["redirect_uri"]).port
    stato = dati["flow"]["state"]

    # 1. il redirect vero di Google
    urllib.request.urlopen(
        f"http://127.0.0.1:{porta}/?code=codice-buono&state={stato}", timeout=5
    ).read()
    # 2. la seconda richiesta del browser, senza parametri
    urllib.request.urlopen(f"http://127.0.0.1:{porta}/favicon.ico", timeout=5).read()

    catturato = google_auth._server.oauth_result
    assert catturato["code"] == "codice-buono"
    assert catturato["state"] == stato


class _FintaRisposta:
    def __init__(self, corpo, testo=""):
        self._corpo = corpo
        self.text = testo

    def json(self):
        if self._corpo is None:
            raise ValueError("non e' JSON")
        return self._corpo


def test_errore_del_token_tradotto_in_rimedio():
    """Google spiega il rifiuto nel corpo, non nello stato HTTP: un
    '401 Unauthorized' da solo non dice se sbagliare sia il secret, il
    tipo di client o un codice gia' consumato."""
    msg = google_auth.spiega_errore_token(
        _FintaRisposta({"error": "invalid_client",
                        "error_description": "Unauthorized"}))
    assert "invalid_client" in msg
    assert "secret" in msg

    msg = google_auth.spiega_errore_token(
        _FintaRisposta({"error": "redirect_uri_mismatch"}))
    assert "Desktop app" in msg

    assert "rete" in google_auth.spiega_errore_token(None)
    assert "non interpretabile" in google_auth.spiega_errore_token(
        _FintaRisposta(None, "<html>errore</html>"))


class _RispostaApi:
    def __init__(self, status, corpo):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._corpo = corpo
        self.text = str(corpo)

    def json(self):
        if self._corpo is None:
            raise ValueError("non e' JSON")
        return self._corpo


def test_api_spenta_lo_dice_invece_di_403():
    """'403 Forbidden' non distingue fra permesso mancante, API spenta sul
    progetto e quota finita. Il messaggio di Google si', e va mostrato."""
    corpo = {"error": {
        "message": "Google Calendar API has not been used in project 123 "
                   "before or it is disabled.",
        "details": [{"reason": "SERVICE_DISABLED"}],
    }}
    with pytest.raises(google_auth.ApiError) as e:
        google_auth.check(_RispostaApi(403, corpo))
    assert "has not been used" in str(e.value)
    assert "Abilitala" in str(e.value)


def test_accesso_revocato_suggerisce_il_login():
    with pytest.raises(google_auth.ApiError) as e:
        google_auth.check(_RispostaApi(401, {"error": {"message": "Invalid Credentials"}}))
    assert "rifai il login" in str(e.value)


def test_risposta_buona_passa_liscia():
    r = _RispostaApi(200, {"items": []})
    assert google_auth.check(r) is r


# -- file credenziali scaricato da Google -------------------------------------

def _scrivi_json(tmp_path, sezione, dati):
    import json as _j
    p = tmp_path / "client_secret_prova.json"
    p.write_text(_j.dumps({sezione: dati}), encoding="utf-8")
    return str(p)


def test_legge_il_json_di_un_client_desktop(tmp_path):
    p = _scrivi_json(tmp_path, "installed", {
        "client_id": "123-abc.apps.googleusercontent.com",
        "client_secret": "GOCSPX-esempio",
        "project_id": "gigamail-1",
    })
    info = google_auth.leggi_client_json(p)
    assert info["client_id"].startswith("123-abc")
    assert info["project_id"] == "gigamail-1"
    assert info["tipo"] == "installed"


def test_client_web_rifiutato_subito(tmp_path):
    """Un client 'Web application' non accetta il redirect di loopback:
    dirlo qui evita tre schermate di browser e un redirect_uri_mismatch."""
    p = _scrivi_json(tmp_path, "web", {"client_id": "x", "client_secret": "y"})
    with pytest.raises(ValueError) as e:
        google_auth.leggi_client_json(p)
    assert "Desktop app" in str(e.value)


def test_json_incompleto_rifiutato(tmp_path):
    p = _scrivi_json(tmp_path, "installed", {"client_id": "solo-id"})
    with pytest.raises(ValueError):
        google_auth.leggi_client_json(p)


def test_credenziali_mai_mescolate_fra_fonti(monkeypatch):
    """Il guasto da evitare: id da una fonte e secret da un'altra. Google
    risponde solo 'invalid_client' e non si capisce dove guardare."""
    monkeypatch.setattr(google_auth, "_G_JSON",
                        {"client_id": "id-del-json",
                         "client_secret": "GOCSPX-del-json"})
    monkeypatch.setattr(google_auth, "_G_CFG", {})

    # solo l'id nell'ambiente: coppia incompleta, si scarta tutta
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-dell-ambiente")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    cid, sec, fonte = google_auth._risolvi_credenziali()
    assert cid == "id-del-json" and sec == "GOCSPX-del-json"
    assert cid != "id-dell-ambiente", "id e secret presi da fonti diverse"

    # coppia completa nell'ambiente: vince tutta intera
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-dell-ambiente")
    cid, sec, fonte = google_auth._risolvi_credenziali()
    assert (cid, sec) == ("id-dell-ambiente", "GOCSPX-dell-ambiente")
    assert "ambiente" in fonte


def test_installa_copia_solo_dopo_aver_validato(tmp_path, monkeypatch):
    cattivo = _scrivi_json(tmp_path, "web", {"client_id": "x", "client_secret": "y"})
    with pytest.raises(ValueError):
        google_auth.installa_client_json(cattivo)
