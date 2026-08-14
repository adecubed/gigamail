"""Multi-account Microsoft: get_token deve selezionare l'identita' GIUSTA
(niente piu' accounts[0] / 'ultimo login vince') e non avviare mai flussi
interattivi impliciti."""
import json
import os

import pytest

import auth


class FakeCache:
    def __init__(self):
        self.accounts = []
        self.has_state_changed = False

    def deserialize(self, s):
        try:
            self.accounts = json.loads(s).get("accounts", [])
        except Exception:
            self.accounts = []

    def serialize(self):
        return json.dumps({"accounts": self.accounts})


class FakeApp:
    def __init__(self, client_id, authority=None, token_cache=None):
        self.cache = token_cache

    def get_accounts(self):
        return [{"username": u} for u in self.cache.accounts]

    def acquire_token_silent(self, scopes, account=None):
        self.cache.has_state_changed = True
        return {"access_token": "tok-" + account["username"]}


class FakeMsal:
    SerializableTokenCache = FakeCache
    PublicClientApplication = FakeApp


@pytest.fixture()
def fake_msal(monkeypatch):
    monkeypatch.setattr(auth, "msal", FakeMsal)
    auth.clear_current_account()
    yield
    auth.clear_current_account()
    if os.path.exists(auth.TOKEN_PATH):
        os.unlink(auth.TOKEN_PATH)


def _write_global_cache(usernames):
    with open(auth.TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps({"accounts": usernames}))


def test_seleziona_identita_per_email_non_accounts0(fake_msal):
    _write_global_cache(["primo@x.it", "secondo@x.it"])
    auth.set_current_account("secondo@x.it", account_id=2)
    assert auth.get_token() == "tok-secondo@x.it"


def test_senza_contesto_compat_accounts0(fake_msal):
    _write_global_cache(["primo@x.it", "secondo@x.it"])
    assert auth.get_token() == "tok-primo@x.it"


def test_email_ignota_senza_seed_auth_required(fake_msal):
    _write_global_cache(["primo@x.it"])
    auth.set_current_account("sconosciuto@x.it", account_id=9)
    with pytest.raises(auth.AuthRequired):
        auth.get_token()


def test_email_ignota_MAI_fallback_su_altra_identita(fake_msal):
    """Il bug originale: con email esplicita non si deve MAI ricevere il
    token di un altro account."""
    _write_global_cache(["primo@x.it"])
    auth.set_current_account("sconosciuto@x.it", account_id=9)
    try:
        tok = auth.get_token()
    except auth.AuthRequired:
        return
    assert tok != "tok-primo@x.it"


def test_seed_dal_db_quando_manca_dalla_cache_globale(fake_msal, monkeypatch):
    _write_global_cache(["primo@x.it"])
    seed = json.dumps({"accounts": ["db-only@x.it"]})
    auth.set_current_account("db-only@x.it", account_id=7, token_cache_json=seed)

    persisted = {}
    import accounts as core_accounts
    monkeypatch.setattr(core_accounts, "update_microsoft_token",
                        lambda aid, tc: persisted.update(aid=aid))
    assert auth.get_token() == "tok-db-only@x.it"
    assert persisted.get("aid") == 7  # il refresh torna nel DB per-account


def test_nessun_account_niente_device_flow_implicito(fake_msal):
    """Prima: senza token partiva un device flow interattivo DENTRO get_token
    (blocco del server). Ora: AuthRequired, subito."""
    if os.path.exists(auth.TOKEN_PATH):
        os.unlink(auth.TOKEN_PATH)
    with pytest.raises(auth.AuthRequired):
        auth.get_token()


def test_case_insensitive_email(fake_msal):
    _write_global_cache(["Simone@X.it"])
    auth.set_current_account("simone@x.it", account_id=1)
    assert auth.get_token() == "tok-Simone@X.it"
