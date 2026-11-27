"""`gigamail pgp peers|accept|keep`: the terminal way to decide about a
correspondent's changed OpenPGP key (cli.py, core/pgp.py)."""
import base64
import email
import sqlite3
from argparse import Namespace
from contextlib import closing
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

pysequoia = pytest.importorskip("pysequoia")

from gigamail import cli, consent, policy  # noqa: E402
from gigamail.core import pgp  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402

ME = "mario.rossi@example.com"
PEER = "anna.bianchi@example.com"
OTHER_PEER = "luca.verdi@example.com"

OLD = "Thu, 12 Nov 2026 10:00:00 +0100"
NEW = "Fri, 20 Nov 2026 10:00:00 +0100"
NEWER = "Mon, 23 Nov 2026 10:00:00 +0100"


@pytest.fixture(autouse=True)
def notices(monkeypatch):
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


@pytest.fixture()
def verified(monkeypatch):
    """The user passed the OS verification, with no dry-run in the way."""
    monkeypatch.delenv("GIGAMAIL_CONSENT_BACKEND", raising=False)
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    monkeypatch.setattr(consent, "require_human", lambda _reason: True)


@pytest.fixture()
def refused(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")


@pytest.fixture()
def asked(monkeypatch):
    """Every reason the OS verification was asked with (it answers yes)."""
    reasons = []

    def fake(reason):
        reasons.append(reason)
        return True
    monkeypatch.setattr(consent, "require_human", fake)
    return reasons


@pytest.fixture()
def audited(monkeypatch):
    lines = []
    monkeypatch.setattr(policy, "audit",
                        lambda *a, **kw: lines.append((a, kw)))
    return lines


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


def _grouped(fingerprint):
    f = fingerprint.upper()
    return " ".join(f[i:i + 4] for i in range(0, len(f), 4))


def _mail(tsk, date, sender=PEER, addr=PEER):
    b64 = base64.b64encode(bytes(tsk.extract_certificate())).decode()
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, ME, "Hello", date
    m["Autocrypt"] = f"addr={addr}; prefer-encrypt=mutual; keydata={b64}"
    m.attach(MIMEText("hello", "plain", "utf-8"))
    return email.message_from_bytes(m.as_bytes())


def _known_then_changed(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))


def _run(fn, address=PEER):
    return fn(Namespace(address=address))


def _printed(capsys):
    return " ".join(capsys.readouterr().out.split())


# -- peers ---------------------------------------------------------------

def test_peers_lists_keys_and_what_is_waiting(capsys, peer, other):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(_new_key(), OLD, sender=OTHER_PEER, addr=OTHER_PEER))
    assert cli.cmd_pgp_peers(Namespace()) == 0
    out = capsys.readouterr().out
    assert PEER in out and OTHER_PEER in out
    assert _grouped(_fpr(peer)) in out and _grouped(_fpr(other)) in out
    waiting = [ln for ln in out.splitlines() if _grouped(_fpr(other)) in ln]
    assert waiting and ("waiting" in waiting[0] or "in attesa" in waiting[0])
    quiet = [ln for ln in out.splitlines() if OTHER_PEER in ln]
    assert quiet and "waiting" not in quiet[0] and "in attesa" not in quiet[0]


