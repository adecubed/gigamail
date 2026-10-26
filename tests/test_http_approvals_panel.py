"""The console's "waiting for you" panel: pending requests say who sends
them once approved, and recently decided ones say what happened.

Before this the new console showed only the requests its own agent bar
raised: a draft the watcher prepared from a rule was visible on Telegram
and in `gigamail approvals list`, and nowhere on screen.
"""
import importlib
import time

import pytest
from fastapi.testclient import TestClient

from gigamail import policy
from gigamail.core import rules as rules_mod


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "tok")
    from gigamail import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app, headers={"X-ADE-Token": "tok"}) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


def _request(to="mario.rossi@example.com", ttl=900.0, tool="send_mail"):
    preview = {"to": to, "subject": "Visit", "body": "hello"}
    return policy.store().create(tool, {"to": to}, preview, ttl=ttl)


def _born_from_rule(rid):
    # a rule's draft is a reply_mail request, sent by the watcher's path
    rules_mod.store().record("rule_x", 1, "m1", "mario.rossi@example.com",
                             "awaiting_approval", request_id=rid)


def test_pending_requests_say_who_completes_them(client):
    agent_rid = _request()
    watcher_rid = _request(to="anna.bianchi@example.com")
    _born_from_rule(watcher_rid)
    by_id = {r["request_id"]: r for r in client.get("/approvals").json()}
    assert by_id[agent_rid]["completed_by"] == "agent"
    assert by_id[watcher_rid]["completed_by"] == "watcher"
    assert by_id[agent_rid]["preview"]["subject"] == "Visit"


def test_recent_lists_what_was_decided_and_how_it_went(client):
    rejected = _request()
    policy.store().reject(rejected, by="console:tester")
    sent = _request(to="anna.bianchi@example.com")
    policy.store().approve(sent, by="console:tester")
    assert policy.store().consume_approved(sent, "send_mail")
    policy.store().record_outcome(sent, "ok", {"accepted": 1})
    still_waiting = _request(to="luca.verdi@example.com")
    expired = _request(to="old@example.com", ttl=0.001)
    time.sleep(0.01)

    recent = {r["request_id"]: r for r in client.get("/approvals/recent").json()}
    assert set(recent) == {rejected, sent, expired}
    assert recent[rejected]["status"] == "rejected"
    assert recent[rejected]["decided_by"] == "console:tester"
    assert recent[sent]["status"] == "executed"
    assert recent[sent]["execution_outcome"] == "ok"
    assert recent[sent]["provider_result"] == {"accepted": 1}
    assert recent[expired]["status"] == "pending" and recent[expired]["expired"] is True
    # the one still waiting is in the pending list, not here
    assert [r["request_id"] for r in client.get("/approvals").json()] == [still_waiting]


def test_recent_window_is_bounded(client):
    rid = _request()
    policy.store().reject(rid, by="console:tester")
    assert client.get("/approvals/recent?hours=0").json() == []
    assert client.get("/approvals/recent?hours=-5").json() == []
    assert [r["request_id"] for r in client.get("/approvals/recent?hours=99999").json()] == [rid]


