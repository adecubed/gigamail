"""Provider-level regressions: assert the actual wire payload and IMAP effects."""
import email
from types import SimpleNamespace

import pytest

from ade_mail_agent.core import imap_client, mail, mail_router


@pytest.mark.parametrize("port", [465, 587])
def test_smtp_bcc_is_envelope_only(monkeypatch, port):
    sent = {}

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, *args):
            pass

        def starttls(self, **kwargs):
            pass

        def sendmail(self, sender, recipients, payload):
            sent.update(recipients=recipients, payload=payload)
            return {}

    monkeypatch.setattr(imap_client.smtplib, "SMTP_SSL", SMTP)
    monkeypatch.setattr(imap_client.smtplib, "SMTP", SMTP)
    result = imap_client.send_message(
        "smtp.test", port, "me@example.test", "password",
        "public@example.test", "Subject", "Body",
        cc=["copy@example.test"], bcc=["private@example.test"],
    )
    assert result["success"]
    assert set(sent["recipients"]) == {
        "public@example.test", "copy@example.test", "private@example.test"}
    message = email.message_from_string(sent["payload"])
    assert message["Bcc"] is None
    assert "private@example.test" not in sent["payload"]


def test_graph_reply_sends_exact_approved_recipients(monkeypatch):
    sent = {}

    def post(url, *, headers, json):
        sent.update(url=url, payload=json)
        return SimpleNamespace(status_code=202, headers={}, text="")

    monkeypatch.setattr(mail.requests, "post", post)
    monkeypatch.setattr(mail, "_headers", lambda: {})
    result = mail.send_message(
        "approved@example.test", "Re: Subject", "Body", reply_to_id="message",
        cc=["copy@example.test"], bcc=["private@example.test"],
    )
    assert result["success"]
    assert sent["url"].endswith("/messages/message/reply")
    assert sent["payload"] == {
        "comment": "Body",
        "message": {
            "toRecipients": [{"emailAddress": {"address": "approved@example.test"}}],
            "ccRecipients": [{"emailAddress": {"address": "copy@example.test"}}],
            "bccRecipients": [{"emailAddress": {"address": "private@example.test"}}],
        },
    }


class IMAP:
    """A mailbox with another pending deletion that must survive our action."""
    capabilities = (b"IMAP4rev1", b"UIDPLUS")

    def __init__(self):
        self.messages = {"INBOX": {"42", "99"}, "Trash": set(), "Archive": set()}
        self.deleted = {"99"}
        self.folder = "INBOX"
        self.operations = []
        self.copy_status = self.store_status = self.expunge_status = "OK"
        self.move_status = "NO"

    def select(self, folder):
        folder = folder.strip('"')
        if folder not in self.messages:
            return "NO", [b"missing"]
        self.folder = folder
        return "OK", [str(len(self.messages[folder])).encode()]

    def uid(self, command, *args):
        command = command.upper()
        self.operations.append((command, args))
        if command == "FETCH":
            return "OK", [(b"42 (UID 42)", b"Subject: original\r\n")] \
                if args[0] in self.messages[self.folder] else [None]
        if command == "MOVE":
            if self.move_status == "OK":
                self.messages[self.folder].remove(args[0])
                self.messages[args[1].strip('"')].add(args[0])
            return self.move_status, [b""]
        if command == "COPY":
            if self.copy_status == "OK":
                self.messages[args[1].strip('"')].add(args[0])
            return self.copy_status, [b""]
        if command == "STORE":
            if self.store_status == "OK":
                if args[1] == "+FLAGS":
                    self.deleted.add(args[0])
                else:
                    self.deleted.discard(args[0])
            return self.store_status, [b""]
        if command == "SEARCH":
            return "OK", [" ".join(sorted(self.deleted)).encode()]
        if command == "EXPUNGE":
            if self.expunge_status == "OK":
                self.messages[self.folder].discard(args[0])
                self.deleted.discard(args[0])
            return self.expunge_status, [b""]
        raise AssertionError(command)

    def expunge(self):
        self.operations.append(("GLOBAL_EXPUNGE", ()))
        if self.expunge_status == "OK":
            self.messages[self.folder] -= self.deleted
            self.deleted.clear()
        return self.expunge_status, [b""]


