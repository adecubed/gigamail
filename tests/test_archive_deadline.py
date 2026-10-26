"""The archive step of a watcher tick is bounded in time.

A server that never finishes a FETCH used to freeze the whole watcher:
the socket timeout bounds each recv, and a server that keeps sending a
byte now and then resets it forever. These tests run the real imaplib
client against a loopback server that does exactly that.
"""
import imaplib
import socket
import threading
import time
from email.message import EmailMessage

import pytest

from gigamail.core import archivio, archivio_sync, mail_router, outlook_import
from gigamail.core import imap_client as ic


def _mime(message_id: str, subject: str = "Viewing request") -> bytes:
    m = EmailMessage()
    m["Message-ID"] = message_id
    m["From"] = "mario.rossi@example.com"
    m["To"] = "info@example.com"
    m["Subject"] = subject
    m["Date"] = "Wed, 14 Oct 2026 10:00:00 +0200"
    m.set_content("Is the flat in Via Roma 10 still available?")
    return m.as_bytes()


class FakeImapServer:
    """A loopback IMAP server with one folder, INBOX.

    With trickle=False it answers every command at once. With trickle=True
    a UID FETCH starts a 100 kB literal and then sends one byte every
    `drip` seconds, forever: the stuck FETCH seen in the field."""

    def __init__(self, messages=None, trickle=False, drip=0.05):
        self.messages = dict(messages or {})
        self.trickle = trickle
        self.drip = drip
        self.fetched = []
        self.session_over = threading.Event()
        self._stop = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(0.1)
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self._stop.set()
        self._listener.close()

    def _accept(self):
        while not self._stop.is_set():
            try:
                sock, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._session, args=(sock,),
                             daemon=True).start()

    def _session(self, sock):
        sock.settimeout(5)
        try:
            with sock, sock.makefile("rb") as reader:
                # PREAUTH: already logged in, as after _connect.
                sock.sendall(b"* PREAUTH fake IMAP ready\r\n")
                for line in reader:
                    if self._stop.is_set() or not self._answer(sock, line):
                        return
        except OSError:
            pass
        finally:
            self.session_over.set()

    def _answer(self, sock, line: bytes) -> bool:
        words = line.decode().split()
        tag, verb = words[0], words[1].upper()
        sub = words[2].upper() if len(words) > 2 else ""
        ok = f"{tag} OK done\r\n".encode()
        if verb == "CAPABILITY":
            sock.sendall(b"* CAPABILITY IMAP4rev1\r\n" + ok)
        elif verb == "LIST":
            sock.sendall(b'* LIST (\\HasNoChildren) "/" INBOX\r\n' + ok)
        elif verb in ("EXAMINE", "SELECT"):
            sock.sendall(f"* {len(self.messages)} EXISTS\r\n"
                         "* OK [UIDVALIDITY 7] UIDs valid\r\n"
                         f"{tag} OK [READ-ONLY] done\r\n".encode())
        elif verb == "UID" and sub == "SEARCH":
            uids = " ".join(str(u) for u in sorted(self.messages))
            sock.sendall(f"* SEARCH {uids}\r\n".encode() + ok)
        elif verb == "UID" and sub == "FETCH":
            uids = [int(u) for u in words[3].split(",")]
            self.fetched.extend(uids)
            if self.trickle:
                self._trickle(sock, uids[0])
                return False
            for uid in uids:
                raw = self.messages[uid]
                sock.sendall(
                    f'* {uid} FETCH (UID {uid} INTERNALDATE '
                    f'"14-Oct-2026 10:00:00 +0200" RFC822 {{{len(raw)}}}'
                    "\r\n".encode() + raw + b")\r\n")
            sock.sendall(ok)
        elif verb == "LOGOUT":
            sock.sendall(b"* BYE bye\r\n" + ok)
            return False
        else:
            sock.sendall(ok)
        return True

    def _trickle(self, sock, uid):
        sock.sendall(f'* {uid} FETCH (UID {uid} RFC822 {{100000}}\r\n'.encode())
        while not self._stop.is_set():
            time.sleep(self.drip)
            sock.sendall(b"x")   # raises once the client drops the socket


@pytest.fixture()
def st(tmp_path):
    s = archivio.ArchiveStore(tmp_path / "a.db", tmp_path / "mail")
    archivio.set_store(s)
    yield s
    archivio.set_store(None)


@pytest.fixture()
def servers(monkeypatch):
    """account id -> FakeImapServer; sincronizza() reaches them through
    the real credentials and connection hooks, with a 1 s recv timeout."""
    by_account = {}
    monkeypatch.setattr(mail_router, "_account",
                        lambda aid: {"id": aid, "type": "imap"})
    monkeypatch.setattr(
        mail_router, "_imap_credentials",
        lambda a: ("127.0.0.1", by_account[a["id"]].port,
                   f"user{a['id']}@example.com", "secret"))

    def acquire(host, port, user, pwd, force_new=False):
        conn = imaplib.IMAP4(host, port, timeout=1)
        return ic._connection_key(host, port, user, pwd), conn

    monkeypatch.setattr(ic, "_acquire_connection", acquire)
    yield by_account
    for server in by_account.values():
        server.close()


