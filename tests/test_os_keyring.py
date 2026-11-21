"""Accounts key in the OS keyring on macOS/Linux, 0600 file as fallback.

The real Keychain / Secret Service is never touched: a fake backend
stands in for keyring.
"""
import os
import stat
import sys

import pytest
from cryptography.fernet import Fernet

from gigamail.core import accounts as core_accounts
from gigamail.core import os_keyring

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows uses DPAPI (test_dpapi.py)"
)

_PATHS = (
    core_accounts.KEY_PATH,
    core_accounts.KEY_PATH_DPAPI,
    core_accounts.KEY_PATH_KEYRING,
)


class FakeKeyring:
    priority = 5

    def __init__(self):
        self.items = {}
        self.fail = False
        self.corrupt = False

    def get_password(self, service, name):
        if self.fail:
            raise RuntimeError("locked")
        value = self.items.get((service, name))
        if value is not None and self.corrupt:
            return value + "x"
        return value

    def set_password(self, service, name, value):
        if self.fail:
            raise RuntimeError("locked")
        self.items[(service, name)] = value


@pytest.fixture()
def clean_keys():
    """Remove the key files for the test and put back whatever the rest of
    the session had, so accounts saved by other tests still decrypt."""
    saved = {}
    for p in _PATHS:
        if os.path.exists(p):
            with open(p, "rb") as f:
                saved[p] = f.read()
            os.unlink(p)
    yield
    for p in _PATHS:
        if os.path.exists(p):
            os.unlink(p)
    for p, data in saved.items():
        with open(p, "wb") as f:
            f.write(data)


@pytest.fixture()
def fake_keyring(monkeypatch, clean_keys):
    kr = FakeKeyring()
    monkeypatch.setattr(os_keyring, "_backend", lambda: kr)
    return kr


@pytest.fixture()
def no_keyring(monkeypatch, clean_keys):
    monkeypatch.setattr(os_keyring, "_backend", lambda: None)


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_first_run_puts_key_in_keyring(fake_keyring):
    key = core_accounts._get_key()
    assert not os.path.exists(core_accounts.KEY_PATH)  # nothing in clear
    assert os.path.exists(core_accounts.KEY_PATH_KEYRING)
    with open(core_accounts.KEY_PATH_KEYRING, "rb") as f:
        marker = f.read()
    assert key not in marker  # the marker names the entry, not the key
    assert list(fake_keyring.items.values()) == [key.decode()]
    assert core_accounts._get_key() == key  # stable


def test_legacy_clear_key_moves_to_keyring(fake_keyring):
    legacy = Fernet.generate_key()
    with open(core_accounts.KEY_PATH, "wb") as f:
        f.write(legacy)
    assert core_accounts._get_key() == legacy
    assert not os.path.exists(core_accounts.KEY_PATH)
    assert os.path.exists(core_accounts.KEY_PATH_KEYRING)
    assert core_accounts._get_key() == legacy


def test_accounts_still_encrypt_with_keyring(fake_keyring):
    enc = core_accounts._encrypt("imap-password")
    assert core_accounts._decrypt(enc) == "imap-password"


def test_no_keyring_first_run_writes_owner_only_file(no_keyring):
    key = core_accounts._get_key()
    assert os.path.exists(core_accounts.KEY_PATH)
    assert not os.path.exists(core_accounts.KEY_PATH_KEYRING)
    assert _mode(core_accounts.KEY_PATH) == 0o600
    assert core_accounts._get_key() == key


def test_no_keyring_legacy_file_gets_tightened(no_keyring):
    legacy = Fernet.generate_key()
    with open(core_accounts.KEY_PATH, "wb") as f:
        f.write(legacy)
    os.chmod(core_accounts.KEY_PATH, 0o644)
    assert core_accounts._get_key() == legacy
    assert _mode(core_accounts.KEY_PATH) == 0o600


def test_unreachable_keyring_raises_and_never_makes_a_new_key(fake_keyring):
    key = core_accounts._get_key()
    fake_keyring.fail = True
    with pytest.raises(core_accounts.KeyUnavailableError):
        core_accounts._get_key()
    assert not os.path.exists(core_accounts.KEY_PATH)
    fake_keyring.fail = False
    assert core_accounts._get_key() == key


def test_keyring_unreachable_later_on_a_server_raises(fake_keyring, monkeypatch):
    core_accounts._get_key()
    monkeypatch.setattr(os_keyring, "_backend", lambda: None)
    with pytest.raises(core_accounts.KeyUnavailableError):
        core_accounts._get_key()
    assert not os.path.exists(core_accounts.KEY_PATH)


def test_missing_keyring_entry_raises(fake_keyring):
    core_accounts._get_key()
    fake_keyring.items.clear()
    with pytest.raises(core_accounts.KeyUnavailableError):
        core_accounts._get_key()
    assert not os.path.exists(core_accounts.KEY_PATH)


def test_key_that_does_not_read_back_stays_in_file(fake_keyring):
    fake_keyring.corrupt = True
    key = core_accounts._get_key()
    assert not os.path.exists(core_accounts.KEY_PATH_KEYRING)
    assert os.path.exists(core_accounts.KEY_PATH)
    assert _mode(core_accounts.KEY_PATH) == 0o600
    assert core_accounts._get_key() == key


def test_backend_off_by_env(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_OS_KEYRING", "0")
    assert os_keyring._backend() is None
    assert not os_keyring.available()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_backend_off_without_dbus_session(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_OS_KEYRING", "1")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert os_keyring._backend() is None


def test_plain_text_backend_is_refused(monkeypatch):
    keyring = pytest.importorskip("keyring")

    class PlainText:
        priority = 0.5

    monkeypatch.setenv("GIGAMAIL_OS_KEYRING", "1")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/none")
    monkeypatch.setattr(keyring, "get_keyring", lambda: PlainText())
    assert os_keyring._backend() is None


def test_real_backend_is_accepted(monkeypatch):
    keyring = pytest.importorskip("keyring")
    kr = FakeKeyring()
    monkeypatch.setenv("GIGAMAIL_OS_KEYRING", "1")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/none")
    monkeypatch.setattr(keyring, "get_keyring", lambda: kr)
    assert os_keyring._backend() is kr