def test_peers_prints_local_dates(capsys, peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    cli.cmd_pgp_peers(Namespace())
    assert "2026-11-12" in capsys.readouterr().out


def test_peers_with_an_empty_store_says_so(capsys):
    assert cli.cmd_pgp_peers(Namespace()) == 0
    out = capsys.readouterr().out
    assert "No " in out or "Nessuna" in out


def test_peers_does_not_create_the_key_store(capsys):
    assert not db_path(pgp.DB_NAME).exists()
    assert cli.cmd_pgp_peers(Namespace()) == 0
    assert not db_path(pgp.DB_NAME).exists()


def test_peers_skips_a_row_left_for_an_own_address(capsys, peer):
    """An upgraded store holds a peer row for our own address (the previous
    version learned it from Sent copies): it is not listed, and no crash."""
    pgp.own_key(ME)
    mine = _new_key()
    cert = mine.extract_certificate()
    with closing(sqlite3.connect(str(db_path(pgp.DB_NAME)))) as conn, conn:
        conn.execute(
            "INSERT INTO peer_keys(address, keydata, fingerprint, prefer_encrypt,"
            " last_seen, first_seen) VALUES (?,?,?,?,?,?)",
            (ME, bytes(cert), cert.fingerprint, "mutual", 1_700_000_000.0,
             1_700_000_000.0))
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert cli.cmd_pgp_peers(Namespace()) == 0
    out = capsys.readouterr().out
    assert ME not in out
    assert PEER in out


def test_peers_with_a_store_but_no_keys_says_so(capsys):
    pgp.list_peer_keys()  # creates the store
    assert cli.cmd_pgp_peers(Namespace()) == 0
    out = capsys.readouterr().out
    assert "No " in out or "Nessuna" in out


# -- accept ------------------------------------------------------------

def test_accept_after_verification_changes_the_key(verified, capsys, peer, other,
                                                   monkeypatch):
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_accept) == 0
    out = capsys.readouterr().out
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    assert pgp.peer_key_info(PEER)["held"] is None
    assert PEER in out
    assert _grouped(_fpr(peer)) in out and _grouped(_fpr(other)) in out


def test_accept_prints_the_keys_before_asking_the_verification(
        monkeypatch, capsys, peer, other):
    _known_then_changed(peer, other)
    seen = {}

    def fake(_reason):
        seen["out"] = capsys.readouterr().out
        return True
    monkeypatch.setattr(consent, "require_human", fake)
    assert _run(cli.cmd_pgp_accept) == 0
    assert PEER in seen["out"]
    assert _grouped(_fpr(peer)) in seen["out"] and _grouped(_fpr(other)) in seen["out"]


def test_accept_is_audited_with_the_decision(verified, audited, peer, other):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_accept) == 0
    assert audited == [(("pgp_key_decision",
                         {"address": PEER, "accepted": _fpr(other), "other": _fpr(peer)},
                         "accepted"), {"detail": "cli"})]


def test_keep_is_audited_with_the_decision(verified, audited, peer, other):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_keep) == 0
    assert audited == [(("pgp_key_decision",
                         {"address": PEER, "accepted": _fpr(peer), "other": _fpr(other)},
                         "kept"), {"detail": "cli"})]


def test_accept_falls_back_to_a_refused_key(verified, peer, other):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_keep) == 0
    assert pgp.peer_key_info(PEER)["held"]["state"] == "refused"
    assert _run(cli.cmd_pgp_accept) == 0
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)


def test_accept_prefers_the_pending_key_over_a_refused_one(verified, peer, other, third):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_keep) == 0
    pgp.learn_autocrypt(_mail(third, NEWER))
    assert _run(cli.cmd_pgp_accept) == 0
    assert pgp.peer_cert(PEER).fingerprint == _fpr(third)


def test_accept_with_nothing_to_decide_asks_no_verification(
        asked, audited, capsys, peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert _run(cli.cmd_pgp_accept) == 1
    assert asked == [] and audited == []
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("fn", ["cmd_pgp_accept", "cmd_pgp_keep"])
def test_an_unknown_address_is_a_clear_message(asked, audited, capsys, fn):
    assert _run(getattr(cli, fn), "nobody@example.com") == 1
    assert asked == [] and audited == []
    assert "nobody@example.com" in capsys.readouterr().out


def test_an_address_is_matched_in_any_form(verified, peer, other):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_accept, f"Anna Bianchi <{PEER.upper()}>") == 0
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)


# -- keep ----------------------------------------------------------------

def test_keep_after_verification_refuses_the_key(verified, capsys, peer, other):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_keep) == 0
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    held = pgp.peer_key_info(PEER)["held"]
    assert held["state"] == "refused" and held["fingerprint"].lower() == _fpr(other).lower()
    assert pgp.held_changes([PEER]) == []
    out = capsys.readouterr().out
    assert _grouped(_fpr(peer)) in out and _grouped(_fpr(other)) in out


