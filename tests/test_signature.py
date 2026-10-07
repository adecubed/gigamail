"""A per-account signature at the bottom of every outgoing mail.

It is added when the approval request is built, so the preview the human
approves is the mail that leaves: the executed payload is never touched.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from gigamail import consent, policy, server
from gigamail.core import signature

SIG = "Mario Rossi\nVia Roma 10, Milano"


# ── the module ───────────────────────────────────────────────────────

def test_no_signature_changes_nothing(account_signature):
    assert signature.get(1) == ""
    assert signature.apply(1, "Hello") == "Hello"


def test_signature_goes_at_the_bottom_once(account_signature):
    account_signature(1, SIG)
    signed = signature.apply(1, "Hello,\nsee you tomorrow.\n\n")
    assert signed == "Hello,\nsee you tomorrow.\n\n" + SIG + "\n"
    assert signature.apply(1, signed) == signed        # a redraft: not twice


def test_signature_belongs_to_its_account(account_signature):
    account_signature(1, SIG)
    assert signature.apply(2, "Hello") == "Hello"
    assert signature.apply(None, "Hello") == "Hello"


def test_save_trims_clears_and_caps(account_signature):
    assert signature.save(1, "  Mario\r\nRossi \n") == "Mario\nRossi"
    assert signature.get(1) == "Mario\nRossi"
    assert signature.save(1, "") == ""
    assert signature.apply(1, "Hello") == "Hello"
    with pytest.raises(ValueError):
        signature.save(1, "x" * (signature.MAX_CHARS + 1))


def test_the_old_video_call_key_is_still_read(account_signature):
    account_signature.settings["firma_account_3"] = "Mario Rossi"
    assert signature.get(3) == "Mario Rossi"
    account_signature(3, "")                          # cleared on purpose
    assert signature.get(3) == ""


def test_an_unreadable_setting_sends_without_signature(monkeypatch):
    def broken(*a, **kw):
        raise OSError("database locked")
    monkeypatch.setattr(signature.accounts, "get_setting", broken)
    assert signature.apply(1, "Hello") == "Hello"


# ── MCP tools ────────────────────────────────────────────────────────

@pytest.fixture
def mcp_world(tmp_path, monkeypatch, account_signature):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    accounts = {1: {"id": 1, "email": "office@example.com"}}
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: accounts[1])
    monkeypatch.setattr(server.core_accounts, "get_account_by_id", lambda aid: accounts.get(aid))
    monkeypatch.setattr(server.mail_router, "get_message",
                        lambda **kw: {"subject": "Visit", "from": "client@example.com"})
    monkeypatch.setattr(policy, "notify_approval_requested", lambda *a, **kw: None)
    account_signature(1, SIG)
    yield
    policy.set_store(None)


def test_send_mail_preview_shows_the_signature_that_is_sent(mcp_world, monkeypatch):
    sent = []
    monkeypatch.setattr(server.mail_router, "send_message",
                        lambda **kw: sent.append(kw) or {"success": True})
    pending = server.send_mail("client@example.com", "Visit", "See you at 17:00.")
    assert pending["preview"]["body"].endswith(SIG + "\n")
    rid = pending["request_id"]
    # the agent repeating the same call gets the same request
    again = server.send_mail("client@example.com", "Visit", "See you at 17:00.")
    assert again["request_id"] == rid
    policy.store().approve(rid)
    server.send_mail("client@example.com", "Visit", "See you at 17:00.", request_id=rid)
    assert sent[0]["body"] == pending["preview"]["body"]
    assert sent[0]["body"].count(SIG) == 1


def test_reply_mail_preview_shows_the_signature(mcp_world, monkeypatch):
    sent = []
    monkeypatch.setattr(server.mail_router, "reply_message",
                        lambda **kw: sent.append(kw) or {"success": True})
    pending = server.reply_mail("42", "Thanks, confirmed.")
    assert pending["preview"]["body"] == "Thanks, confirmed.\n\n" + SIG + "\n"
    policy.store().approve(pending["request_id"])
    server.reply_mail("42", "Thanks, confirmed.", request_id=pending["request_id"])
    assert sent[0]["body"] == pending["preview"]["body"]


def test_a_signature_changed_after_approval_does_not_change_the_mail(
        mcp_world, monkeypatch, account_signature):
    sent = []
    monkeypatch.setattr(server.mail_router, "send_message",
                        lambda **kw: sent.append(kw) or {"success": True})
    pending = server.send_mail("client@example.com", "Visit", "Hello")
    account_signature(1, "Someone else")
    policy.store().approve(pending["request_id"])
    server.send_mail("client@example.com", "Visit", "Hello",
                     request_id=pending["request_id"])
    assert sent[0]["body"] == "Hello\n\n" + SIG + "\n"


# ── console ──────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, account_signature):
    from gigamail import http_api
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "local-test-token")
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    importlib.reload(http_api)
    with TestClient(http_api.app, headers={"X-ADE-Token": "local-test-token"}) as c:
        yield c


def test_console_reads_and_saves_the_signature(client, monkeypatch):
    from gigamail.http_api import accounts
    monkeypatch.setattr(accounts.core_accounts, "get_account_by_id",
                        lambda aid: {"id": aid} if aid == 1 else None)
    assert client.get("/accounts/1/signature").json() == {"signature": ""}
    r = client.post("/accounts/1/signature", json={"signature": " " + SIG + " "})
    assert r.json() == {"signature": SIG}
    assert client.get("/accounts/1/signature").json() == {"signature": SIG}
    assert client.post("/accounts/9/signature",
                       json={"signature": SIG}).status_code == 404
    too_long = "x" * (signature.MAX_CHARS + 1)
    assert client.post("/accounts/1/signature",
                       json={"signature": too_long}).status_code == 400


def test_console_compose_is_signed(client, monkeypatch, account_signature):
    from gigamail.http_api import mail
    sent = []
    account_signature(1, SIG)
    monkeypatch.setattr(mail, "_save_address", lambda addr: None)
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    monkeypatch.setattr(mail.mail_router, "send_message",
                        lambda **kw: sent.append(kw) or {"success": True})
    r = client.post("/mail/send", json={"account_id": 1, "to": "client@example.com",
                                        "subject": "Visit", "body": "Hello"})
    assert r.status_code == 200
    assert sent[0]["body"] == "Hello\n\n" + SIG + "\n"


# ── CLI ──────────────────────────────────────────────────────────────

def test_cli_sets_shows_and_clears(account_signature, capsys):
    from gigamail import cli

    def run(text=None, clear=False):
        args = type("A", (), {"account_id": 1, "text": text, "clear": clear})()
        assert cli.cmd_identity_signature(args) == 0
        return capsys.readouterr().out

    assert "nessuna firma" in run()
    assert "Mario Rossi\nVia Roma 10" in run(text=r"Mario Rossi\nVia Roma 10")
    assert signature.get(1) == "Mario Rossi\nVia Roma 10"
    assert "nessuna firma" in run(clear=True)
    assert signature.get(1) == ""