@pytest.fixture
def imap(monkeypatch):
    conn = IMAP()
    monkeypatch.setattr(imap_client, "_acquire_connection", lambda *a, **k: ("key", conn))
    monkeypatch.setattr(imap_client, "_release_connection", lambda *a, **k: None)
    monkeypatch.setattr(imap_client, "_list_folders", lambda c: list(c.messages))

    def resolve(c, folder):
        real = "Trash" if folder.lower() == "trash" else folder
        return real if c.select(real)[0] == "OK" else None

    monkeypatch.setattr(imap_client, "_resolve_folder_strict", resolve)
    return conn


def delete(**kwargs):
    return imap_client.delete_message(
        "imap.test", 993, "me@example.test", "password", "42",
        folder=kwargs.get("folder", "INBOX"))


def test_delete_copy_failure_preserves_original(imap):
    imap.copy_status = "NO"
    assert not delete()
    assert "42" in imap.messages["INBOX"]
    assert not any(op in {"STORE", "EXPUNGE", "GLOBAL_EXPUNGE"}
                   for op, _ in imap.operations)


def test_delete_store_failure_never_expunges(imap):
    imap.store_status = "NO"
    assert not delete()
    assert "42" in imap.messages["INBOX"]
    assert not any("EXPUNGE" in op for op, _ in imap.operations)


def test_delete_expunge_failure_reported(imap):
    imap.expunge_status = "NO"
    assert not delete()
    assert "42" in imap.messages["INBOX"]


def test_delete_only_expunges_its_own_uid(imap):
    assert delete()
    assert imap.messages["INBOX"] == {"99"}
    assert imap.messages["Trash"] == {"42"}
    assert ("EXPUNGE", ("42",)) in imap.operations
    assert not any(op == "GLOBAL_EXPUNGE" for op, _ in imap.operations)


def test_delete_prefers_atomic_move(imap):
    imap.move_status = "OK"
    assert delete()
    assert imap.messages["INBOX"] == {"99"}
    assert imap.messages["Trash"] == {"42"}
    assert not any(op in {"COPY", "STORE", "EXPUNGE", "GLOBAL_EXPUNGE"}
                   for op, _ in imap.operations)


def test_legacy_delete_refuses_to_expunge_other_messages(imap):
    imap.capabilities = (b"IMAP4rev1",)
    assert not delete()
    assert imap.messages["INBOX"] == {"42", "99"}
    assert not any(op in {"COPY", "STORE", "GLOBAL_EXPUNGE"}
                   for op, _ in imap.operations)


def test_legacy_delete_works_without_other_pending_deletions(imap):
    imap.capabilities = (b"IMAP4rev1",)
    imap.deleted.clear()
    assert delete()
    assert imap.messages["INBOX"] == {"99"}
    assert imap.messages["Trash"] == {"42"}


@pytest.mark.parametrize("folder", ["Missing", "Archive"])
def test_delete_never_falls_back_from_explicit_source(imap, folder):
    assert not delete(folder=folder)
    assert imap.messages["INBOX"] == {"42", "99"}
    assert not any(op in {"MOVE", "COPY", "STORE"} for op, _ in imap.operations)


def test_delete_expunge_failure_clears_the_deleted_flag(imap):
    """Un flag Deleted lasciato li' lo cancellerebbe per sempre il prossimo
    EXPUNGE di un altro client, mentre l'utente legge "non eliminata"."""
    imap.expunge_status = "NO"
    assert not delete()
    assert "42" not in imap.deleted


def test_delete_without_folder_means_inbox_not_a_search(imap):
    """Gli UID valgono solo nella loro cartella: il 42 di Archive e' un
    altro messaggio da quello mostrato nell'anteprima (INBOX)."""
    imap.messages = {"INBOX": {"99"}, "Trash": set(), "Archive": {"42"}}
    assert not delete(folder="")
    assert imap.messages["Archive"] == {"42"}
    assert not any(op in {"MOVE", "COPY", "STORE"} for op, _ in imap.operations)


def test_uidplus_announced_after_login_is_used(imap):
    """La lista di capability di imaplib e' quella di prima del login."""
    imap.capabilities = (b"IMAP4rev1",)
    imap.capability = lambda: ("OK", [b"IMAP4rev1 UIDPLUS MOVE"])
    assert delete()
    assert imap.messages["INBOX"] == {"99"}
    assert ("EXPUNGE", ("42",)) in imap.operations


