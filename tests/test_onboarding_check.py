"""`gigamail check`: il percorso di onboarding su un account vero, qui con
server e casella finti. Il test end to end su IMAP vero e' test_e2e_imap."""
import threading
import time

import pytest

from gigamail import onboarding_check, policy
from gigamail import server as srv
from gigamail.core import accounts as core_accounts


@pytest.fixture()
def mondo(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    casella = []
    monkeypatch.setattr(core_accounts, "get_active_account",
                        lambda: {"id": 7, "email": "me@x.test", "type": "imap"})
    monkeypatch.setattr(srv, "list_unread", lambda **kw: {"messages": []})
    monkeypatch.setattr(srv, "search_mail", lambda query, **kw: {
        "provider": [m for m in casella if query in m["subject"] or query == "a"],
        "archive": []})

    def send_mail(to, subject, body, account_id=None, request_id=None, **kw):
        if not request_id:
            rid = policy.store().create("send_mail", {"to": to, "subject": subject},
                                        {"to": to})
            return {"status": "approval_required", "request_id": rid}
        casella.append({"subject": subject})
        return {"success": True}
    monkeypatch.setattr(srv, "send_mail", send_mail)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    yield casella
    policy.set_store(None)


def _approva_appena_c_e(decisione="approve"):
    def gira():
        for _ in range(2000):
            pend = policy.store().list_pending()
            if pend:
                getattr(policy.store(), decisione)(pend[0]["request_id"], by="test")
                return
    t = threading.Thread(target=gira)
    t.start()
    return t


def test_passa_solo_dopo_l_approvazione(mondo, capsys):
    t = _approva_appena_c_e()
    assert onboarding_check.main(["--timeout", "30"]) == 0
    t.join()
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert "onboarding check PASSED (8/8)" in out
    assert len(mondo) == 1          # una sola mail, dopo l'approvazione


def test_rifiutata_non_parte(mondo, capsys):
    t = _approva_appena_c_e("reject")
    assert onboarding_check.main(["--timeout", "30"]) == 1
    t.join()
    assert mondo == []
    assert "[FAIL] 6. human approval" in capsys.readouterr().out
