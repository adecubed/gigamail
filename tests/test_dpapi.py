"""DPAPI: protezione chiave account legata all'utente Windows."""
import os
import sys

import pytest

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import win_dpapi

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="DPAPI solo su Windows"
)


def test_roundtrip():
    data = b"chiave-segretissima-1234"
    protected = win_dpapi.protect(data)
    assert protected != data
    assert win_dpapi.unprotect(protected) == data


def test_dati_corrotti_rifiutati():
    with pytest.raises(OSError):
        win_dpapi.unprotect(b"garbage-non-dpapi")


@pytest.fixture()
def clean_keys():
    for p in (core_accounts.KEY_PATH, core_accounts.KEY_PATH_DPAPI):
        if os.path.exists(p):
            os.unlink(p)
    yield
    for p in (core_accounts.KEY_PATH, core_accounts.KEY_PATH_DPAPI):
        if os.path.exists(p):
            os.unlink(p)


def test_prima_esecuzione_crea_chiave_protetta(clean_keys):
    key = core_accounts._get_key()
    assert os.path.exists(core_accounts.KEY_PATH_DPAPI)
    assert not os.path.exists(core_accounts.KEY_PATH)  # niente chiaro su disco
    # su disco NON c'e' la chiave in chiaro
    with open(core_accounts.KEY_PATH_DPAPI, "rb") as f:
        assert key not in f.read()
    assert core_accounts._get_key() == key  # stabile


def test_migrazione_chiave_legacy(clean_keys):
    from cryptography.fernet import Fernet
    legacy = Fernet.generate_key()
    with open(core_accounts.KEY_PATH, "wb") as f:
        f.write(legacy)
    key = core_accounts._get_key()
    assert key == legacy                                   # stessa chiave
    assert not os.path.exists(core_accounts.KEY_PATH)      # chiaro rimosso
    assert os.path.exists(core_accounts.KEY_PATH_DPAPI)    # protetto creato
    assert core_accounts._get_key() == legacy              # rilettura ok


def test_cifratura_account_continua_a_funzionare(clean_keys):
    enc = core_accounts._encrypt("password-imap")
    assert core_accounts._decrypt(enc) == "password-imap"
