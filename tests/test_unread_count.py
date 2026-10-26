"""Il badge delle non lette: Graph conta dal suo lato (solo id, filtro),
e un server di posta che non risponde da' 502 pulito, senza traceback."""

import requests
from fastapi.testclient import TestClient

from gigamail.core import mail as ms_mail
from gigamail.core import mail_router


class _R:
    def __init__(self, n):
        self._n = n

    def raise_for_status(self):
        pass

    def json(self):
        return {"value": [{"id": str(i)} for i in range(self._n)]}


def test_graph_conta_con_un_filtro_e_solo_gli_id(monkeypatch):
    visti = {}
    monkeypatch.setattr(ms_mail, "_headers", lambda: {})

    def finto_get(url, headers=None, params=None, timeout=None):
        visti.update(params=params, timeout=timeout, url=url)
        return _R(7)

    monkeypatch.setattr(ms_mail.requests, "get", finto_get)
    assert ms_mail.count_unread("inbox", "2026-10-14T00:00:00Z", 99) == 7
    assert visti["params"]["$select"] == "id"
    assert visti["params"]["$top"] == 99
    assert "isRead eq false" in visti["params"]["$filter"]
    assert "receivedDateTime ge 2026-10-14T00:00:00Z" in visti["params"]["$filter"]
    assert visti["timeout"]


def test_account_microsoft_usa_il_conteggio_di_graph(monkeypatch):
    monkeypatch.setattr(mail_router, "_account", lambda aid: {"id": 1, "type": "microsoft"})
    monkeypatch.setattr(mail_router, "_demo", lambda a: False)
    chiamate = []
    monkeypatch.setattr(ms_mail, "count_unread", lambda f, since, cap: chiamate.append((f, cap)) or 3)
    monkeypatch.setattr(mail_router, "get_messages",
                        lambda **k: (_ for _ in ()).throw(AssertionError("non deve scaricare le mail")))
    assert mail_router.count_unread(1) == 3
    assert chiamate == [("inbox", 99)]


def test_graph_che_non_risponde_da_502_pulito(monkeypatch):
    from gigamail import http_api

    def guasto(*a, **k):
        raise requests.HTTPError("502 Server Error: Bad Gateway")

    monkeypatch.setattr(mail_router, "count_unread", guasto)
    with TestClient(http_api.app) as c:
        r = c.get("/mail/unread_count?account_id=1")
    assert r.status_code == 502
    assert "non raggiungibile" in r.json()["detail"]
