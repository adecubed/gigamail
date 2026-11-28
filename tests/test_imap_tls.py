"""Il certificato del server IMAP si verifica. Prima nessuno lo faceva:
su una rete ostile la password IMAP andava a chi si metteva in mezzo."""
import ssl

import pytest

from gigamail.core import imap_client, mail_router


@pytest.fixture(autouse=True)
def pulito():
    imap_client._TLS_NON_VERIFICATO.clear()
    yield
    imap_client._TLS_NON_VERIFICATO.clear()


def test_di_default_il_certificato_si_verifica():
    ctx = imap_client._tls_context("imap.example.com", 993, "a@example.com")
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname


def test_insecure_tls_vale_solo_per_quell_account():
    mail_router._imap_credentials({"email": "a@example.com", "data": {
        "imap_host": "IMAP.example.com", "imap_port": 993, "password": "x",
        "insecure_tls": True}})
    assert imap_client._tls_context("imap.example.com", 993,
                                    "A@example.com").verify_mode == ssl.CERT_NONE
    assert imap_client._tls_context("imap.example.com", 993,
                                    "b@example.com").verify_mode == ssl.CERT_REQUIRED
    assert imap_client._tls_context("altro.example.com", 993,
                                    "a@example.com").verify_mode == ssl.CERT_REQUIRED


def test_senza_flag_nessuna_eccezione():
    mail_router._imap_credentials({"email": "a@example.com", "data": {
        "imap_host": "imap.example.com", "imap_port": 993, "password": "x"}})
    assert not imap_client._TLS_NON_VERIFICATO


def test_certificato_rifiutato_non_si_ritenta_e_dice_cosa_fare(monkeypatch):
    tentativi = []

    def rifiuta(*a, **kw):
        tentativi.append(1)
        e = ssl.SSLCertVerificationError(1, "certificate verify failed")
        e.verify_message = "self-signed certificate"
        raise e
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", rifiuta)
    with pytest.raises(imap_client.CertificatoNonValido) as info:
        imap_client._connect("imap.example.com", 993, "a@example.com", "x")
    assert len(tentativi) == 1                 # la password non riparte
    assert "accounts tls" in str(info.value)


def test_cli_tls_insecure_chiede_la_verifica(tmp_path, monkeypatch):
    from gigamail import cli
    from gigamail.core import accounts

    aid = accounts.add_imap_account("T", "t@example.com", "x", "imap.example.com",
                                    993, "smtp.example.com", 465)
    try:
        monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
        assert cli.main(["accounts", "tls", str(aid), "--insecure"]) == 1
        assert not accounts.get_account_by_id(aid)["data"].get("insecure_tls")
        monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
        monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
        assert cli.main(["accounts", "tls", str(aid), "--insecure"]) == 0
        assert accounts.get_account_by_id(aid)["data"]["insecure_tls"] is True
        monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
        assert cli.main(["accounts", "tls", str(aid), "--verify"]) == 0
        assert "insecure_tls" not in accounts.get_account_by_id(aid)["data"]
    finally:
        accounts.delete_account(aid)


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST", "127.0.0.1", "::1",
                                  "[::1]", "bridge.localhost"])
def test_loopback_host_skips_certificate_check(host):
    # Local bridges (Proton Bridge) use a self-signed certificate and the
    # traffic never leaves the machine.
    ctx = imap_client._tls_context(host, 1143, "a@example.com")
    assert ctx.verify_mode == ssl.CERT_NONE


@pytest.mark.parametrize("host", ["imap.example.com", "10.0.0.5", "localhost.example.com"])
def test_remote_host_still_verifies_certificate(host):
    ctx = imap_client._tls_context(host, 1143, "a@example.com")
    assert ctx.verify_mode == ssl.CERT_REQUIRED


class _FakePlainImap:
    """Plain IMAP connection whose STARTTLS succeeds or fails."""
    instances = []
    error = imap_client.imaplib.IMAP4.error
    abort = imap_client.imaplib.IMAP4.abort

    def __init__(self, host, port, *, starttls_ok=True):
        self.host, self.port = host, port
        self.starttls_ok = starttls_ok
        self.tls = False
        self.logged_in = False
        _FakePlainImap.instances.append(self)

    def starttls(self, ssl_context=None):
        if not self.starttls_ok:
            raise _FakePlainImap.error("STARTTLS not supported by server")
        self.tls = True

    def socket(self):
        class _S:
            def settimeout(self, t):
                pass
        return _S()

    def login(self, user, password):
        assert self.tls, "login before TLS"
        self.logged_in = True

    def logout(self):
        pass


def _plain_text_answer(*a, **kw):
    raise ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1010)")


@pytest.fixture
def fake_plain(monkeypatch):
    _FakePlainImap.instances.clear()
    monkeypatch.setattr(imap_client.imaplib, "IMAP4", _FakePlainImap)
    return _FakePlainImap


def test_plain_text_answer_upgrades_with_starttls(monkeypatch, fake_plain):
    # Proton Bridge on 1143 speaks STARTTLS, not implicit TLS.
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", _plain_text_answer)
    conn = imap_client._connect("localhost", 1143, "a@example.com", "x")
    assert conn.tls and conn.logged_in


def test_port_143_uses_starttls_directly(monkeypatch, fake_plain):
    def no_implicit(*a, **kw):
        raise AssertionError("implicit TLS tried on 143")
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", no_implicit)
    conn = imap_client._connect("imap.example.com", 143, "a@example.com", "x")
    assert conn.tls and conn.logged_in


def test_no_starttls_means_no_login(monkeypatch):
    _FakePlainImap.instances.clear()
    class _NoStartTls(_FakePlainImap):
        def __init__(self, host, port):
            super().__init__(host, port, starttls_ok=False)
    monkeypatch.setattr(imap_client.imaplib, "IMAP4", _NoStartTls)
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", _plain_text_answer)
    with pytest.raises(imap_client.StartTlsUnavailable):
        imap_client._connect("mail.example.com", 1143, "a@example.com", "x")
    assert len(_FakePlainImap.instances) == 1      # not retried
    assert not _FakePlainImap.instances[0].logged_in


def test_port_993_never_falls_back_to_plain(monkeypatch, fake_plain):
    monkeypatch.setattr(imap_client.imaplib, "IMAP4_SSL", _plain_text_answer)
    with pytest.raises(ConnectionError):
        imap_client._connect("imap.example.com", 993, "a@example.com", "x")
    assert not fake_plain.instances
