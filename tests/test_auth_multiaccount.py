"""Multi-account Microsoft: get_token deve selezionare l'identita' GIUSTA
(niente piu' accounts[0] / 'ultimo login vince') e non avviare mai flussi
interattivi impliciti."""
import json
import os
import threading
from contextvars import copy_context

import pytest

from ade_mail_agent.core import auth


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
    from ade_mail_agent.core import accounts as core_accounts
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


def test_concurrent_requests_keep_their_microsoft_identity(fake_msal, monkeypatch):
    _write_global_cache(["first@x.it", "second@x.it"])
    started = threading.Event()
    resume = threading.Event()
    real_get_app = auth._get_app
    results = {}

    def get_app():
        if threading.current_thread().name == "account-first":
            started.set()
            assert resume.wait(5)
        return real_get_app()

    monkeypatch.setattr(auth, "_get_app", get_app)
    monkeypatch.setattr(auth, "_save_cache", lambda cache: None)

    def first_request():
        auth.set_current_account("first@x.it", 1)
        results["first"] = auth.get_token()

    thread = threading.Thread(target=first_request, name="account-first")
    thread.start()
    try:
        assert started.wait(5)
        auth.set_current_account("second@x.it", 2)
        results["second"] = auth.get_token()
    finally:
        resume.set()
        thread.join(5)
    assert not thread.is_alive()
    assert results == {"first": "tok-first@x.it", "second": "tok-second@x.it"}


def test_child_context_cannot_mutate_parent_identity(fake_msal):
    _write_global_cache(["parent@x.it", "child@x.it"])
    auth.set_current_account("parent@x.it", 1)
    child = copy_context()
    child.run(auth.set_current_account, "child@x.it", 2)
    assert child.run(auth.get_token) == "tok-child@x.it"
    assert auth.get_token() == "tok-parent@x.it"
