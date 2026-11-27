"""A correspondent's changed OpenPGP key waits for the user's decision
(core/pgp.py: held_peer_keys, peer_key_info, learn_autocrypt)."""
import base64
import email
import sqlite3
import time
from contextlib import closing
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

pysequoia = pytest.importorskip("pysequoia")

from gigamail.core import imap_client, mail_router, pgp  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402

ME = "mario.rossi@example.com"
PEER = "anna.bianchi@example.com"

OLD = "Thu, 12 Nov 2026 10:00:00 +0100"
NEW = "Fri, 20 Nov 2026 10:00:00 +0100"
NEWER = "Mon, 23 Nov 2026 10:00:00 +0100"


from gigamail import policy  # noqa: E402

_REAL_NOTIFY_PLAIN = getattr(policy, "notify_plain", None)


@pytest.fixture(autouse=True)
def notices(monkeypatch):
    """Every notice the code under test would send, and none really sent."""
    sent = []
    monkeypatch.setattr(policy, "notify_plain",
                        lambda text: sent.append(text) or True, raising=False)
    return sent


@pytest.fixture(autouse=True)
def _empty_store():
    path = db_path(pgp.DB_NAME)
    if path.exists():
        path.unlink()
    yield


def _new_key():
    return pysequoia.Tsk.generate(user_id=f"<{PEER}>")


@pytest.fixture()
def peer():
    return _new_key()


@pytest.fixture()
def other():
    return _new_key()


@pytest.fixture()
def third():
    return _new_key()


def _fpr(tsk):
    return tsk.extract_certificate().fingerprint


def _autocrypt_of(tsk, addr):
    b64 = base64.b64encode(bytes(tsk.extract_certificate())).decode()
    return f"addr={addr}; prefer-encrypt=mutual; keydata={b64}"


def _mail(tsk, date, sender=PEER, addr=PEER):
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, ME, "Hello", date
    m["Autocrypt"] = _autocrypt_of(tsk, addr)
    m.attach(MIMEText("hello", "plain", "utf-8"))
    return email.message_from_bytes(m.as_bytes())


def _held_rows():
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn:
        return conn.execute(
            "SELECT lower(fingerprint), state, last_seen, told"
            " FROM held_peer_keys ORDER BY fingerprint").fetchall()


def _put_held(tsk, state, last_seen, told=0, decided_at=None, first_seen=None):
    cert = tsk.extract_certificate()
    pgp.peer_key_info(PEER)  # make sure the tables exist
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute(
            "INSERT INTO held_peer_keys(address, fingerprint, keydata, state,"
            " first_seen, last_seen, decided_at, told) VALUES (?,?,?,?,?,?,?,?)",
            (PEER, cert.fingerprint, bytes(cert), state,
             first_seen if first_seen is not None else last_seen,
             last_seen, decided_at, told))


def _write_old_store(address, tsk, last_seen):
    """The store as the previous version wrote it: no first_seen, no held table."""
    cert = tsk.extract_certificate()
    path = db_path(pgp.DB_NAME)
    with closing(sqlite3.connect(str(path))) as conn, conn:
        conn.execute("""CREATE TABLE peer_keys (
            address TEXT PRIMARY KEY, keydata BLOB NOT NULL,
            fingerprint TEXT NOT NULL, prefer_encrypt TEXT NOT NULL DEFAULT '',
            last_seen REAL NOT NULL)""")
        conn.execute(
            "INSERT INTO peer_keys VALUES (?,?,?,?,?)",
            (address, bytes(cert), cert.fingerprint, "mutual", last_seen))


def test_a_changed_key_is_held_and_the_known_one_stays(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert pgp.learn_autocrypt(_mail(other, NEW)) is None
    info = pgp.peer_key_info(PEER)
    assert info["known"]["fingerprint"] == _fpr(peer)
    assert info["held"]["fingerprint"] == _fpr(other)
    assert info["held"]["state"] == "pending"
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)


def test_the_same_key_seen_again_asks_nothing(peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(peer, NEW))
    info = pgp.peer_key_info(PEER)
    assert info["held"] is None
    assert info["known"]["first_seen"] < info["known"]["last_seen"]


def test_an_older_mail_with_another_key_creates_nothing(peer, other):
    pgp.learn_autocrypt(_mail(peer, NEW))
    pgp.learn_autocrypt(_mail(other, OLD))
    assert pgp.peer_key_info(PEER)["held"] is None


