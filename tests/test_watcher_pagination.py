"""Scansione paginata: arretrato, perimetro temporale e pagine sovrapposte."""
from datetime import datetime, timedelta, timezone

from ade_mail_agent.core import mail_router
from ade_mail_agent.watcher import ingestion


def _message(mid, when):
    return {"id": mid, "receivedDateTime": when.isoformat()}


def test_paginazione_filtra_date_senza_perdere_pagine_non_ordinate(monkeypatch):
    now = datetime.now(timezone.utc)
    rule = {"rule_id": "rule_1", "account_id": 1, "trigger_kind": "senders",
            "created_at": (now - timedelta(days=1)).timestamp()}
    pages = [
        [_message("1", now), _message("2", now)],
        [_message("3", now), _message("4", now)],
        [_message("old-1", now - timedelta(days=2)),
         _message("old-2", now - timedelta(days=2))],
        [_message("recent-after-old", now)],
    ]
    calls = []

    def get_messages(**kw):
        calls.append(kw)
        return pages[kw["skip"] // 2]

    monkeypatch.setattr(mail_router, "get_messages", get_messages)
    found = ingestion.poll_folder(rule, top=2, unread_days=7, verbose=False)
    assert [m["id"] for m in found] == ["1", "2", "3", "4", "recent-after-old"]
    assert [c["skip"] for c in calls] == [0, 2, 4, 6]


def test_pagine_sovrapposte_non_duplicano_e_non_ciclano(monkeypatch):
    now = datetime.now(timezone.utc)
    rule = {"rule_id": "rule_1", "account_id": 1, "trigger_kind": "senders",
            "created_at": 0}
    pages = [[_message("1", now), _message("2", now)],
             [_message("2", now), _message("3", now)],
             [_message("2", now), _message("3", now)]]
    calls = []

    def get_messages(**kw):
        calls.append(kw["skip"])
        return pages[len(calls) - 1]

    monkeypatch.setattr(mail_router, "get_messages", get_messages)
    found = ingestion.poll_folder(rule, top=2, unread_days=7, verbose=False)
    assert [m["id"] for m in found] == ["1", "2", "3"]
    assert calls == [0, 2, 4]
