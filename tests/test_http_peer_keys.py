"""HTTP routes that show and decide a correspondent's changed OpenPGP key.
Reading is open to the console token; deciding needs the click in the
console, and the agent has no way to decide at all."""
import base64
import email
import json
import pathlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest
from fastapi.testclient import TestClient

pysequoia = pytest.importorskip("pysequoia")

from gigamail import http_api, policy  # noqa: E402
from gigamail.core import pgp  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402
from gigamail.http_api import console_click  # noqa: E402

ME = "mario.rossi@example.com"
PEER = "anna.bianchi@example.com"

OLD = "Thu, 12 Nov 2026 10:00:00 +0100"
NEW = "Fri, 20 Nov 2026 10:00:00 +0100"
NEWER = "Mon, 23 Nov 2026 10:00:00 +0100"

SECRET = "h" * 40


@pytest.fixture(autouse=True)
def _empty_store():
    path = db_path(pgp.DB_NAME)
    if path.exists():
        path.unlink()
    yield


@pytest.fixture(autouse=True)
def _no_notices(monkeypatch):
    monkeypatch.setattr(policy, "notify_plain", lambda text: True, raising=False)


@pytest.fixture()
def client():
    console_click.set_secret(SECRET)
    try:
        with TestClient(http_api.app) as c:
            yield c
    finally:
        console_click.set_secret("")


@pytest.fixture()
def human():
    return {console_click.HEADER: SECRET}


@pytest.fixture()
def audit_log():
    path = policy._audit_path()
    if path.exists():
        path.unlink()

    def read():
        if not path.exists():
            return []
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return read


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


def _body(tsk, accept=True, address=PEER):
    return {"address": address, "fingerprint": _fpr(tsk), "accept": accept}


def _mcp_tool_names():
    import asyncio

    from gigamail.server import mcp
    loop = asyncio.new_event_loop()
    try:
        tools = loop.run_until_complete(mcp.list_tools())
    finally:
        loop.close()
    return [t.name for t in tools]


def _source_of(module):
    root = pathlib.Path(http_api.__file__).resolve().parent.parent
    return (root / module).read_text(encoding="utf-8")


def _deciding_names(names):
    return [n for n in names
            if "peer_key" in n or "decide" in n or "accept_key" in n]


def test_peer_key_info_is_readable_with_the_console_token(client, peer, other):
    _known_then_changed(peer, other)
    r = client.get("/encryption/peer_key", params={"address": PEER})
    assert r.status_code == 200
    assert r.json() == pgp.peer_key_info(PEER)
    assert r.json()["known"]["fingerprint"].lower() == _fpr(peer).lower()
    assert r.json()["held"]["fingerprint"].lower() == _fpr(other).lower()


def test_pending_lists_every_address_waiting(client, peer, other):
    assert client.get("/encryption/pending").json() == {"pending": []}
    _known_then_changed(peer, other)
    r = client.get("/encryption/pending")
    assert r.status_code == 200
    assert r.json() == {"pending": [pgp.peer_key_info(PEER)]}
    assert len(r.json()["pending"]) == 1


def test_reading_never_creates_the_key_store(client, monkeypatch):
    path = db_path(pgp.DB_NAME)
    assert not path.exists()
    assert client.get("/encryption/pending").json() == {"pending": []}
    r = client.get("/encryption/peer_key", params={"address": PEER})
    assert r.status_code == 200
    assert r.json() == {"address": PEER, "known": None, "held": None}
    assert not path.exists()


def test_without_the_library_the_reads_are_empty_and_the_decision_is_409(
        client, human, monkeypatch, peer, other):
    _known_then_changed(peer, other)
    monkeypatch.setattr(pgp, "available", lambda: False)
    assert client.get("/encryption/pending").json() == {"pending": []}
    r = client.get("/encryption/peer_key", params={"address": PEER})
    assert r.status_code == 200
    assert r.json() == {"address": PEER, "known": None, "held": None}
    r = client.post("/encryption/peer_key/decide", json=_body(other),
                    headers=human)
    assert r.status_code == 409
    assert r.json()["detail"]


