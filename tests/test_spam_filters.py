"""Spam filters: block mails by subject, sender or text, not by sender."""
import pytest
from fastapi.testclient import TestClient

from gigamail.core import spam_filters


@pytest.fixture(autouse=True)
def own_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path / "ade"))


def _msg(mid, subject, sender="a@example.com", preview=""):
    return {"id": mid, "subject": subject, "bodyPreview": preview,
            "from": {"emailAddress": {"name": "Any One", "address": sender}}}


def test_subject_filter_matches_any_sender_case_insensitively():
    f = spam_filters.add("subject", "Messaggio inviato dal sito", "spam", account_id=2)
    assert f["account_id"] == 2 and f["action"] == "spam"
    filters = spam_filters.list_all(2)
    assert spam_filters.matching(_msg("1", "MESSAGGIO INVIATO DAL SITO di 20128", "x@one.com"), filters)
    assert spam_filters.matching(_msg("2", "Re: messaggio inviato dal sito", "y@two.com"), filters)
    assert spam_filters.matching(_msg("3", "Offer", "x@one.com"), filters) is None
    # a filter for account 2 does not apply to account 3; one for all does
    assert spam_filters.list_all(3) == []
    spam_filters.add("from", "newsletter", "trash")
    assert len(spam_filters.list_all(3)) == 1


def test_from_and_body_fields():
    spam_filters.add("from", "promo@", "spam")
    spam_filters.add("body", "unsubscribe here", "spam")
    fs = spam_filters.list_all()
    assert spam_filters.matching(_msg("1", "Hi", "promo@shop.example"), fs)["field"] == "from"
    assert spam_filters.matching(_msg("2", "Hi", "p@x.com", "Click to Unsubscribe HERE"), fs)["field"] == "body"
    assert spam_filters.matching(_msg("3", "Hi", "p@x.com", "hello"), fs) is None


def test_validation_and_dedup():
    with pytest.raises(ValueError):
        spam_filters.add("subject", "ab", "spam")
    with pytest.raises(ValueError):
        spam_filters.add("header", "abcd", "spam")
    with pytest.raises(ValueError):
        spam_filters.add("subject", "abcd", "nuke")
    a = spam_filters.add("subject", "  Same   text ", "spam", 1)
    b = spam_filters.add("subject", "same text", "spam", 1)
    assert a["id"] == b["id"]
    assert spam_filters.remove(a["id"]) is True
    assert spam_filters.remove(a["id"]) is False
    assert spam_filters.list_all() == []


def test_run_moves_matches_and_counts_hits(monkeypatch):
    from gigamail.core import mail_router
    inbox = [_msg("m1", "Messaggio inviato dal sito"), _msg("m2", "Invoice"),
             _msg("m3", "messaggio inviato dal sito again")]
    monkeypatch.setattr(mail_router, "get_messages", lambda aid, folder="inbox", top=50: inbox)
    f = spam_filters.add("subject", "messaggio inviato dal sito", "trash", 7)
    moved = []
    n = spam_filters.run(7, mover=lambda aid, m, action: moved.append((aid, m["id"], action)) or True)
    assert n == 2
    assert moved == [(7, "m1", "trash"), (7, "m3", "trash")]
    assert spam_filters.list_all()[0]["hits"] == 2
    assert spam_filters.list_all()[0]["id"] == f["id"]


def test_default_mover_uses_the_spam_or_bin_folder(monkeypatch):
    from gigamail.core import mail_router
    calls = []
    monkeypatch.setattr(mail_router, "move_to_folder",
                        lambda aid, message_id="", folder_id="", source_folder=None:
                        calls.append((aid, message_id, folder_id, source_folder)) or True)
    assert spam_filters._move(4, {"id": "z"}, "spam") is True
    assert spam_filters._move(4, {"id": "z"}, "trash") is True
    assert calls == [(4, "z", "junkemail", "inbox"), (4, "z", "deleteditems", "inbox")]


def test_routes_need_the_console_click(monkeypatch, tmp_path):
    from gigamail import http_api, policy
    from gigamail.core import mail_router
    from gigamail.http_api import console_click
    policy.set_store(policy.ApprovalStore(str(tmp_path / "approvals.db")))
    monkeypatch.setattr(mail_router, "get_messages", lambda aid, folder="inbox", top=50: [_msg("m1", "Buy now")])
    moved = []
    monkeypatch.setattr(spam_filters, "_move", lambda aid, m, action: moved.append(m["id"]) or True)
    secret = "s" * 40
    console_click.set_secret(secret)
    try:
        with TestClient(http_api.app) as c:
            body = {"field": "subject", "contains": "buy now", "account_id": 5}
            assert c.post("/spam_filters", json=body).status_code == 403
            r = c.post("/spam_filters", json=body, headers={console_click.HEADER: secret})
            assert r.status_code == 200
            assert r.json()["moved"] == 1 and moved == ["m1"]
            fid = r.json()["filter"]["id"]
            assert c.get("/spam_filters?account_id=5").json()[0]["id"] == fid
            assert c.delete(f"/spam_filters/{fid}").status_code == 403
            assert c.delete(f"/spam_filters/{fid}", headers={console_click.HEADER: secret}).status_code == 200
            assert c.get("/spam_filters").json() == []
    finally:
        console_click.set_secret("")
        policy.set_store(None)


def test_text_filter_reads_the_whole_mail_once(monkeypatch):
    """An IMAP listing carries no body (Graph's bodyPreview is a few
    lines): a filter on the text matched nothing, ever, while the user
    read the words on screen. The run fetches the mail in full, once."""
    from gigamail.core import mail_router
    inbox = [_msg("m1", "Messaggio inviato dal sito"), _msg("m2", "Invoice")]
    monkeypatch.setattr(mail_router, "get_messages", lambda aid, folder="inbox", top=50: inbox)
    spam_filters.add("body", "Media: Google,Immobiliare.it", "spam", 7)
    fetched = []

    def fetch(aid, m):
        fetched.append(m["id"])
        return {"id": m["id"], "body": {"content": "<p>Media: Google,Immobiliare.it,Idealista</p>"}} \
            if m["id"] == "m1" else {"id": m["id"], "body_text": "please pay"}
    moved = []
    n = spam_filters.run(7, mover=lambda aid, m, a: moved.append(m["id"]) or True, fetcher=fetch)
    assert n == 1 and moved == ["m1"]
    assert sorted(fetched) == ["m1", "m2"]
    # the next run does not read them again
    spam_filters.run(7, mover=lambda aid, m, a: True, fetcher=fetch)
    assert sorted(fetched) == ["m1", "m2"]
    assert spam_filters.list_all()[0]["hits"] == 1


def test_a_rule_hides_a_filtered_mail_instead_of_answering(monkeypatch):
    spam_filters.add("body", "unsubscribe", "trash", 3)
    moved = []
    full = {"id": "x", "subject": "Hi", "body_text": "click to UNSUBSCRIBE"}
    f = spam_filters.hide_if_filtered(3, full, mover=lambda aid, m, a: moved.append((m["id"], a)) or True)
    assert f["field"] == "body" and moved == [("x", "trash")]
    assert spam_filters.hide_if_filtered(3, {"id": "y", "subject": "Hi", "body_text": "hello"}) is None
    assert spam_filters.list_all()[0]["hits"] == 1