def test_keep_with_nothing_pending_says_so(verified, asked, capsys, peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert _run(cli.cmd_pgp_keep) == 1
    assert asked == []
    assert capsys.readouterr().out.strip()


def test_keep_does_not_act_on_a_refused_key(asked, audited, peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=False)
    assert _run(cli.cmd_pgp_keep) == 1
    assert asked == [] and audited == []


# -- verification ------------------------------------------------------

def test_without_verification_nothing_changes(refused, audited, peer, other):
    _known_then_changed(peer, other)
    assert _run(cli.cmd_pgp_accept) == 1
    assert _run(cli.cmd_pgp_keep) == 1
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"
    assert audited == []


@pytest.mark.parametrize("fn", ["cmd_pgp_accept", "cmd_pgp_keep"])
def test_without_a_consent_backend_returns_2(monkeypatch, audited, peer, other, fn):
    _known_then_changed(peer, other)

    def unavailable(_reason):
        raise consent.ConsentUnavailable("no backend")
    monkeypatch.setattr(consent, "require_human", unavailable)
    assert _run(getattr(cli, fn)) == 2
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"
    assert audited == []


def test_a_newer_key_arriving_in_between_is_never_accepted_unseen(
        monkeypatch, capsys, audited, peer, other, third):
    _known_then_changed(peer, other)

    def verify_then_a_newer_key_arrives(_reason):
        pgp.learn_autocrypt(_mail(third, NEWER))
        return True
    monkeypatch.setattr(consent, "require_human", verify_then_a_newer_key_arrives)
    assert _run(cli.cmd_pgp_accept) == 1
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"
    assert audited == []
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("fn", ["cmd_pgp_accept", "cmd_pgp_keep"])
def test_the_test_consent_override_decides_nothing(monkeypatch, capsys, audited,
                                                   peer, other, fn):
    """GIGAMAIL_CONSENT_BACKEND=allow answers yes only in dry-run, and in
    dry-run nothing is decided: the two variables never skip the verification."""
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    _known_then_changed(peer, other)
    assert _run(getattr(cli, fn)) == 0
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    held = pgp.peer_key_info(PEER)["held"]
    assert held["state"] == "pending"
    assert held["fingerprint"].lower() == _fpr(other).lower()
    assert audited == []
    assert "nothing was changed" in capsys.readouterr().out


@pytest.mark.parametrize("fn", ["cmd_pgp_accept", "cmd_pgp_keep"])
def test_deciding_without_a_key_store_creates_none(asked, audited, capsys, fn):
    assert not db_path(pgp.DB_NAME).exists()
    assert _run(getattr(cli, fn)) == 1
    assert not db_path(pgp.DB_NAME).exists()
    assert asked == [] and audited == []
    assert PEER in capsys.readouterr().out


def test_a_missing_library_is_reported_with_exit_2(monkeypatch, capsys, asked):
    monkeypatch.setattr(pgp, "available", lambda: False)
    for fn in (cli.cmd_pgp_peers, cli.cmd_pgp_accept, cli.cmd_pgp_keep):
        assert fn(Namespace(address=PEER)) == 2
    assert asked == []
    assert "pysequoia" in capsys.readouterr().out


# -- language ----------------------------------------------------------

@pytest.mark.parametrize("lang,words", [
    ("en", ["correspondents' keys", "adopt the new key", "keep the key in use"]),
    ("it", ["chiavi dei corrispondenti", "adotta la chiave nuova",
            "tieni la chiave in uso"]),
])
def test_help_is_in_the_users_language(monkeypatch, capsys, lang, words):
    monkeypatch.setenv("GIGAMAIL_LANG", lang)
    printed = ""
    for argv in (["pgp", "--help"], ["pgp", "peers", "--help"],
                 ["pgp", "accept", "--help"], ["pgp", "keep", "--help"]):
        with pytest.raises(SystemExit):
            cli.main(argv)
        printed += " " + " ".join(capsys.readouterr().out.split())
    for word in words:
        assert word in printed


@pytest.mark.parametrize("lang,word", [("it", "Nessun"), ("en", "No ")])
def test_messages_follow_the_users_language(monkeypatch, capsys, lang, word):
    monkeypatch.setenv("GIGAMAIL_LANG", lang)
    cli.cmd_pgp_peers(Namespace())
    assert word in capsys.readouterr().out