@pytest.fixture
def imap_move(monkeypatch, imap):
    def resolve(c, folder):
        real = next((f for f in c.messages if f.lower() == folder.lower()), folder)
        return real if c.select(real)[0] == "OK" else None

    monkeypatch.setattr(imap_client, "_resolve_folder_strict", resolve)
    monkeypatch.setattr(imap_client, "_resolve_folder", resolve)
    return imap


def move(source="INBOX"):
    return imap_client.move_to_folder(
        "imap.test", 993, "me@example.test", "password", "42",
        folder="Archive", source_folder=source)


def test_move_fallback_only_removes_its_own_uid(imap_move):
    """Senza MOVE lo spostamento faceva un EXPUNGE di tutta la cartella:
    il 99, segnato Deleted da un altro client, spariva per sempre."""
    assert move()
    assert imap_move.messages["INBOX"] == {"99"}
    assert imap_move.messages["Archive"] == {"42"}
    assert "99" in imap_move.deleted
    assert not any(op == "GLOBAL_EXPUNGE" for op, _ in imap_move.operations)


def test_legacy_move_refuses_before_copying(imap_move):
    imap_move.capabilities = (b"IMAP4rev1",)
    assert not move()
    assert imap_move.messages == {"INBOX": {"42", "99"}, "Trash": set(),
                                  "Archive": set()}
    assert not any(op in {"COPY", "STORE", "GLOBAL_EXPUNGE"}
                   for op, _ in imap_move.operations)


@pytest.mark.parametrize("source", ["INBOX", "", None])
def test_move_never_searches_other_folders(imap_move, source):
    """Il 42 non e' nella cartella indicata (o in INBOX se non indicata):
    spostare il 42 di Trash sarebbe spostare un altro messaggio."""
    imap_move.messages = {"INBOX": {"99"}, "Trash": {"42"}, "Archive": set()}
    assert not move(source)
    assert imap_move.messages["Trash"] == {"42"}
    assert not any(op in {"MOVE", "COPY", "STORE"} for op, _ in imap_move.operations)


def test_router_reply_reads_original_from_requested_folder(monkeypatch):
    read = {}
    sent = {}
    monkeypatch.setattr(mail_router, "_account", lambda a: {"id": 1})

    def original(account_id, message_id, *, folder):
        read.update(account_id=account_id, message_id=message_id, folder=folder)
        return {"subject": "Subject", "from": {"emailAddress": {"address": "right@example.test"}}}

    monkeypatch.setattr(mail_router, "get_message", original)
    monkeypatch.setattr(mail_router, "send_message", lambda **kw: sent.update(kw) or {"success": True})
    assert mail_router.reply_message(1, "42", "Body", folder="Archive")["success"]
    assert read["folder"] == "Archive"
    assert sent["to"] == "right@example.test"


def test_imap_pagination_returns_all_pages_once(monkeypatch, imap):
    uids = [b"7", b"6", b"5", b"4", b"3", b"2", b"1"]
    monkeypatch.setattr(imap_client, "_uid_recent_ids", lambda c, top: uids[:top])
    monkeypatch.setattr(imap_client, "_resolve_folder", lambda c, f: "INBOX")

    def fetch(c, uid_set, query):
        items = []
        for uid in uid_set.split(","):
            raw = f"From: sender@example.test\r\nSubject: {uid}\r\nDate: Fri, {int(uid):02d} Aug 2026 10:00:00 +0000\r\n".encode()
            items.append((f"UID {uid} FLAGS ()".encode(), raw))
        return "OK", items

    monkeypatch.setattr(imap_client, "_uid_fetch", fetch)
    pages = [imap_client.get_messages("host", 993, "me", "pw", top=3, skip=skip)
             for skip in (0, 3, 6, 9)]
    assert [[m["id"] for m in page] for page in pages] == [
        ["7", "6", "5"], ["4", "3", "2"], ["1"], []]


