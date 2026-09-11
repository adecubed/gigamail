"""Il cc di reply_mail deve arrivare fino all'invio.

Regressione vera, 11/09/2026: il cc veniva accettato dal tool, finiva
negli args, compariva nell'anteprima approvata dall'umano... e poi
execute_fn non lo passava a reply_message. Chi approvava vedeva la copia
promessa e il destinatario in copia non riceveva nulla: un silenzio che
non lascia traccia da nessuna parte.
"""
import pytest

from ade_mail_agent import policy
from ade_mail_agent import server as srv
from ade_mail_agent.core import mail_router


@pytest.fixture(autouse=True)
def store_isolato(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


def test_cc_arriva_a_reply_message(monkeypatch):
    inviato = {}
    monkeypatch.setattr(mail_router, "reply_message",
                        lambda **kw: inviato.update(kw) or {"success": True})
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: {"from": {"emailAddress":
                                               {"address": "cliente@x.it"}},
                                      "subject": "Appuntamento"})
    r = srv.reply_mail(message_id="1", body="ok", cc=["ufficio@x.it"])
    assert r["preview"]["cc"] == ["ufficio@x.it"]
    policy.store().approve(r["request_id"])
    srv.reply_mail(message_id="1", body="ok", cc=["ufficio@x.it"],
                   request_id=r["request_id"])
    assert inviato["cc"] == ["ufficio@x.it"]


def test_senza_cc_resta_none(monkeypatch):
    inviato = {}
    monkeypatch.setattr(mail_router, "reply_message",
                        lambda **kw: inviato.update(kw) or {"success": True})
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: {"from": {"emailAddress":
                                               {"address": "cliente@x.it"}},
                                      "subject": "Appuntamento"})
    r = srv.reply_mail(message_id="1", body="ok")
    policy.store().approve(r["request_id"])
    srv.reply_mail(message_id="1", body="ok", request_id=r["request_id"])
    assert inviato["cc"] is None