def test_approving_reports_who_sends(client, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    agent_rid = _request()
    watcher_rid = _request(to="anna.bianchi@example.com", tool="reply_mail")
    _born_from_rule(watcher_rid)
    r = client.post(f"/approvals/{agent_rid}/approve")
    assert r.status_code == 200 and r.json()["completed_by"] == "agent"
    r = client.post(f"/approvals/{watcher_rid}/approve")
    assert r.status_code == 200 and r.json()["completed_by"] == "watcher"
    # a rule's draft is sent here too (dry run: consumed, nothing leaves)
    assert r.json()["status"] == "executed" and r.json()["outcome"] == "dryrun"
    assert policy.store().get(watcher_rid)["status"] == policy.EXECUTED
    assert rules_mod.store().get_handled("rule_x", "m1")["status"] == "sent"


def test_an_agent_request_approved_here_is_executed_by_gigamail(client, monkeypatch):
    """Approved from this page (or Telegram, or the CLI) a request of the
    agent stayed "approved" for good: only the agent bar made the agent
    call the tool again. GigaMail now completes it with the stored
    arguments, and says what happened."""
    from gigamail import consent, server
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    sent = []
    monkeypatch.setitem(server.APPROVED_EXECUTORS, "send_mail",
                        lambda a: sent.append(a) or {"success": True, "provider_result": {"accepted": [a["to"]]}})
    rid = _request()
    r = client.post(f"/approvals/{rid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed" and r.json()["outcome"] == "ok"
    assert sent == [{"to": "mario.rossi@example.com"}]
    rec = policy.store().get(rid)
    assert rec["status"] == policy.EXECUTED and rec["execution_outcome"] == "ok"
    # a second approval cannot send it again
    assert client.post(f"/approvals/{rid}/approve").status_code == 409

    # a failure is recorded and reported, not hidden behind "approved"
    monkeypatch.setitem(server.APPROVED_EXECUTORS, "send_mail",
                        lambda a: (_ for _ in ()).throw(RuntimeError("SMTP down")))
    rid2 = _request(to="anna.bianchi@example.com")
    r = client.post(f"/approvals/{rid2}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "executed" and r.json()["outcome"] == "failed"
    assert "SMTP down" in r.json()["error"]
    # a watcher draft goes out now, by the watcher's own send path
    from gigamail.watcher import execution
    gone = []
    monkeypatch.setattr(execution, "_execute_reply",
                        lambda rid, a: gone.append(rid) or policy.store().consume_approved(rid, "reply_mail") and {"success": True})
    rid3 = _request(to="w@example.com", tool="reply_mail")
    _born_from_rule(rid3)
    r = client.post(f"/approvals/{rid3}/approve").json()
    assert r["status"] == "executed" and r["completed_by"] == "watcher", r
    assert gone == [rid3]
    assert rules_mod.store().get_handled("rule_x", "m1")["status"] == "sent"


def test_approved_requests_nobody_sent_are_resumed(client, monkeypatch):
    """An approval taken by an older backend, or lost half-way, left the
    request "approved" for good and the card said "executing" for days.
    The backend's sweep completes it, and the audit says it was resumed."""
    from gigamail import completion, server
    sent = []
    monkeypatch.setitem(server.APPROVED_EXECUTORS, "send_mail",
                        lambda a: sent.append(a["to"]) or {"success": True})
    old = _request(to="left@example.com")
    policy.store().approve(old, by="console:older-backend")
    expired = _request(to="late@example.com")
    assert policy.store().approve(expired, by="console:older-backend")
    # Expire it after the approval: with a 10 ms TTL the slower Windows
    # runners reached approve() already past the deadline, and the
    # request stayed pending.
    with policy.store()._conn() as conn:
        conn.execute("UPDATE approvals SET expires_at=? WHERE request_id=?",
                     (time.time() - 60, expired))
    still_pending = _request(to="pending@example.com")
    audit = []
    monkeypatch.setattr(policy, "audit", lambda tool, args, outcome, *a, **k: audit.append((args.get("request_id"), outcome)))
    reps = completion.complete_left_behind()
    assert [r["request_id"] for r in reps] == [old]
    assert reps[0]["status"] == "executed" and reps[0]["outcome"] == "ok"
    assert sent == ["left@example.com"]
    assert (old, "approval_resumed") in audit
    assert policy.store().get(still_pending)["status"] == policy.PENDING
    assert policy.store().get(expired)["status"] == policy.APPROVED
    # nothing left: the sweep is idempotent
    assert completion.complete_left_behind() == []


def test_edit_closes_the_request_with_a_note_and_requeues_a_rule_draft(client, monkeypatch):
    """The popup's Edit: a request is frozen to what would run, so editing
    closes this one with a note; a draft born from a rule is redrafted
    by the watcher with it."""
    from gigamail.http_api import console_click
    secret = "s" * 40
    console_click.set_secret(secret)
    try:
        H = {console_click.HEADER: secret}
        rid = _request()
        _born_from_rule(rid)
        assert client.post(f"/approvals/{rid}/edit", json={"note": "shorter"}).status_code == 403
        assert client.post(f"/approvals/{rid}/edit", json={"note": " "}, headers=H).status_code == 400
        r = client.post(f"/approvals/{rid}/edit", json={"note": "shorter"}, headers=H)
        assert r.status_code == 200 and r.json()["requeued"] is True
        assert policy.store().get(rid)["status"] == policy.REJECTED
        h = rules_mod.store().get_handled("rule_x", "m1")
        assert h["status"] == "retry" and h["feedback"] == "shorter"
        # the agent's own request: closed, the note is for the agent
        rid2 = _request(to="anna.bianchi@example.com")
        r = client.post(f"/approvals/{rid2}/edit", json={"note": "add the price"}, headers=H)
        assert r.status_code == 200 and r.json()["requeued"] is False
        assert client.post(f"/approvals/{rid2}/edit", json={"note": "x"}, headers=H).status_code == 409
    finally:
        console_click.set_secret("")


def test_the_reply_alert_popup_reads_the_context_and_queues_the_instruction(client, monkeypatch):
    from gigamail.core import mail_router
    from gigamail.http_api import console_click
    from gigamail.watcher import tg_risposte
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: {"bodyPreview": "Quanto costa il trilocale?"})
    key = tg_risposte.register_context(1, {"id": "m7", "subject": "Info",
                                           "from": {"emailAddress": {"name": "Bruna", "address": "bruna@example.com"}}})
    assert client.get("/alerts/nope1234").status_code == 404
    ctx = client.get(f"/alerts/{key}").json()
    assert ctx["mittente"] == "bruna@example.com" and ctx["testo"].startswith("Quanto costa")
    secret = "s" * 40
    console_click.set_secret(secret)
    try:
        H = {console_click.HEADER: secret}
        assert client.post(f"/alerts/{key}/reply", json={"instruction": "ok"}).status_code == 403
        assert client.post(f"/alerts/{key}/reply", json={"instruction": " "}, headers=H).status_code == 400
        assert client.post(f"/alerts/{key}/reply", json={"instruction": "ok, va bene"}, headers=H).status_code == 200
        assert rules_mod.store().kv_keys(tg_risposte._KV_DESKTOP)
    finally:
        console_click.set_secret("")