def test_router_passes_imap_pagination(monkeypatch):
    received = {}
    monkeypatch.setattr(mail_router, "_account", lambda a: {"id": 1, "type": "imap"})
    monkeypatch.setattr(imap_client, "get_messages", lambda *a, **kw: received.update(kw) or [])
    mail_router.get_messages(1, top=30, skip=60)
    assert received["top"] == 30
    assert received["skip"] == 60


class DateOrderedIMAP:
    """High UIDs are old imports; low UIDs are the newest received mail."""
    dates = {
        "1": "25 Sep 2026 12:00:00 +0000",
        "2": "24 Sep 2026 12:00:00 +0000",
        "3": "23 Sep 2026 12:00:00 +0000",
        "40": "01 Aug 2026 12:00:00 +0000",
        "41": "02 Aug 2026 12:00:00 +0000",
        "42": "03 Aug 2026 12:00:00 +0000",
    }

    def __init__(self, supports_sort=False):
        self.supports_sort = supports_sort
        self.operations = []
        self.date_status = "OK"

    def select(self, folder):
        return "OK", [str(len(self.dates)).encode()]

    def uid(self, command, *args):
        command = command.upper()
        self.operations.append((command, args))
        if command == "SORT":
            return ("OK", [b"1 2 3 42 41 40"]) if self.supports_sort else ("NO", [b"unsupported"])
        if command == "SEARCH":
            # No charset is needed to enumerate IDs, even on older servers.
            assert args == (None, "ALL")
            return "OK", [b"1 2 3 40 41 42"]
        assert command == "FETCH"
        uid_set, query = args
        dates_only = query == "(UID BODY.PEEK[HEADER.FIELDS (DATE)])"
        assert dates_only or query == "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE CONTENT-TYPE)])"
        if dates_only and self.date_status != "OK":
            return self.date_status, [b"temporary failure"]
        items = []
        for uid in uid_set.split(","):
            raw = f"Date: {self.dates[uid]}\r\n"
            if not dates_only:
                raw += f"From: sender@example.test\r\nSubject: Mail {uid}\r\n"
            items.append((f"1 (UID {uid} FLAGS ()".encode(), raw.encode()))
        return "OK", items


@pytest.mark.parametrize("supports_sort", [True, False])
def test_imap_pages_keep_recent_low_uids_ahead_of_old_imports(monkeypatch, supports_sort):
    conn = DateOrderedIMAP(supports_sort)
    monkeypatch.setattr(imap_client, "_acquire_connection", lambda *a, **kw: ("key", conn))
    monkeypatch.setattr(imap_client, "_release_connection", lambda *a, **kw: None)
    monkeypatch.setattr(imap_client, "_resolve_folder_strict", lambda *a: "Archive")
    monkeypatch.setattr(imap_client, "_IMAP_DATE_BATCH_SIZE", 2)
    pages = [imap_client.get_messages("host", 993, "me", "pw", folder="Archive", top=2, skip=skip)
             for skip in (0, 2, 4, 6)]
    assert [[m["id"] for m in page] for page in pages] == [
        ["1", "2"], ["3", "42"], ["41", "40"], []]
    seen = [m["id"] for page in pages for m in page]
    assert len(seen) == len(set(seen)) == len(conn.dates)
    date_fetches = [args for op, args in conn.operations
                    if op == "FETCH" and args[1] == "(UID BODY.PEEK[HEADER.FIELDS (DATE)])"]
    if supports_sort:
        assert date_fetches == []
        assert not any(op == "SEARCH" for op, args in conn.operations)
    else:
        assert len(date_fetches) == 12  # Three batches for each of four page requests.
        assert all(len(args[0].split(",")) <= 2 for args in date_fetches)


def test_imap_fallback_equal_dates_have_a_stable_uid_order():
    conn = DateOrderedIMAP()
    conn.dates = {uid: "25 Sep 2026 12:00:00 +0000" for uid in conn.dates}
    assert imap_client._uid_recent_ids(conn, 2) == [b"42", b"41"]
    assert imap_client._uid_recent_ids(conn, 4)[2:] == [b"40", b"3"]


def test_imap_fallback_date_failure_never_claims_an_empty_page():
    conn = DateOrderedIMAP()
    conn.date_status = "NO"
    with pytest.raises(RuntimeError, match="date header fetch failed"):
        imap_client._uid_recent_ids(conn, 2)