def test_a_newer_pending_key_replaces_an_older_one(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.learn_autocrypt(_mail(third, NEWER))
    assert pgp.peer_key_info(PEER)["held"]["fingerprint"] == _fpr(third)
    assert len(pgp.pending_changes()) == 1
    assert len(_held_rows()) == 1


def test_an_old_mail_does_not_bring_back_a_displaced_pending_key(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.learn_autocrypt(_mail(third, NEWER))
    pgp.learn_autocrypt(_mail(other, NEW))
    assert pgp.peer_key_info(PEER)["held"]["fingerprint"] == _fpr(third)
    assert len(_held_rows()) == 1


def test_a_display_name_and_capitals_are_the_same_correspondent(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW, sender='"Anna Bianchi" <Anna.Bianchi@Example.com>'))
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"


def test_an_own_address_is_never_learned_or_held(peer):
    mine = pgp.own_key(ME)
    pgp.learn_autocrypt(_mail(peer, OLD, sender=ME, addr=ME))
    assert pgp.peer_key_info(ME) == {"address": ME, "known": None, "held": None}
    assert pgp._cert_for(ME).fingerprint == mine.extract_certificate().fingerprint
    assert pgp.missing_keys([ME]) == []


def test_an_own_address_ignores_a_peer_row_left_in_the_store(peer):
    mine = pgp.own_key(ME)
    pgp.import_peer_key(ME, bytes(peer.extract_certificate()))
    assert pgp.peer_key_info(ME) == {"address": ME, "known": None, "held": None}
    assert pgp._cert_for(ME).fingerprint == mine.extract_certificate().fingerprint


def test_a_store_from_the_current_version_upgrades_without_a_question(peer):
    _write_old_store(PEER, peer, last_seen=1_700_000_000.0)
    info = pgp.peer_key_info(PEER)
    assert info["held"] is None
    assert info["known"]["first_seen"] == info["known"]["last_seen"] == 1_700_000_000.0
    assert pgp.pending_changes() == []


def test_the_first_seen_of_an_upgraded_key_is_kept_when_it_is_seen_again(peer):
    _write_old_store(PEER, peer, last_seen=1_700_000_000.0)
    pgp.learn_autocrypt(_mail(peer, NEW))
    info = pgp.peer_key_info(PEER)
    # Stored 0 still reads as last_seen, which has now moved on.
    assert info["known"]["first_seen"] == info["known"]["last_seen"]


def test_a_new_key_is_stored_with_first_seen(peer):
    assert pgp.learn_autocrypt(_mail(peer, OLD)) == PEER
    info = pgp.peer_key_info(PEER)
    assert info["known"]["first_seen"] == info["known"]["last_seen"] > 0


def test_a_refused_key_only_has_its_last_seen_raised(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "refused", last_seen=1_700_000_000.0, decided_at=1_700_000_100.0)
    assert pgp.learn_autocrypt(_mail(other, NEW)) is None
    ((fpr, state, last_seen, told),) = _held_rows()
    assert (fpr, state, told) == (_fpr(other).lower(), "refused", 0)
    assert last_seen > 1_700_000_000.0
    info = pgp.peer_key_info(PEER)
    assert info["held"]["state"] == "refused"
    assert pgp.pending_changes() == []


def test_last_seen_of_a_held_key_never_goes_down(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEWER))
    before = _held_rows()[0][2]
    pgp.learn_autocrypt(_mail(other, NEW))
    assert _held_rows()[0][2] == before


def test_a_pending_key_seen_again_only_raises_last_seen(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute("UPDATE held_peer_keys SET told=1")
    first = pgp.peer_key_info(PEER)["held"]["first_seen"]
    pgp.learn_autocrypt(_mail(other, NEWER))
    ((_, state, last_seen, told),) = _held_rows()
    assert (state, told) == ("pending", 1)
    held = pgp.peer_key_info(PEER)["held"]
    assert held["first_seen"] == first
    assert held["last_seen"] == last_seen > first


def test_a_replaced_key_that_comes_back_is_pending_again(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "replaced", last_seen=1_700_000_000.0,
              decided_at=1_700_000_100.0, told=3)
    pgp.learn_autocrypt(_mail(other, NEW))
    ((fpr, state, _, told),) = _held_rows()
    # told was reset to 0, then the arrival notice set its bit again.
    assert (fpr, state, told) == (_fpr(other).lower(), "pending", 1)
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"


def test_a_mail_older_than_the_decision_does_not_undo_an_acceptance(
        monkeypatch, notices, peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))      # held pending
    pgp.learn_autocrypt(_mail(peer, NEWER))     # the old key, in a later mail
    pgp.decide_change(PEER, _fpr(other), accept=True)
    del notices[:]
    pgp.learn_autocrypt(_mail(peer, NEWER))     # that mail read again
    assert pgp.pending_changes() == []
    assert pgp.held_changes([PEER]) == []
    assert notices == []
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn:
        (decided_at,) = conn.execute(
            "SELECT decided_at FROM held_peer_keys WHERE state='replaced'").fetchone()
    # A mail with the old key written after the decision is a real change.
    monkeypatch.setattr(pgp, "_mail_time", lambda msg: decided_at + 60)
    pgp.learn_autocrypt(_mail(peer, NEWER))
    held = pgp.peer_key_info(PEER)["held"]
    assert (held["fingerprint"], held["state"]) == (_fpr(peer), "pending")
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    assert len(notices) == 1


def test_a_pending_row_for_an_own_address_is_never_reported(peer):
    pgp.own_key(ME)
    cert = peer.extract_certificate()
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute(
            "INSERT INTO held_peer_keys(address, fingerprint, keydata, state,"
            " first_seen, last_seen) VALUES (?,?,?,'pending',?,?)",
            (ME, cert.fingerprint, bytes(cert), 1_700_000_000.0, 1_700_000_000.0))
    assert pgp.pending_changes() == []
    assert pgp.key_change_for(ME) is None


def test_a_peer_row_for_an_own_address_is_not_listed(peer):
    pgp.own_key(ME)
    cert = peer.extract_certificate()
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute(
            "INSERT INTO peer_keys(address, keydata, fingerprint, prefer_encrypt,"
            " last_seen, first_seen) VALUES (?,?,?,?,?,?)",
            (ME, bytes(cert), cert.fingerprint, "mutual", 1_700_000_000.0,
             1_700_000_000.0))
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert [i["address"] for i in pgp.list_peer_keys()] == [PEER]


def test_a_replaced_key_is_never_reported_as_held(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "replaced", last_seen=1_700_000_000.0,
              decided_at=1_700_000_100.0)
    assert pgp.peer_key_info(PEER)["held"] is None


def test_the_most_recently_refused_key_is_the_one_reported(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "refused", last_seen=1_700_000_000.0, decided_at=1_700_000_100.0)
    _put_held(third, "refused", last_seen=1_690_000_000.0, decided_at=1_700_000_500.0)
    assert pgp.peer_key_info(PEER)["held"]["fingerprint"] == _fpr(third)