def test_deciding_without_the_click_secret_is_refused(client, peer, other):
    _known_then_changed(peer, other)
    r = client.post("/encryption/peer_key/decide", json=_body(other))
    assert r.status_code == 403
    assert r.json()["detail"] == "only from the console"
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"


def test_the_click_is_checked_before_the_body_or_the_store(client, audit_log):
    # No store, a body that means nothing, no click: only 403 comes back.
    for body in ({"address": PEER, "fingerprint": "ab" * 20, "accept": True},
                 {"address": "", "fingerprint": "", "accept": True},
                 {"nonsense": 1}, {}):
        r = client.post("/encryption/peer_key/decide", json=body)
        assert r.status_code == 403
        assert r.json() == {"detail": "only from the console"}
    r = client.post("/encryption/peer_key/decide", content=b"not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 403
    assert not db_path(pgp.DB_NAME).exists()
    assert audit_log() == []


def test_a_wrong_click_secret_is_refused(client, peer, other):
    _known_then_changed(peer, other)
    r = client.post("/encryption/peer_key/decide", json=_body(other),
                    headers={console_click.HEADER: "x" * 40})
    assert r.status_code == 403
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)


def test_a_console_click_accepts_and_is_audited(client, human, audit_log,
                                                 peer, other):
    _known_then_changed(peer, other)
    r = client.post("/encryption/peer_key/decide", json=_body(other),
                    headers=human)
    assert r.status_code == 200
    out = r.json()
    assert out["outcome"] == "accepted"
    assert out["accepted"].lower() == _fpr(other).lower()
    assert out["other"].lower() == _fpr(peer).lower()
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    lines = [e for e in audit_log() if e["tool"] == "pgp_key_decision"]
    assert len(lines) == 1
    assert lines[0]["outcome"] == "accepted"
    assert lines[0]["detail"] == "console click"
    assert lines[0]["args"] == {"address": PEER, "accepted": out["accepted"],
                                "other": out["other"]}
    assert lines[0]["args"]["accepted"].lower() == _fpr(other).lower()
    assert lines[0]["args"]["other"].lower() == _fpr(peer).lower()


def test_a_console_click_keeps_the_old_key_and_is_audited(
        client, human, audit_log, peer, other):
    _known_then_changed(peer, other)
    r = client.post("/encryption/peer_key/decide",
                    json=_body(other, accept=False), headers=human)
    assert r.status_code == 200
    assert r.json()["outcome"] == "kept"
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    lines = [e for e in audit_log() if e["tool"] == "pgp_key_decision"]
    assert len(lines) == 1 and lines[0]["outcome"] == "kept"
    args = lines[0]["args"]
    assert set(args) == {"address", "accepted", "other"}
    assert args["address"] == PEER
    assert args["accepted"].lower() == _fpr(peer).lower()   # the known key stays
    assert args["other"].lower() == _fpr(other).lower()     # the refused one


def test_a_stale_fingerprint_answers_409(client, human, audit_log,
                                         peer, other, third):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(third, NEWER))   # the one the person saw is gone
    r = client.post("/encryption/peer_key/decide", json=_body(other),
                    headers=human)
    assert r.status_code == 409
    assert r.json()["detail"]
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    assert [e for e in audit_log() if e["tool"] == "pgp_key_decision"] == []


@pytest.mark.parametrize("address", ["", "   ", "not an address", "a@b@c"])
def test_an_empty_or_malformed_address_answers_400(client, human, audit_log,
                                                   peer, other, address):
    _known_then_changed(peer, other)
    r = client.post("/encryption/peer_key/decide",
                    json=_body(other, address=address), headers=human)
    assert r.status_code == 400
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)
    assert [e for e in audit_log() if e["tool"] == "pgp_key_decision"] == []


def test_the_agent_has_no_way_to_decide_a_key():
    names = _mcp_tool_names()
    assert names, "the list must not be empty, or this test proves nothing"
    assert _deciding_names(names) == []
    for module in ("server.py", "remote_http.py"):
        source = _source_of(module)
        assert "decide_change" not in source and "import_peer_key" not in source


def test_the_agent_check_is_not_vacuous():
    assert _deciding_names(["send_mail", "decide_peer_key", "accept_key",
                            "get_peer_key", "list_mail"]) == [
        "decide_peer_key", "accept_key", "get_peer_key"]
