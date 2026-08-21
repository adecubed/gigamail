"""Barriere anti-spam (0.2): deterministiche, locali, fail-closed.
reply=False → non si risponde; auto_ok=False → al massimo semi."""
from ade_mail_agent.core import mail_guard


CLEAN_MSG = {
    "from": {"emailAddress": {"address": "cliente@fidato.it"}},
    "subject": "Info",
    "body": {"content": "Buongiorno, avrei una domanda."},
    "attachments": [],
}

DMARC_PASS = {"authentication-results": [
    "mx.example.com; spf=pass; dkim=pass; dmarc=pass header.from=fidato.it"]}


def test_mail_pulita_autenticata_va_anche_in_auto():
    v = mail_guard.check(DMARC_PASS, CLEAN_MSG)
    assert v.reply and v.auto_ok


def test_dmarc_assente_o_fail_mai_auto():
    for headers in ({}, {"authentication-results":
                         ["mx; dmarc=fail header.from=fidato.it"]}):
        v = mail_guard.check(headers, CLEAN_MSG)
        assert v.reply and not v.auto_ok
        assert "dmarc-not-pass" in v.reasons


def test_header_non_recuperabili_fail_closed():
    v = mail_guard.check(None, CLEAN_MSG)
    assert v.reply and not v.auto_ok
    assert "headers-unavailable" in v.reasons


def test_rfc3834_mai_rispondere():
    cases = [
        {"auto-submitted": ["auto-replied"]},
        {"auto-submitted": ["auto-generated"]},
        {"precedence": ["bulk"]},
        {"precedence": ["list"]},
        {"list-id": ["<news.example.com>"]},
        {"list-unsubscribe": ["<mailto:unsub@x.it>"]},
        {"x-auto-response-suppress": ["All"]},
        {"return-path": ["<>"]},
    ]
    for h in cases:
        v = mail_guard.check({**DMARC_PASS, **h}, CLEAN_MSG)
        assert not v.reply, f"doveva bloccare: {h}"


def test_auto_submitted_no_e_lecito():
    v = mail_guard.check({**DMARC_PASS, "auto-submitted": ["no"]}, CLEAN_MSG)
    assert v.reply and v.auto_ok


def test_mittenti_noreply_bloccati():
    for local in ("no-reply", "noreply", "donotreply", "mailer-daemon",
                  "bounce"):
        msg = dict(CLEAN_MSG,
                   **{"from": {"emailAddress": {"address": f"{local}@shop.it"}}})
        v = mail_guard.check(DMARC_PASS, msg)
        assert not v.reply, f"doveva bloccare {local}@"


def test_verdetto_spam_del_provider_rispettato():
    v = mail_guard.check({**DMARC_PASS, "x-spam-flag": ["YES"]}, CLEAN_MSG)
    assert not v.reply


def test_allegati_pericolosi_bloccano():
    for name in ("fattura.exe", "docs.zip", "script.js", "install.msi"):
        msg = dict(CLEAN_MSG, attachments=[{"name": name}])
        v = mail_guard.check(DMARC_PASS, msg)
        assert not v.reply, f"doveva bloccare {name}"
    # un pdf normale no
    v = mail_guard.check(DMARC_PASS, dict(CLEAN_MSG,
                                          attachments=[{"name": "doc.pdf"}]))
    assert v.reply


def test_corpo_abnorme_blocca():
    msg = dict(CLEAN_MSG, body={"content": "x" * (mail_guard.MAX_BODY_CHARS + 1)})
    assert not mail_guard.check(DMARC_PASS, msg).reply


def test_sender_address_normalizza():
    assert mail_guard.sender_address(
        {"from": {"emailAddress": {"address": "A@B.IT"}}}) == "a@b.it"
    assert mail_guard.sender_address(
        {"from": "Nome Cognome <x@y.it>"}) == "x@y.it"
