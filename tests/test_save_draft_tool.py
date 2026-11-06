"""The save_draft MCP tool: an agent can leave a mail in the Drafts folder
for the user to change and send, instead of asking to send it.

It sends nothing, so it runs at once (WRITE_SAFE) and is audited; a reply
draft follows reply_mail's fixed addressing.
"""
import asyncio
import json

import pytest

from gigamail import gen_toolmap, policy, server
from gigamail.core import drafts


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    drafts.set_store(drafts.DraftStore(tmp_path / "drafts.db"))
    log = {"save": [], "fail": None}

    def _save(account_id=None, draft=None, remote_id=None):
        log["save"].append((account_id, dict(draft)))
        if log["fail"]:
            return {"success": False, "error": log["fail"]}
        return {"success": True, "remote_id": "r1", "remote_folder": "Drafts"}

    monkeypatch.setattr(server.mail_router, "save_draft", _save)
    monkeypatch.setattr(server.core_accounts, "get_active_account",
                        lambda: {"id": 3, "email": "me@example.com"})
    monkeypatch.setattr(server.signature, "apply", lambda account_id, body: body)
    monkeypatch.setattr(server.mail_router, "send_message",
                        lambda **kw: pytest.fail("save_draft must not send"))
    yield log
    drafts.set_store(None)


def _audit_lines():
    path = policy._audit_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_new_draft_reaches_the_drafts_folder_and_the_audit(mailbox):
    out = server.save_draft(body="Hello", to="mario.rossi@example.com",
                            subject="Quote", cc=["anna.bianchi@example.com"])
    assert out["success"] and out["in_mailbox"] and out["folder"] == "Drafts"
    account_id, draft = mailbox["save"][0]
    assert account_id == 3
    assert draft["to"] == "mario.rossi@example.com"
    assert draft["cc"] == "anna.bianchi@example.com"
    assert draft["subject"] == "Quote" and draft["body"] == "Hello"
    assert drafts.store().get(out["draft_id"])["in_mailbox"]
    line = [e for e in _audit_lines() if e["tool"] == "save_draft"][-1]
    assert line["outcome"] == "executed"
    assert line["args"]["draft_id"] == out["draft_id"]
    assert "body" not in line["args"]


def test_reply_draft_goes_to_the_sender_not_to_the_given_address(mailbox, monkeypatch):
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {
        "from": {"emailAddress": {"address": "client@example.com"}},
        "subject": "Visit on Thursday"})
    out = server.save_draft(body="Thursday is fine", to="someone.else@example.com",
                            reply_to_message_id="m42")
    _, draft = mailbox["save"][0]
    assert draft["to"] == "client@example.com"
    assert draft["subject"] == "Re: Visit on Thursday"
    assert draft["reply_to_id"] == "m42"
    assert out["success"]


def test_reply_subject_is_not_prefixed_twice(mailbox, monkeypatch):
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {
        "from": "client@example.com", "subject": "RE: Visit"})
    server.save_draft(body="ok", reply_to_message_id="m42")
    assert mailbox["save"][0][1]["subject"] == "RE: Visit"


def test_reply_to_a_missing_message_saves_nothing(mailbox, monkeypatch):
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: None)
    out = server.save_draft(body="ok", reply_to_message_id="gone")
    assert not out["success"] and out["draft_id"] is None
    assert mailbox["save"] == [] and drafts.store().list() == []


def test_a_failed_copy_keeps_the_draft_in_gigamail_and_says_why(mailbox):
    mailbox["fail"] = "Drafts folder not found"
    out = server.save_draft(body="Hello", to="mario.rossi@example.com")
    assert out["success"] and not out["in_mailbox"]
    assert "Drafts folder not found" in out["error"]
    assert drafts.store().get(out["draft_id"])["body"] == "Hello"
    line = [e for e in _audit_lines() if e["tool"] == "save_draft"][-1]
    assert line["outcome"] == "saved_locally"


def test_the_signature_is_added_like_on_a_send(mailbox, monkeypatch):
    monkeypatch.setattr(server.signature, "apply",
                        lambda account_id, body: body + "\n-- \nMario")
    server.save_draft(body="Hello", to="mario.rossi@example.com")
    assert mailbox["save"][0][1]["body"].endswith("-- \nMario")


def test_save_draft_is_write_safe_in_the_schema_and_the_map():
    tools = asyncio.new_event_loop().run_until_complete(server.mcp.list_tools())
    tool = {t.name: t for t in tools}["save_draft"]
    assert gen_toolmap._classify(tool) == "WRITE_SAFE"
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False
    assert "request_id" not in (tool.input_schema or {}).get("properties", {})
