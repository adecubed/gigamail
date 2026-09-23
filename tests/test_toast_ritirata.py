"""Una richiesta decisa toglie la sua toast, da qualunque canale arrivi il si'."""
import sys
import types

import pytest

from ade_mail_agent import policy
from ade_mail_agent.core import desktop_notify


@pytest.fixture()
def ritirate(monkeypatch):
    fatte = []
    monkeypatch.setattr(desktop_notify, "dismiss", lambda rid: fatte.append(rid) or True)
    return fatte


def _nuova():
    return policy.store().create(
        "send_mail", {"to": "a@example.com", "subject": "x", "body": "y"},
        {"to": "a@example.com"})


def test_approvare_ritira_la_toast(ritirate):
    """Il 15/09 una risposta approvata su Telegram lasciava sul PC la
    notifica con il bottone Approva."""
    rid = _nuova()
    assert policy.store().approve(rid, by="telegram:1")
    assert ritirate == [rid]


def test_rifiutare_ritira_la_toast(ritirate):
    rid = _nuova()
    assert policy.store().reject(rid, by="telegram:1")
    assert ritirate == [rid]


def test_revocare_ed_eseguire_ritirano_la_toast(ritirate):
    rid = _nuova()
    policy.store().approve(rid, by="cli:test")
    assert policy.store().revoke(rid, by="cli:test")
    altra = _nuova()
    policy.store().approve(altra, by="cli:test")
    assert policy.store().consume_approved(altra, "send_mail") is not None
    assert ritirate == [rid, rid, altra, altra]


def test_una_decisione_fallita_non_tocca_le_toast(ritirate):
    rid = _nuova()
    policy.store().reject(rid, by="cli:test")
    assert policy.store().approve(rid, by="cli:test") is False
    assert ritirate == [rid]


def test_dismiss_usa_tag_gruppo_e_app(monkeypatch):
    chiamate = []

    class Storia:
        def remove_grouped_tag_with_id(self, tag, group, app):
            chiamate.append((tag, group, app))

    finto = types.ModuleType("winrt.windows.ui.notifications")
    finto.ToastNotificationManager = types.SimpleNamespace(history=Storia())
    for nome in ("winrt", "winrt.windows", "winrt.windows.ui"):
        if nome not in sys.modules:
            monkeypatch.setitem(sys.modules, nome, types.ModuleType(nome))
    monkeypatch.setitem(sys.modules, "winrt.windows.ui.notifications", finto)
    monkeypatch.setattr(desktop_notify.sys, "platform", "win32")
    assert desktop_notify.dismiss("req_abc123") is True
    assert chiamate == [("req_abc123", "approvals", desktop_notify._APP_ID)]


def test_dismiss_rifiuta_id_non_validi(monkeypatch):
    monkeypatch.setattr(desktop_notify.sys, "platform", "win32")
    assert desktop_notify.dismiss("req_x'); Remove-Item C:") is False
    assert desktop_notify.dismiss("") is False
