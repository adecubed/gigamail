"""A burst of mail reads stops and waits for a person.

Exfiltration needs two halves: reading a lot, and carrying it out. The
second half may run through the harness's own shell or fetch, where
GigaMail has no gate, so GigaMail gates the first: past a number of reads
in a short window, the next read executes nothing and asks a person, out
of band, whether the agent may go on.
"""
import pytest

from gigamail import policy
from gigamail import server as srv
from gigamail.core import read_budget


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    monkeypatch.setenv("GIGAMAIL_READ_BURST_MAX", "3")
    monkeypatch.setenv("GIGAMAIL_READ_BURST_WINDOW", "600")
    yield
    policy.set_store(None)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def clock():
    c = Clock()
    read_budget.reset(c)
    return c


@pytest.fixture()
def mailbox(monkeypatch):
    calls = []

    def get_message(**kw):
        calls.append(kw["message_id"])
        return {"id": kw["message_id"], "subject": "Hi",
                "body": {"contentType": "text", "content": "Hello"}}
    monkeypatch.setattr(srv.mail_router, "get_message", get_message)
    return calls


def _read(i):
    return srv.read_message(message_id=str(i))


def test_reads_under_the_budget_go_through(clock, mailbox):
    for i in range(3):
        assert _read(i)["body"]["content"] == "Hello"
    assert mailbox == ["0", "1", "2"]


def test_the_read_past_the_budget_reads_nothing_and_asks_a_person(clock, mailbox):
    for i in range(3):
        _read(i)
    r = _read(3)
    assert r["status"] == "approval_required" and r["request_id"]
    assert "body" not in r and mailbox == ["0", "1", "2"]
    rec = policy.store().get(r["request_id"])
    assert rec["tool"] == read_budget.TOOL and rec["status"] == policy.PENDING
    # every content read counts: attachments and searches as well
    assert srv.read_attachment(message_id="1", filename="a.pdf")["status"] == "awaiting_approval"
    assert srv.search_mail(query="x")["status"] == "awaiting_approval"


def test_waiting_does_not_read_and_does_not_ask_again(clock, mailbox):
    for i in range(4):
        _read(i)
    first = policy.store().list_pending()
    r = _read(5)
    assert r["status"] == "awaiting_approval"
    assert policy.store().list_pending() == first and mailbox == ["0", "1", "2"]


def test_approval_gives_a_fresh_budget(clock, mailbox):
    for i in range(4):
        _read(i)
    rid = policy.store().list_pending()[0]["request_id"]
    policy.store().approve(rid, by="console:test")
    for i in range(3):
        assert _read(10 + i)["body"]["content"] == "Hello"
    assert _read(20)["status"] == "approval_required"


def test_approval_completed_by_the_console_counts_too(clock, mailbox):
    for i in range(4):
        _read(i)
    rid = policy.store().list_pending()[0]["request_id"]
    policy.store().approve(rid, by="console:test")
    srv.execute_approved(rid)      # what the console does on approve
    assert policy.store().get(rid)["status"] == policy.EXECUTED
    assert _read(10)["body"]["content"] == "Hello"


def test_rejection_ends_reading_for_the_session(clock, mailbox):
    for i in range(4):
        _read(i)
    rid = policy.store().list_pending()[0]["request_id"]
    policy.store().reject(rid, by="console:test")
    r = _read(10)
    assert r["status"] == "rejected" and "body" not in r
    clock.t += 3600
    assert _read(11)["status"] == "rejected"
    assert mailbox == ["0", "1", "2"]


def test_reads_spread_over_time_never_pause(clock, mailbox):
    for i in range(10):
        clock.t += 300          # one read every five minutes
        assert _read(i)["body"]["content"] == "Hello"


def test_an_unanswered_request_that_expired_asks_again(clock, mailbox, monkeypatch):
    for i in range(4):
        _read(i)
    rid = policy.store().list_pending()[0]["request_id"]
    real_get = policy.store().get
    monkeypatch.setattr(policy.store(), "get",
                        lambda r: dict(real_get(r), expired=True) if r == rid else real_get(r))
    r = _read(5)
    assert r["status"] == "approval_required" and r["request_id"] != rid


def test_no_tool_raises_the_budget():
    import asyncio
    tools = {t.name for t in asyncio.new_event_loop().run_until_complete(srv.mcp.list_tools())}
    assert read_budget.TOOL not in tools
    assert not {t for t in tools if "budget" in t or "continue" in t}
