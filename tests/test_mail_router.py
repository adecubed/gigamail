"""Dispatch del router: account Microsoft vs IMAP, alias cartelle."""
import pytest

from ade_mail_agent.core import mail_router


MS_ACCOUNT = {"id": 10, "type": "microsoft", "email": "ms@example.com"}
IMAP_ACCOUNT = {
    "id": 20, "type": "imap", "email": "imap@example.com",
    "data": {
        "password": "pw", "imap_host": "imap.example.com", "imap_port": 993,
        "smtp_host": "smtp.example.com", "smtp_port": 465,
    },
}


@pytest.fixture()
def fake_accounts(monkeypatch):
    def _by_id(aid):
        return {10: MS_ACCOUNT, 20: IMAP_ACCOUNT}.get(aid)
    monkeypatch.setattr(mail_router.acc, "get_account_by_id", _by_id)
    monkeypatch.setattr(mail_router.acc, "get_active_account", lambda: MS_ACCOUNT)


@pytest.fixture()
def spy_ms(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        mail_router.ms_mail, "get_messages",
        lambda folder="inbox", top=20, skip=0: calls.update(folder=folder, top=top) or [],
    )
    return calls


@pytest.fixture()
def spy_imap(monkeypatch):
    calls = {}

    def fake_get(host, port, email_addr, password, folder="INBOX", top=20):
        calls.update(host=host, folder=folder, email=email_addr)
        return []

    monkeypatch.setattr(mail_router.imap, "get_messages", fake_get)
    return calls


@pytest.mark.parametrize("alias,target", [
    ("inbox", "inbox"),
    ("trash", "deleteditems"),
    ("deleted", "deleteditems"),
    ("cestino", "deleteditems"),
    ("spam", "junkemail"),
    ("junk", "junkemail"),
    ("sent", "sentitems"),
    ("drafts", "drafts"),
])
def test_alias_cartelle_microsoft(fake_accounts, spy_ms, alias, target):
    mail_router.get_messages(account_id=10, folder=alias)
    assert spy_ms["folder"] == target


@pytest.mark.parametrize("alias,target", [
    ("inbox", "INBOX"),
    ("trash", "trash"),
    ("deleted", "trash"),      # la console usa 'deleted': deve mappare a trash
    ("cestino", "trash"),
    ("spam", "junk"),
    ("junk", "junk"),
    ("sent", "sent"),
])
def test_alias_cartelle_imap(fake_accounts, spy_imap, alias, target):
    mail_router.get_messages(account_id=20, folder=alias)
    assert spy_imap["folder"] == target
    assert spy_imap["host"] == "imap.example.com"


def test_account_inesistente_lista_vuota(fake_accounts, spy_ms, spy_imap):
    """Id esplicito inesistente: MAI ripiegare sull'account attivo
    (isolamento account) — lista vuota e nessuna chiamata provider."""
    assert mail_router.get_messages(account_id=999) == []
    assert not spy_ms and not spy_imap


def test_send_dispatch_imap(fake_accounts, monkeypatch):
    sent = {}

    def fake_send(smtp_host, smtp_port, email_addr, password, to, subject, body, **kw):
        sent.update(to=to, subject=subject, smtp_host=smtp_host)
        return True

    monkeypatch.setattr(mail_router.imap, "send_message", fake_send)
    result = mail_router.send_message(
        account_id=20, to="dest@example.it", subject="Prova", body="ciao"
    )
    assert sent["to"] == "dest@example.it"
    assert isinstance(result, dict) and "success" in result


def test_send_result_normalizzato_bool(fake_accounts, monkeypatch):
    monkeypatch.setattr(mail_router.imap, "send_message",
                        lambda *a, **kw: True)
    r = mail_router.send_message(account_id=20, to="x@y.it", subject="s", body="b")
    assert r["success"] is True