def test_a_pending_key_comes_before_a_refused_one(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "refused", last_seen=1_700_000_000.0, decided_at=1_700_000_100.0)
    pgp.learn_autocrypt(_mail(third, NEW))
    held = pgp.peer_key_info(PEER)["held"]
    assert (held["fingerprint"], held["state"]) == (_fpr(third), "pending")


def test_pending_changes_and_list_are_sorted_by_address(peer, other):
    anna_other = pysequoia.Tsk.generate(user_id="<anna.bianchi@example.com>")
    luca = "luca.verdi@example.com"
    luca_a = pysequoia.Tsk.generate(user_id=f"<{luca}>")
    luca_b = pysequoia.Tsk.generate(user_id=f"<{luca}>")
    pgp.learn_autocrypt(_mail(luca_a, OLD, sender=luca, addr=luca))
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(luca_b, NEW, sender=luca, addr=luca))
    pgp.learn_autocrypt(_mail(anna_other, NEW))
    assert [i["address"] for i in pgp.list_peer_keys()] == [PEER, luca]
    assert [i["address"] for i in pgp.pending_changes()] == [PEER, luca]


# ── learners from several processes take turns ──────────────────────

def test_learning_starts_its_transaction_before_the_first_read(monkeypatch, peer):
    real = pgp._db
    seen = []

    def spy(write=False):
        from contextlib import contextmanager

        @contextmanager
        def wrapper():
            with real(write) as conn:
                seen.append(conn.in_transaction)
                yield conn
        return wrapper()

    monkeypatch.setattr(pgp, "_db", spy)
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert seen == [True]


def test_a_second_writer_waits_while_a_learner_holds_the_store(peer):
    pgp.peer_key_info(PEER)  # tables exist
    with pgp._db(write=True):
        other = sqlite3.connect(str(db_path(pgp.DB_NAME)), timeout=0.2)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()


def test_a_write_transaction_rolls_back_on_an_error_and_closes_the_file(peer):
    with pytest.raises(RuntimeError):
        with pgp._db(write=True) as conn:
            conn.execute(
                "INSERT INTO peer_keys(address, keydata, fingerprint, last_seen)"
                " VALUES ('x@example.com', x'00', 'F', 1)")
            raise RuntimeError("boom")
    assert pgp.list_peer_keys() == []
    db_path(pgp.DB_NAME).unlink()  # fails on Windows if a handle is left open


# ── leftovers: ties, import, a failing ALTER ─────────────────────────

