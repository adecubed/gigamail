"""Onboarding end to end su un server IMAP/SMTP vero.

Account -> ricerca -> bozza che NON parte da sola -> approvazione umana ->
invio -> la risposta arriva davvero. Gira contro un server di prova
(GreenMail in CI: vedi .github/workflows/ci.yml), mai contro una casella
reale. Senza GIGAMAIL_E2E_IMAP_HOST il test si salta.

L'approvazione qui e' quella che la CLI registra DOPO Windows Hello /
Touch ID: il prompt biometrico non si puo' premere da un test, il resto
del percorso e' identico.
"""
import imaplib
import os
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage

import pytest

HOST = os.environ.get("GIGAMAIL_E2E_IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("GIGAMAIL_E2E_IMAP_PORT", "993"))
SMTP_PORT = int(os.environ.get("GIGAMAIL_E2E_SMTP_PORT", "465"))

pytestmark = pytest.mark.skipif(
    not HOST, reason="GIGAMAIL_E2E_IMAP_HOST non impostata: niente server di prova")

TITOLARE = "titolare@e2e.test"
CLIENTE = "cliente@e2e.test"


def _ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # certificato self-signed del server di prova
    return ctx


def _manda(da, a, oggetto, testo):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = da, a, oggetto
    msg.set_content(testo)
    with smtplib.SMTP_SSL(HOST, SMTP_PORT, context=_ctx()) as s:
        s.login(da, "x")
        s.send_message(msg)


def _oggetti(casella):
    c = imaplib.IMAP4_SSL(HOST, IMAP_PORT, ssl_context=_ctx())
    try:
        c.login(casella, "x")
        c.select("INBOX")
        _, ids = c.search(None, "ALL")
        out = []
        for i in ids[0].split():
            _, dati = c.fetch(i, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
            out.append(dati[0][1].decode(errors="replace").strip())
        return out
    finally:
        c.logout()


def _aspetta(condizione, secondi=20):
    fine = time.time() + secondi
    while time.time() < fine:
        esito = condizione()
        if esito:
            return esito
        time.sleep(0.5)
    return condizione()


@pytest.fixture()
def account(tmp_path, monkeypatch):
    from gigamail import policy
    from gigamail.core import accounts

    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    aid = accounts.add_imap_account("E2E", TITOLARE, "x", HOST, IMAP_PORT,
                                    HOST, SMTP_PORT, insecure_tls=True)
    yield aid
    accounts.delete_account(aid)
    policy.set_store(None)


def test_dalla_ricerca_all_invio_approvato(account):
    from gigamail import policy
    from gigamail import server as srv

    segno = uuid.uuid4().hex[:10]
    oggetto = f"Richiesta preventivo {segno}"
    _manda(CLIENTE, TITOLARE, oggetto, "Buongiorno, mi mandate il listino?")
    assert _aspetta(lambda: any(segno in o for o in _oggetti(TITOLARE)))

    # 1. l'account c'e'
    assert any(a.get("id") == account for a in srv.list_accounts())

    # 2. la ricerca trova la mail
    def _trovata():
        r = srv.search_mail(query=segno, account_id=account)
        return next((m for m in r.get("provider") or []
                     if segno in str(m.get("subject"))), None)
    mail = _aspetta(_trovata)
    assert mail, "search_mail non trova la mail appena arrivata"

    # 3. la bozza non parte da sola
    corpo = f"Buongiorno, in risposta a {segno}: ecco il listino."
    prima = srv.reply_mail(message_id=mail["id"], body=corpo, account_id=account)
    assert prima["status"] == "approval_required", prima
    rid = prima["request_id"]
    assert not any(segno in o for o in _oggetti(CLIENTE)), \
        "la risposta e' partita prima dell'approvazione"

    # 4. senza approvazione, ripresentare la richiesta non basta
    attesa = srv.reply_mail(message_id=mail["id"], body=corpo,
                            account_id=account, request_id=rid)
    assert attesa["status"] == "awaiting_approval", attesa
    assert not any(segno in o for o in _oggetti(CLIENTE))

    # 5. l'umano approva, la risposta parte e arriva
    assert policy.store().approve(rid, by="e2e:umano")
    dopo = srv.reply_mail(message_id=mail["id"], body=corpo,
                          account_id=account, request_id=rid)
    assert dopo.get("success") is True, dopo
    assert _aspetta(lambda: any(segno in o for o in _oggetti(CLIENTE))), \
        "la risposta approvata non e' arrivata al cliente"

    # 6. la stessa approvazione non vale due volte
    with pytest.raises(ValueError):
        srv.reply_mail(message_id=mail["id"], body=corpo,
                       account_id=account, request_id=rid)
    assert sum(segno in o for o in _oggetti(CLIENTE)) == 1
