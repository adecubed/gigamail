"""A failed console request says why and is written to the log; an
installation with no calendar is not a failure."""
import imaplib

import pytest
from fastapi.testclient import TestClient

from gigamail import http_api
from gigamail.core import auth, calendar_router
from gigamail.http_api import errors
from gigamail.http_api import mail as mail_api


@pytest.fixture()
def logfile(monkeypatch, tmp_path):
    path = tmp_path / "logs" / "console.log"
    monkeypatch.setattr(errors, "log_path", lambda: path)
    monkeypatch.setattr(errors, "_logger", None)
    yield path
    for handler in list(errors.log().handlers):
        handler.close()
        errors.log().removeHandler(handler)
    errors._logger = None


@pytest.fixture()
def client(logfile):
    with TestClient(http_api.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def imap_only(monkeypatch):
    """IMAP mailboxes only, no Google calendar: the provider is Microsoft,
    the default, and there is no Microsoft account."""
    accounts = calendar_router.core_accounts
    monkeypatch.setattr(accounts, "get_active_account",
                        lambda: {"id": 2, "type": "imap", "email": "mario.rossi@example.com"})
    monkeypatch.setattr(accounts, "get_calendar_provider", lambda: "microsoft")
    monkeypatch.setattr(accounts, "get_calendar_primary", lambda: None)


def test_no_calendar_is_its_own_error_and_still_an_auth_one(imap_only):
    assert not calendar_router.connected()
    with pytest.raises(calendar_router.NoCalendar, match="No calendar is connected"):
        calendar_router.get_events()
    assert issubclass(calendar_router.NoCalendar, auth.AuthRequired)


def test_a_microsoft_account_counts_as_a_calendar(monkeypatch, imap_only):
    monkeypatch.setattr(calendar_router.core_accounts, "get_calendar_primary", lambda: 1)
    assert calendar_router.connected()


def test_agenda_of_an_imap_only_installation_is_empty_not_a_500(client, imap_only, logfile):
    """With IMAP mailboxes only, every calendar request answered 500."""
    for url in ("/calendar?days=30", "/calendar/today"):
        r = client.get(url)
        assert (r.status_code, r.json()) == (200, []), url
    assert client.get("/calendar/provider").json() == {"provider": "microsoft", "connected": False}
    assert not logfile.exists() or "calendar" not in logfile.read_text(encoding="utf-8")


def test_what_needs_a_calendar_says_that_none_is_connected(client, imap_only):
    r = client.get("/calendar/free_slots")
    assert r.status_code == 409
    assert "Microsoft 365" in r.json()["detail"] and "Google" in r.json()["detail"]
    r = client.post("/calendar", json={"subject": "Meeting", "start": "2026-11-12T10:00",
                                       "end": "2026-11-12T11:00"})
    assert r.status_code == 409


def test_a_mail_server_error_reaches_the_console_with_its_reason(client, monkeypatch, logfile):
    def refuse(*a, **kw):
        raise imaplib.IMAP4.error("command: UID => got more than 1000000 bytes")

    monkeypatch.setattr(mail_api.mail_router, "get_messages", refuse)
    r = client.get("/mail?top=1&account_id=2")
    assert r.status_code == 502
    assert "got more than 1000000 bytes" in r.json()["detail"]
    text = logfile.read_text(encoding="utf-8")
    assert "GET /mail -> imaplib.IMAP4.error: command: UID => got more than" in text
    assert "in refuse" in text                      # the stack
    assert "account_id" not in text                 # no query string


def test_a_mail_server_that_does_not_answer_is_a_504(client, monkeypatch, logfile):
    def hang(*a, **kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr(mail_api.mail_router, "get_messages", hang)
    assert client.get("/mail").status_code == 504
    assert "TimeoutError" in logfile.read_text(encoding="utf-8")


def test_an_unexpected_error_points_at_the_log_and_keeps_values_out_of_it(client, monkeypatch, logfile):
    def broken(*a, **kw):
        raise ValueError("unexpected " + "x" * 1000)

    monkeypatch.setattr(mail_api.mail_router, "search_messages", broken)
    r = client.get("/mail/search/private%20words")
    assert r.status_code == 500
    assert "ValueError" in r.json()["detail"] and str(logfile) in r.json()["detail"]
    text = logfile.read_text(encoding="utf-8")
    assert "GET /mail/search/{query} -> builtins.ValueError" in text
    assert "private" not in text
    assert "x" * (errors.MAX_REASON_CHARS + 1) not in text


def test_a_log_that_cannot_be_written_does_not_break_the_answer(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr(errors, "log_path", lambda: blocker / "logs" / "console.log")
    monkeypatch.setattr(errors, "_logger", None)

    def broken(*a, **kw):
        raise ValueError("unexpected")

    monkeypatch.setattr(mail_api.mail_router, "get_messages", broken)
    with TestClient(http_api.app, raise_server_exceptions=False) as c:
        assert c.get("/mail").status_code == 500
    errors._logger = None
