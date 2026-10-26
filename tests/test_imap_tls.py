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
