"""IMAP search: server hits only, read-only, bounded.

The old search downloaded up to 3000 whole messages per folder whenever
the server found fewer than `top` hits, with RFC822 on a read-write
SELECT: minutes on a mailbox with many folders, and every message it
touched was marked as read.
"""
from email.message import EmailMessage

import pytest

from gigamail.core import imap_client


def _raw(uid: int, subject: str, sender: str = "mario.rossi@example.com",
         body: str = "Hello") -> bytes:
    m = EmailMessage()
    m["From"] = f"Mario Rossi <{sender}>"
    m["To"] = "owner@example.com"
    m["Subject"] = subject
    m["Date"] = f"Mon, {uid:02d} Sep 2026 10:00:00 +0000"
    m.set_content(body)
    return m.as_bytes()


class FakeConn:
    """Enough of imaplib for search_messages: folders, SEARCH by subject,
    and a record of every SELECT and FETCH."""

    def __init__(self, folders):
        self.folders = folders          # {name: {uid: raw}}
        self.selected = None
        self.selects = []               # (folder, readonly)
        self.fetches = []               # fetch item strings
        self.literal = None

    def select(self, mailbox, readonly=False):
        name = mailbox.strip('"')
        self.selects.append((name, readonly))
        self.selected = name
        return "OK", [str(len(self.folders.get(name, {}))).encode()]

    def fetch(self, *args):             # sequence-number fetch: must not be used
        self.fetches.append(("seq",) + args)
        return "OK", []

    def uid(self, command, *args):
        box = self.folders.get(self.selected, {})
        if command == "search":
            field, value = args[-2], args[-1].strip('"').lower()
            hits = []
            for uid, raw in box.items():
                text = raw.decode(errors="replace").lower()
                if field == "SUBJECT" and f"subject: {value}" in text:
                    hits.append(str(uid).encode())
                elif field == "SUBJECT" and value in text.split("subject:")[1].split("\n")[0]:
                    hits.append(str(uid).encode())
            return "OK", [b" ".join(hits)]
        if command == "fetch":
            uid, item = args
            self.fetches.append(item)
            return "OK", [(f"1 (UID {uid} BODY[] {{1}}".encode(), box[int(uid)])]
        raise AssertionError(command)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(folders):
        conn = FakeConn(folders)
        holder["conn"] = conn
        monkeypatch.setattr(imap_client, "_acquire_connection",
                            lambda *a, **k: (("k",), conn))
        monkeypatch.setattr(imap_client, "_release_connection", lambda *a, **k: None)
        monkeypatch.setattr(imap_client, "_list_folders", lambda c: list(folders))
        return conn
    return install


def _search(query, top=10):
    return imap_client.search_messages("imap.example.com", 993, "owner@example.com",
                                       "pw", query, top=top)


def test_search_opens_folders_read_only_and_peeks(fake):
    conn = fake({"INBOX": {1: _raw(1, "Grant eligibility"), 2: _raw(2, "Lunch")},
                 "Archive": {5: _raw(5, "Other")}})
    found = _search("eligibility")
    assert [m["subject"] for m in found] == ["Grant eligibility"]
    assert all(readonly for _, readonly in conn.selects)
    # Only the server's hit is fetched, without setting \Seen.
    assert conn.fetches == ["(BODY.PEEK[])"]


def test_search_does_not_download_the_folder_when_hits_are_few(fake):
    box = {uid: _raw(uid, f"Newsletter {uid}") for uid in range(1, 400)}
    conn = fake({"INBOX": box})
    assert _search("nothing like this") == []
    assert conn.fetches == []


def test_search_stops_at_top_and_starts_from_inbox(fake):
    conn = fake({"Projects": {uid: _raw(uid, "Report") for uid in range(1, 6)},
                 "INBOX": {uid: _raw(uid, "Report") for uid in range(10, 13)}})
    found = _search("report", top=3)
    assert len(found) == 3
    assert {m["folder"] for m in found} == {"INBOX"}
    assert [name for name, _ in conn.selects] == ["INBOX"]


def test_search_respects_the_time_budget(fake, monkeypatch):
    conn = fake({"INBOX": {1: _raw(1, "Report")}, "Archive": {2: _raw(2, "Report")}})
    monkeypatch.setattr(imap_client, "_SEARCH_BUDGET_S", -1)
    assert _search("report") == []
    assert conn.selects == []


def test_folder_order_puts_inbox_then_sent_and_skips_drafts():
    order = imap_client._search_folder_order(
        ["Projects", "INBOX.Sent", "Drafts", "INBOX", "Outbox"])
    assert order == ["INBOX", "INBOX.Sent", "Projects"]