@pytest.fixture()
def short_budget(monkeypatch):
    monkeypatch.setattr(archivio_sync, "ACCOUNT_BUDGET", 0.3)
    monkeypatch.setattr(archivio_sync, "HARD_STOP_GRACE", 0.5)


# -- a FETCH that never finishes ------------------------------------------

def test_a_fetch_that_never_finishes_is_cut_off(st, servers, short_budget):
    servers[6] = FakeImapServer({1: _mime("<1@example.com>")}, trickle=True)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="next tick"):
        archivio_sync.sincronizza(6, budget=archivio_sync.ACCOUNT_BUDGET)
    assert time.monotonic() - started < 5
    assert servers[6].fetched == [1]
    assert servers[6].session_over.wait(5)
    # Nothing was saved, so the next tick starts from the same message.
    assert not (st.stato(6, "INBOX") or {}).get("cursor")


def test_a_stuck_account_does_not_stop_the_others(st, servers, short_budget,
                                                  monkeypatch, capsys):
    from gigamail.core import accounts as core_accounts
    from gigamail.watcher.runner import Watcher

    servers[6] = FakeImapServer({1: _mime("<1@example.com>")}, trickle=True)
    servers[8] = FakeImapServer({4: _mime("<4@example.com>")})
    monkeypatch.setattr(core_accounts, "get_accounts",
                        lambda: [{"id": 6, "type": "imap"},
                                 {"id": 8, "type": "imap"}])
    monkeypatch.setattr(outlook_import, "avvia_se_serve",
                        lambda aid: "non-disponibile")
    w = Watcher(interval=120, verbose=True)
    beats = []
    monkeypatch.setattr(w, "heartbeat", lambda: beats.append(1))

    started = time.monotonic()
    saved = w.archivia_posta()

    assert time.monotonic() - started < 8
    assert saved == 1 and sum(st.conta(8).values()) == 1
    assert servers[8].fetched == [4]
    out = capsys.readouterr().out
    assert "archivio 6 non aggiornato" in out and "next tick" in out
    # The heartbeat keeps going: the console does not report a dead watcher.
    assert beats


def test_the_watchdog_leaves_a_connection_that_finished_in_time(servers):
    servers[1] = FakeImapServer()
    conn = imaplib.IMAP4("127.0.0.1", servers[1].port, timeout=1)
    with ic.abort_after(conn, 0.2) as cut:
        assert conn.noop()[0] == "OK"
    time.sleep(0.4)
    assert not cut.is_set()
    assert conn.noop()[0] == "OK"
    conn.logout()


def test_no_budget_means_no_watchdog(servers):
    servers[1] = FakeImapServer()
    conn = imaplib.IMAP4("127.0.0.1", servers[1].port, timeout=1)
    with ic.abort_after(conn, None) as cut:
        pass
    assert not cut.is_set()
    assert conn.noop()[0] == "OK"
    conn.logout()


# -- the budget between commands ------------------------------------------

@pytest.fixture()
def late(monkeypatch):
    """Turns the deadline on when the test says so, instead of racing a
    real clock."""
    state = {"late": False}
    monkeypatch.setattr(archivio_sync, "_expired",
                        lambda deadline: deadline is not None and state["late"])
    return state


def test_imap_sync_stops_between_batches_and_resumes(st, servers, late,
                                                     monkeypatch):
    servers[6] = FakeImapServer({u: _mime(f"<{u}@example.com>")
                                 for u in (1, 2, 3)})
    monkeypatch.setattr(archivio_sync, "_LOTTO_IMAP", 1)

    def after_first_batch():
        late["late"] = True

    out = archivio_sync.sincronizza(6, battito=after_first_batch, budget=60)
    assert out["timed_out"] == 1
    assert out["nuovi"] == 1 and out["restano"] == 2
    state = st.stato(6, "INBOX")
    assert state["cursor"] == "1" and state["complete"] == 0

    late["late"] = False
    out = archivio_sync.sincronizza(6)
    assert out["nuovi"] == 2 and not out.get("timed_out")
    assert servers[6].fetched == [1, 2, 3]
    assert st.stato(6, "INBOX")["complete"] == 1


def test_graph_sync_stops_between_messages_and_resumes(st, late):
    raws = {f"m{i}": _mime(f"<g{i}@example.com>") for i in range(3)}

    def get(url):
        if "/mailFolders?" in url:
            return {"value": [{"id": "inbox", "displayName": "Inbox"}]}
        return {"value": [{"id": m} for m in raws]}

    downloaded = []

    def get_raw(url):
        mid = url.split("/messages/")[1].split("/")[0]
        downloaded.append(mid)
        late["late"] = True
        return raws[mid]

    out = archivio_sync.sincronizza_graph(5, get=get, get_raw=get_raw,
                                          deadline=0.0)
    assert out["timed_out"] == 1 and out["nuovi"] == 1
    assert downloaded == ["m0"]
    state = st.stato(5, "inbox")
    assert state["complete"] == 0 and "/mailFolders/inbox/messages" in state["cursor"]

    late["late"] = False
    downloaded.clear()
    out = archivio_sync.sincronizza_graph(5, get=get, get_raw=get_raw)
    assert out["nuovi"] == 2 and downloaded == ["m1", "m2"]
    assert st.stato(5, "inbox")["complete"] == 1