def test_a_tie_keeps_the_pending_key_that_is_already_waiting(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.learn_autocrypt(_mail(third, NEW))
    assert pgp.peer_key_info(PEER)["held"]["fingerprint"] == _fpr(other)


def test_importing_the_same_key_again_keeps_its_first_seen(peer):
    pgp.import_peer_key(PEER, bytes(peer.extract_certificate()))
    first = pgp.peer_key_info(PEER)["known"]["first_seen"]
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute("UPDATE peer_keys SET first_seen=?, last_seen=?", (1000.0, 1000.0))
    pgp.import_peer_key(PEER, bytes(peer.extract_certificate()))
    known = pgp.peer_key_info(PEER)["known"]
    assert first > 1000.0 and known["first_seen"] == 1000.0
    assert known["last_seen"] > 1000.0


def test_importing_a_key_deletes_the_held_row_with_its_fingerprint(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.import_peer_key(PEER, bytes(other.extract_certificate()))
    assert _held_rows() == []
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)


class _Conn:
    """A connection whose ALTER TABLE fails, as it does when another process
    got there first (then the column exists) or for a real reason (then not)."""

    def __init__(self, conn, add_column):
        self.conn, self.add_column = conn, add_column

    def execute(self, sql, *a):
        if sql.startswith("ALTER TABLE"):
            if self.add_column:
                self.conn.execute(sql, *a)
            raise sqlite3.OperationalError("boom")
        return self.conn.execute(sql, *a)


def _old_store_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE peer_keys (
        address TEXT PRIMARY KEY, keydata BLOB NOT NULL,
        fingerprint TEXT NOT NULL, prefer_encrypt TEXT NOT NULL DEFAULT '',
        last_seen REAL NOT NULL)""")
    return conn


def test_a_failing_alter_table_is_raised_when_the_column_is_still_missing():
    with closing(_old_store_conn()) as conn:
        with pytest.raises(sqlite3.OperationalError):
            pgp._create_tables(_Conn(conn, add_column=False))


def test_a_lost_race_on_alter_table_is_not_an_error():
    with closing(_old_store_conn()) as conn:
        pgp._create_tables(_Conn(conn, add_column=True))
        assert "first_seen" in {r[1] for r in conn.execute("PRAGMA table_info(peer_keys)")}


# ── refusing to encrypt, status, deciding ────────────────────────────

def _known_then_changed(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))


def _clear_mail(subject="Contract draft", body="The confidential terms."):
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"] = ME, PEER, subject
    m.attach(MIMEText(body, "plain", "utf-8"))
    return m


class _SMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def starttls(self, **k):
        pass

    def sendmail(self, sender, recipients, payload):
        _SMTP.sent.append((sender, recipients, payload))
        return {}


@pytest.fixture()
def smtp(monkeypatch):
    _SMTP.sent = []
    monkeypatch.setattr(imap_client.smtplib, "SMTP_SSL", _SMTP)
    monkeypatch.setattr(imap_client.smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(imap_client, "_append_to_sent_folder",
                        lambda h, p, a, pw, raw: True)
    return _SMTP


def _send(**kw):
    args = dict(smtp_host="smtp.example.com", smtp_port=465, email_addr=ME,
                password="x", to=PEER, subject="Contract draft",
                body="The confidential terms.", imap_host="imap.example.com",
                imap_port=993, imap_password="x")
    args.update(kw)
    return imap_client.send_message(**args)


def _imap_account(monkeypatch):
    monkeypatch.setattr(mail_router, "_account", lambda account_id=None: {
        "id": 1, "type": "imap", "email": ME,
        "data": {"smtp_host": "smtp.example.com", "smtp_port": 465,
                 "imap_host": "imap.example.com", "imap_port": 993,
                 "password": "x"}})


def test_nothing_is_encrypted_while_a_change_is_pending(peer, other):
    _known_then_changed(peer, other)
    with pytest.raises(pgp.KeyChangePending) as e:
        pgp.encrypt_message(_clear_mail(), ME, [PEER])
    assert e.value.addresses == [PEER]
    assert PEER in e.value.it and PEER in e.value.en
    assert "nuova da accettare" in e.value.it and "waiting to be accepted" in e.value.en


def test_a_blocked_send_sends_nothing_and_says_why(smtp, peer, other):
    _known_then_changed(peer, other)
    out = _send(encrypt=True)
    assert out["success"] is False and smtp.sent == []
    assert out["blocked"] == "key_changed" and out["blocked_addresses"] == [PEER]


def test_a_send_blocked_for_another_reason_has_no_blocked_key(smtp):
    out = _send(encrypt=True)  # no key at all for the recipient
    assert out["success"] is False and "blocked" not in out


def test_the_router_keeps_the_blocked_reason(monkeypatch, smtp, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    result = mail_router.send_message(1, to=PEER, subject="s", body="b", encrypt=True)
    assert result["success"] is False and smtp.sent == []
    assert result["blocked"] == "key_changed"
    assert result["blocked_addresses"] == [PEER]


def test_a_recipient_in_to_and_cc_is_named_once(peer, other):
    _known_then_changed(peer, other)
    assert pgp.held_changes([PEER, f"Anna <{PEER.upper()}>"]) == [PEER]
    st = pgp.status(ME, [PEER, PEER])
    assert [p["address"] for p in st["pending"]] == [PEER]
    assert st["can_encrypt"] is False


def test_held_changes_keeps_the_order_of_the_recipients(peer, other):
    luca = "luca.verdi@example.com"
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(peer, OLD, sender=luca, addr=luca))
    pgp.learn_autocrypt(_mail(other, NEW, sender=luca, addr=luca))
    assert pgp.held_changes([luca, PEER, luca]) == [luca, PEER]
    assert pgp.held_changes(["nobody@example.com", ""]) == []


def test_status_shape_of_a_pending_entry(peer, other):
    _known_then_changed(peer, other)
    st = pgp.status(ME, [PEER])
    entry = st["pending"][0]
    assert entry["address"] == PEER
    assert entry["known"]["fingerprint"] == _fpr(peer)
    assert entry["held"]["fingerprint"] == _fpr(other)
    assert set(entry["known"]) == {"fingerprint", "first_seen", "last_seen"}
    assert set(entry["held"]) == {"fingerprint", "first_seen"}
    assert st["peers"] == [{"address": PEER, "fingerprint": _fpr(peer)}]


def test_status_shows_fingerprints_without_any_change(peer):
    pgp.own_key(ME)
    pgp.learn_autocrypt(_mail(peer, OLD))
    st = pgp.status(ME, [PEER])
    assert st["peers"] == [{"address": PEER, "fingerprint": _fpr(peer)}]
    assert st["pending"] == [] and st["can_encrypt"] is True


def test_accepting_makes_the_new_key_the_one_in_use(peer, other):
    pgp.own_key(ME)
    _known_then_changed(peer, other)
    out = pgp.decide_change(PEER, _fpr(other).lower(), accept=True)
    assert out == {"address": PEER, "outcome": "accepted",
                   "accepted": _fpr(other), "other": _fpr(peer)}
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    assert pgp.held_changes([PEER]) == []
    pgp.encrypt_message(_clear_mail(), ME, [PEER])


def test_accepting_keeps_the_old_key_only_as_replaced(peer, other):
    _known_then_changed(peer, other)
    before = pgp.peer_key_info(PEER)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    assert [(f, s) for f, s, _, _ in _held_rows()] == [(_fpr(peer).lower(), "replaced")]
    info = pgp.peer_key_info(PEER)
    assert info["held"] is None
    assert info["known"]["first_seen"] == before["held"]["first_seen"]


def test_keeping_the_old_key_is_remembered(peer, other):
    pgp.own_key(ME)
    _known_then_changed(peer, other)
    out = pgp.decide_change(PEER, _fpr(other), accept=False)
    assert out == {"address": PEER, "outcome": "kept",
                   "accepted": _fpr(peer), "other": _fpr(other)}
    pgp.learn_autocrypt(_mail(other, NEWER))
    assert pgp.held_changes([PEER]) == []
    assert pgp.peer_key_info(PEER)["held"]["state"] == "refused"
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    pgp.encrypt_message(_clear_mail(), ME, [PEER])  # a refused key does not block


def test_a_refused_key_can_be_accepted_later(peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=False)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)


def test_a_replaced_key_that_comes_back_is_held_again(monkeypatch, peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    # Written after the decision: a mail from before it changes nothing.
    later = time.time() + 60
    monkeypatch.setattr(pgp, "_mail_time", lambda msg: later)
    pgp.learn_autocrypt(_mail(peer, NEWER))
    held = pgp.peer_key_info(PEER)["held"]
    assert (held["fingerprint"], held["state"]) == (_fpr(peer), "pending")
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    assert pgp.held_changes([PEER]) == [PEER]


def test_deciding_on_a_key_that_is_no_longer_pending_is_refused(peer, other, third):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(third, NEWER))
    with pytest.raises(pgp.PgpError) as e:
        pgp.decide_change(PEER, _fpr(other), accept=True)
    assert "non è più la chiave in attesa" in e.value.it
    assert "no longer the key that is waiting" in e.value.en
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)


def test_deciding_on_a_replaced_or_unknown_key_is_refused(peer, other, third):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    for fp in (_fpr(peer), _fpr(third), "", "nonsense"):
        with pytest.raises(pgp.PgpError):
            pgp.decide_change(PEER, fp, accept=True)
    with pytest.raises(pgp.PgpError):
        pgp.decide_change("nobody@example.com", _fpr(other), accept=False)


def test_deciding_matches_the_address_with_a_display_name_and_capitals(peer, other):
    _known_then_changed(peer, other)
    out = pgp.decide_change(f"Anna <{PEER.upper()}>", _fpr(other), accept=False)
    assert out["address"] == PEER


def test_deciding_starts_its_transaction_before_the_first_read(monkeypatch, peer, other):
    _known_then_changed(peer, other)
    seen = []
    real = pgp._db

    def spy(write=False):
        seen.append(write)
        return real(write)

    monkeypatch.setattr(pgp, "_db", spy)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    assert seen == [True]


def test_the_router_reports_key_changed(monkeypatch, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    st = mail_router.encryption_status(1, [PEER])
    assert st["reason"] == "key_changed" and st["can_encrypt"] is False
    pgp.decide_change(PEER, _fpr(other), accept=True)
    assert mail_router.encryption_status(1, [PEER])["reason"] is None
    assert mail_router.encryption_status(1, ["nobody@example.com"])["reason"] == "keys"


# ── reading: who signed, and key_change on every mail ────────────────

def _encrypted_from(tsk, subject="Offer", body="Our best price."):
    """A mail encrypted for ME and signed by `tsk`, as it arrives."""
    inner = MIMEMultipart("mixed")
    inner.set_param("protected-headers", "v1")
    inner["Subject"] = subject
    inner.attach(MIMEText(body, "plain", "utf-8"))
    ct = pysequoia.encrypt(bytes=inner.as_bytes(),
                           recipients=[pgp.own_key(ME).extract_certificate()],
                           signer=tsk.signer())
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"], outer["Subject"] = PEER, ME, "..."
    outer["Date"] = "Thu, 12 Nov 2026 11:00:00 +0100"
    outer["Message-ID"] = "<offer-1@example.com>"
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    return email.message_from_bytes(outer.as_bytes())


def _insert_held_row(address, fingerprint, keydata, state):
    pgp.peer_key_info(address)  # make sure the tables exist
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute(
            "INSERT INTO held_peer_keys(address, fingerprint, keydata, state,"
            " first_seen, last_seen, decided_at, told) VALUES (?,?,?,?,?,?,?,?)",
            (address, fingerprint, keydata, state, 1.0, 1.0, None, 0))


def test_mail_signed_with_a_pending_key_opens_without_signed_by(peer, other):
    _known_then_changed(peer, other)
    opened, info = pgp.open_message(_encrypted_from(other), ME)
    assert info["decrypted"] is True and info["signature_valid"] is True
    assert info["signer_key"] == "pending"
    assert info["signer_fingerprint"].upper() == _fpr(other).upper()
    assert info["signer"] == PEER and info["signer_matches_from"] is False


def test_after_acceptance_the_same_mail_is_signed_by_the_sender(peer, other):
    _known_then_changed(peer, other)
    _, before = pgp.open_message(_encrypted_from(other), ME)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    after = pgp.resolve_signer(dict(before), PEER)
    assert after["signer_key"] == "accepted" and after["signer_matches_from"] is True


def test_mail_signed_with_the_replaced_key_says_so(peer, other):
    _known_then_changed(peer, other)
    mail = _encrypted_from(peer)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    _, info = pgp.open_message(mail, ME)
    assert info["signer_key"] == "replaced" and info["signer_matches_from"] is False
    with_archive = pgp.resolve_signer({"signer_fingerprint": _fpr(peer).lower(),
                                       "signature_valid": True, "signer": PEER,
                                       "signer_key": "accepted",
                                       "signer_matches_from": True}, PEER)
    assert with_archive["signer_key"] == "replaced"


def test_mail_signed_with_a_refused_key_says_so(peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=False)
    _, info = pgp.open_message(_encrypted_from(other), ME)
    assert info["signer_key"] == "refused" and info["signer_matches_from"] is False


def test_mail_signed_with_the_accepted_key_is_signed_by_the_sender(peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _, info = pgp.open_message(_encrypted_from(peer), ME)
    assert info["signer_key"] == "accepted" and info["signer"] == PEER
    assert info["signer_matches_from"] is True


def test_mail_signed_with_our_own_key_is_own():
    mine = pgp.own_key(ME)
    inner = MIMEText("note to self", "plain", "utf-8")
    ct = pysequoia.encrypt(bytes=inner.as_bytes(),
                           recipients=[mine.extract_certificate()],
                           signer=mine.signer())
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"] = ME, ME
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    _, info = pgp.open_message(email.message_from_bytes(outer.as_bytes()), ME)
    assert info["signer_key"] == "own" and info["signer"] == ME
    assert info["signer_fingerprint"].upper() == _fpr(mine).upper()


def test_a_signature_nobody_knows_keeps_its_fingerprint_and_resolves_later(peer):
    pgp.own_key(ME)
    mail = _encrypted_from(peer)
    cert = peer.extract_certificate()
    # Verified as the store knows nothing of it: build the info as the
    # archive would hold it for a signature checked by other means.
    info = {"encrypted": True, "decrypted": True, "signed": True,
            "signature_valid": True, "signer": None, "signer_key": None,
            "signer_matches_from": False,
            "signer_fingerprint": cert.fingerprint.lower()}
    assert pgp.resolve_signer(dict(info), PEER) == info
    pgp.learn_autocrypt(_mail(peer, OLD))
    out = pgp.resolve_signer(dict(info), PEER)
    assert out["signer_key"] == "accepted" and out["signer"] == PEER
    assert out["signer_matches_from"] is True
    _, opened = pgp.open_message(mail, ME)
    assert opened["signer_fingerprint"] == cert.fingerprint.lower()


def test_an_unsigned_mail_has_no_signer_fingerprint(peer):
    pgp.own_key(ME)
    inner = MIMEText("hi", "plain", "utf-8")
    ct = pysequoia.encrypt(bytes=inner.as_bytes(),
                           recipients=[pgp.own_key(ME).extract_certificate()])
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"] = PEER, ME
    outer.attach(MIMEApplication(b"Version: 1\n", "pgp-encrypted"))
    outer.attach(MIMEApplication(ct, "octet-stream"))
    _, info = pgp.open_message(email.message_from_bytes(outer.as_bytes()), ME)
    assert info["decrypted"] is True
    assert info["signer_fingerprint"] is None and info["signer_key"] is None
    assert info["signer_matches_from"] is False


def test_resolving_does_not_create_the_key_store():
    path = db_path(pgp.DB_NAME)
    assert not path.exists()
    info = {"signer_fingerprint": "ab" * 20, "signer": PEER,
            "signer_key": "accepted", "signer_matches_from": True}
    assert pgp.resolve_signer(dict(info), PEER) == info
    assert not path.exists()


def test_info_archived_before_this_change_is_left_alone():
    old = {"encrypted": True, "decrypted": True, "signature_valid": True,
           "signer": PEER, "signer_matches_from": True}
    assert pgp.resolve_signer(dict(old), PEER) == old
    assert pgp.resolve_signer(None, PEER) is None


def test_resolve_signer_never_raises_on_odd_input():
    assert pgp.resolve_signer({}, PEER) == {}
    assert pgp.resolve_signer({"signer_fingerprint": None}, PEER) == {"signer_fingerprint": None}
    assert pgp.resolve_signer({"signer_fingerprint": 12345}, None) is not None
    assert pgp.resolve_signer("not a dict", PEER) == "not a dict"


def test_resolve_signer_leaves_a_fingerprint_nobody_knows_as_it_was(peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    stored = {"signer_fingerprint": "ab" * 20, "signer": PEER,
              "signer_key": "accepted", "signer_matches_from": True}
    assert pgp.resolve_signer(dict(stored), PEER) == stored


def test_a_held_row_that_cannot_be_read_does_not_stop_other_mail(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _insert_held_row("luca.verdi@example.com", "AA" * 20, b"not a key", "pending")
    _, info = pgp.open_message(_encrypted_from(peer), ME)
    assert info["decrypted"] is True and info["signer_key"] == "accepted"
    pgp.encrypt_message(_clear_mail(), ME, [PEER])


def test_a_clear_mail_from_a_sender_with_a_pending_key_carries_key_change(
        monkeypatch, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    assert pgp.key_change_for(f"Anna <{PEER}>") == {"address": PEER,
                                                    "fingerprint": _fpr(other)}
    monkeypatch.setattr(mail_router, "_get_message_provider", lambda *a: {
        "id": "7", "subject": "Hi",
        "from": {"emailAddress": {"name": "Anna", "address": PEER}},
        "encryption": None})
    served = mail_router.get_message(1, "7")
    assert served["key_change"]["address"] == PEER
    assert served["key_change"]["fingerprint"] == _fpr(other)


def test_key_change_is_absent_without_a_pending_key(monkeypatch, peer):
    _imap_account(monkeypatch)
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert pgp.key_change_for(PEER) is None
    monkeypatch.setattr(mail_router, "_get_message_provider", lambda *a: {
        "id": "7", "from": {"emailAddress": {"address": PEER}}})
    assert "key_change" not in mail_router.get_message(1, "7")


def test_key_change_reads_a_plain_string_sender_too(monkeypatch, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    monkeypatch.setattr(mail_router, "_get_message_provider", lambda *a: {
        "id": "7", "from": f"Anna <{PEER}>"})
    assert mail_router.get_message(1, "7")["key_change"]["address"] == PEER


def test_a_failure_looking_for_key_change_still_serves_the_mail(monkeypatch):
    _imap_account(monkeypatch)
    monkeypatch.setattr(mail_router, "_get_message_provider", lambda *a: {
        "id": "7", "from": {"emailAddress": {"address": PEER}}})

    def boom(address):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(pgp, "key_change_for", boom)
    served = mail_router.get_message(1, "7")
    assert served["id"] == "7" and "key_change" not in served


def test_looking_for_key_change_does_not_create_the_key_store():
    path = db_path(pgp.DB_NAME)
    assert not path.exists()
    assert pgp.key_change_for(PEER) is None
    assert not path.exists()


@pytest.fixture()
def archive(tmp_path):
    from gigamail.core import archivio
    archivio.set_store(archivio.ArchiveStore(tmp_path / "arch.db", tmp_path / "mail"))
    yield archivio
    archivio.set_store(None)


def _clear_mail_from_peer():
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"] = PEER, ME, "Hello"
    m["Message-ID"] = "<clear-1@example.com>"
    m.attach(MIMEText("hello", "plain", "utf-8"))
    return m.as_bytes()


def test_the_archive_fallback_carries_key_change_too(monkeypatch, archive, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    rowid, _ = archive.store().salva(1, _clear_mail_from_peer(), folder="INBOX",
                                     provider_id="9")

    def gone(*a):
        raise RuntimeError("server has no such mail")

    monkeypatch.setattr(mail_router, "_get_message_provider", gone)
    from_provider_id = mail_router.get_message(1, "9", folder="INBOX")
    assert from_provider_id["source"] == "archive"
    assert from_provider_id["key_change"]["address"] == PEER
    by_arch_id = mail_router.get_message(1, f"arch-{rowid}")
    assert by_arch_id["key_change"]["address"] == PEER


def test_the_archive_read_resolves_the_signer_again(archive, peer, other):
    _known_then_changed(peer, other)
    raw = _encrypted_from(other).as_bytes()
    rowid, _ = archive.store().salva(1, raw, folder="INBOX", provider_id="5")
    first = archive.leggi(1, f"arch-{rowid}", keep_opened=True)
    assert first["encryption"]["signer_key"] == "pending"
    assert first["encryption"]["signer_matches_from"] is False
    pgp.decide_change(PEER, _fpr(other), accept=True)
    served = archive.leggi(1, f"arch-{rowid}")
    assert served["encryption"]["signer_key"] == "accepted"
    assert served["encryption"]["signer_matches_from"] is True
    assert served["encryption"]["signer"] == PEER


def test_reading_the_archive_after_the_key_store_is_gone_does_not_recreate_it(
        archive, peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    rowid, _ = archive.store().salva(1, _encrypted_from(peer).as_bytes(),
                                     folder="INBOX", provider_id="5")
    archive.leggi(1, f"arch-{rowid}", keep_opened=True)
    db_path(pgp.DB_NAME).unlink()
    again = archive.leggi(1, f"arch-{rowid}")
    assert again["encryption"]["signer"] == PEER
    assert not db_path(pgp.DB_NAME).exists()


# ── telling the user ─────────────────────────────────────────────────

def _told(address=PEER):
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn:
        return [r[0] for r in conn.execute(
            "SELECT told FROM held_peer_keys WHERE address=? ORDER BY fingerprint",
            (address,))]


def test_the_user_is_told_once_when_a_key_changes(notices, peer, other):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(other, NEW))      # the other process, same mail
    pgp.learn_autocrypt(_mail(other, NEWER))
    assert len(notices) == 1 and PEER in notices[0]
    assert ("ha una chiave di cifratura nuova" in notices[0]
            or "has a new encryption key" in notices[0])
    assert _fpr(other).lower() not in notices[0].lower()
    assert _told() == [1]


def test_first_contact_and_the_same_key_tell_nothing(notices, peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(peer, NEW))
    assert notices == []


def test_a_refused_key_seen_again_tells_nothing(notices, peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "refused", last_seen=1_700_000_000.0, decided_at=1_700_000_100.0)
    pgp.learn_autocrypt(_mail(other, NEW))
    assert notices == []


def test_a_pending_key_never_told_is_told_when_it_is_seen_again(notices, peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "pending", last_seen=1_700_000_000.0, told=0)
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.learn_autocrypt(_mail(other, NEWER))
    assert len(notices) == 1 and _told() == [1]


def test_a_pending_key_already_told_is_not_told_again(notices, peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "pending", last_seen=1_700_000_000.0, told=1)
    pgp.learn_autocrypt(_mail(other, NEW))
    assert notices == []


def test_a_replaced_key_that_comes_back_is_told_again(notices, peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _put_held(other, "replaced", last_seen=1_700_000_000.0,
              decided_at=1_700_000_100.0, told=3)
    pgp.learn_autocrypt(_mail(other, NEW))
    assert len(notices) == 1


def test_a_newer_key_for_the_same_address_is_told_too(notices, peer, other, third):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(third, NEWER))
    assert len(notices) == 2


def test_a_notice_that_fails_is_not_retried(monkeypatch, peer, other):
    calls = []

    def boom(text):
        calls.append(text)
        raise RuntimeError("no toast")

    monkeypatch.setattr(policy, "notify_plain", boom)
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(other, NEWER))
    assert len(calls) == 1 and _told() == [1]


def test_the_notice_is_sent_after_the_transaction_has_committed(monkeypatch, peer, other):
    seen = []

    def check(text):
        # A writer can start: nobody holds the store while the user is told.
        conn = sqlite3.connect(str(db_path(pgp.DB_NAME)), timeout=0.2)
        try:
            conn.execute("BEGIN IMMEDIATE")
            seen.append(conn.execute("SELECT told FROM held_peer_keys").fetchone()[0])
            conn.rollback()
        finally:
            conn.close()
        return True

    monkeypatch.setattr(policy, "notify_plain", check)
    _known_then_changed(peer, other)
    assert seen == [1]


def test_a_stopped_send_is_told_once(notices, smtp, peer, other):
    _known_then_changed(peer, other)
    del notices[:]
    pgp.note_blocked_send([PEER, PEER])
    pgp.note_blocked_send([f"Anna <{PEER.upper()}>"])
    assert len(notices) == 1 and PEER in notices[0]
    assert "non è partita" in notices[0] or "was not sent" in notices[0]
    assert _told() == [3]


def test_a_stopped_send_for_an_address_without_a_pending_key_tells_nothing(
        notices, peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.note_blocked_send([PEER, "nobody@example.com", ""])
    assert notices == []
    _known_then_changed(peer, other)
    del notices[:]
    pgp.decide_change(PEER, _fpr(other), accept=False)
    pgp.note_blocked_send([PEER])
    assert notices == []


def test_a_stopped_send_tells_each_address_with_a_pending_key(notices, peer, other):
    luca = "luca.verdi@example.com"
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(peer, OLD, sender=luca, addr=luca))
    pgp.learn_autocrypt(_mail(other, NEW, sender=luca, addr=luca))
    del notices[:]
    pgp.note_blocked_send([PEER, luca])
    assert len(notices) == 2
    assert PEER in notices[0] and luca in notices[1]


def test_a_stopped_send_notice_survives_an_unreadable_store(monkeypatch, notices):
    def boom(write=False):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(pgp, "_db", boom)
    pgp.note_blocked_send([PEER])
    assert notices == []


def test_the_router_tells_when_a_send_is_stopped(monkeypatch, notices, smtp, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    del notices[:]
    result = mail_router.send_message(1, to=PEER, subject="s", body="b", encrypt=True)
    mail_router.send_message(1, to=PEER, subject="s", body="b", encrypt=True)
    assert result["blocked"] == "key_changed" and smtp.sent == []
    assert len(notices) == 1
    assert "non è partita" in notices[0] or "was not sent" in notices[0]


def test_a_reply_to_an_encrypted_mail_is_stopped_while_a_key_is_pending(
        monkeypatch, notices, smtp, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    del notices[:]
    monkeypatch.setattr(mail_router, "get_message", lambda *a, **kw: {
        "id": "m1", "subject": "Offer",
        "from": {"emailAddress": {"address": PEER}},
        "encryption": {"decrypted": True}})
    result = mail_router.reply_message(1, message_id="m1", body="Agreed.")
    assert smtp.sent == []
    assert result["success"] is False
    assert result["blocked"] == "key_changed"
    assert result["blocked_addresses"] == [PEER]
    assert len(notices) == 1
    assert "non è partita" in notices[0] or "was not sent" in notices[0]


def test_the_router_result_is_the_same_when_telling_fails(monkeypatch, smtp, peer, other):
    _imap_account(monkeypatch)
    _known_then_changed(peer, other)
    before = mail_router.send_message(1, to=PEER, subject="s", body="b", encrypt=True)

    def boom(addresses):
        raise RuntimeError("no toast")

    monkeypatch.setattr(pgp, "note_blocked_send", boom)
    after = mail_router.send_message(1, to=PEER, subject="s", body="b", encrypt=True)
    assert after == before


def test_a_send_blocked_for_another_reason_tells_nothing(monkeypatch, notices, smtp):
    _imap_account(monkeypatch)
    result = mail_router.send_message(1, to=PEER, subject="s", body="b", encrypt=True)
    assert result["success"] is False and "blocked" not in result
    assert notices == []


def test_a_failing_notification_does_not_break_reading(monkeypatch, peer, other):
    monkeypatch.setattr(policy, "notify_plain",
                        lambda text: (_ for _ in ()).throw(RuntimeError("no toast")))
    _known_then_changed(peer, other)
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"


# ── policy.notify_plain ──────────────────────────────────────────────

class _Channel:
    def __init__(self, ok=True):
        self.sent, self.last_error, self.ok = [], "", ok

    def send(self, text, buttons=None, html=False):
        self.sent.append((text, buttons, html))
        return self.ok


def _join_threads():
    import threading
    for t in threading.enumerate():
        if t is not threading.current_thread() and not t.daemon:
            t.join(5)


def _channels(monkeypatch, channel=None, toast=True):
    from gigamail.core import desktop_notify, telegram_channel
    toasts = []
    monkeypatch.setattr(
        desktop_notify, "notify",
        lambda title, body, **kw: toasts.append((title, body, kw)) or toast)
    monkeypatch.setattr(telegram_channel, "channel", lambda: channel)
    monkeypatch.setattr(policy, "_notify_command", lambda: None)
    return toasts


def test_notify_plain_sends_the_text_with_no_buttons_and_no_approval(monkeypatch):
    channel = _Channel()
    toasts = _channels(monkeypatch, channel)
    assert _REAL_NOTIFY_PLAIN("GigaMail: ciao <b>") is True
    _join_threads()
    assert len(toasts) == 1 and toasts[0][1] == "GigaMail: ciao <b>"
    assert not toasts[0][2].get("actions")
    assert len(channel.sent) == 1
    text, buttons, html = channel.sent[0]
    assert not buttons and "ciao" in text and "<b>" not in text


def test_notify_plain_without_telegram_uses_the_desktop_only(monkeypatch):
    toasts = _channels(monkeypatch, channel=None)
    assert _REAL_NOTIFY_PLAIN("GigaMail: ciao") is True
    assert len(toasts) == 1


def test_notify_plain_runs_the_generic_command_with_the_text(monkeypatch):
    import subprocess
    _channels(monkeypatch, channel=None, toast=False)
    monkeypatch.setattr(policy, "_notify_command", lambda: ["tell", "{request_id}", "{message}"])
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: ran.append(argv))
    assert _REAL_NOTIFY_PLAIN("GigaMail: ciao") is True
    _join_threads()
    assert ran == [["tell", "", "GigaMail: ciao"]]


def test_notify_plain_is_false_when_nothing_went_out(monkeypatch):
    _channels(monkeypatch, channel=None, toast=False)
    assert _REAL_NOTIFY_PLAIN("GigaMail: ciao") is False


def test_notify_plain_never_raises(monkeypatch):
    from gigamail.core import desktop_notify, telegram_channel

    def boom(*a, **k):
        raise RuntimeError("broken")

    monkeypatch.setattr(desktop_notify, "notify", boom)
    monkeypatch.setattr(telegram_channel, "channel", boom)
    monkeypatch.setattr(policy, "_notify_command", boom)
    assert _REAL_NOTIFY_PLAIN("GigaMail: ciao") is False
    channel = _Channel(ok=False)
    _channels(monkeypatch, channel)
    monkeypatch.setattr(channel, "send", boom)
    assert _REAL_NOTIFY_PLAIN("GigaMail: ciao") is True
    _join_threads()
