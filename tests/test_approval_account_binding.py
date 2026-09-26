"""Approval payloads bind a mailbox, never the mutable active-account default."""
import pytest

from ade_mail_agent import policy, server


@pytest.fixture
def account_context(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    accounts = {1: {"id": 1, "email": "first@example.test"},
                2: {"id": 2, "email": "second@example.test"}}
    active = [1]
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: accounts[active[0]])
    monkeypatch.setattr(server.core_accounts, "get_account_by_id", lambda aid: accounts.get(aid))
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {"subject": "Original", "from": "client@example.test"})
    monkeypatch.setattr(server.mail_router, "list_folders", lambda **kw: [])
    monkeypatch.setattr(policy, "notify_approval_requested", lambda *a, **kw: None)
    yield active
    policy.set_store(None)


@pytest.mark.parametrize("tool,kwargs,backend", [
    ("send_mail", {"to": "client@example.test", "subject": "Test", "body": "hello"}, "send_message"),
    ("reply_mail", {"message_id": "42", "body": "hello", "folder": "Leads"}, "reply_message"),
    ("move_message", {"message_id": "42", "folder_id": "Archive", "source_folder": "Leads"}, "move_to_folder"),
    ("delete_message", {"message_id": "42", "folder": "Leads"}, "delete_message"),
    ("delete_folder", {"folder_id": "Leads"}, "delete_folder"),
])
def test_active_account_change_cannot_redirect_approval(account_context, monkeypatch, tool, kwargs, backend):
    calls = []
    monkeypatch.setattr(server.mail_router, backend, lambda **kw: calls.append(kw) or {"success": True})
    function = getattr(server, tool)
    pending = function(**kwargs)
    record = policy.store().get(pending["request_id"])
    assert record["args"]["account_id"] == 1
    account_context[0] = 2
    policy.store().approve(pending["request_id"])
    function(**kwargs, request_id=pending["request_id"], account_id=2)
    assert len(calls) == 1 and calls[0]["account_id"] == 1
    if tool == "reply_mail":
        assert calls[0]["folder"] == "Leads"


def test_legacy_approval_without_bound_account_fails_closed(account_context, monkeypatch):
    sent = []
    monkeypatch.setattr(server.mail_router, "send_message", lambda **kw: sent.append(kw))
    rid = policy.store().create("send_mail", {"account_id": None, "to": "client@example.test", "subject": "Test", "body": "hello", "cc": None, "bcc": None}, {})
    policy.store().approve(rid)
    with pytest.raises(ValueError, match="account fissato"):
        server.send_mail("client@example.test", "Test", "hello", request_id=rid)
    assert sent == []


def test_no_active_account_cannot_create_mutable_approval(account_context, monkeypatch):
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: None)
    with pytest.raises(ValueError, match="Nessun account"):
        server.send_mail("client@example.test", "Test", "hello")
    assert policy.store().list_pending() == []


def test_execution_does_not_resolve_new_attachment_arguments(account_context, monkeypatch):
    sent = []
    monkeypatch.setattr(server.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})
    pending = server.send_mail("client@example.test", "Test", "hello")
    policy.store().approve(pending["request_id"])
    monkeypatch.setattr(server, "_resolve_attachments", lambda *a: pytest.fail("Must use stored payload"))
    server.send_mail("ignored@example.test", "ignored", "in allegato", attachments=["new.pdf"], request_id=pending["request_id"])
    assert sent[0]["to"] == "client@example.test"
    assert sent[0]["body"] == "hello"


def test_mcp_execution_preserves_watcher_approved_contact(account_context, monkeypatch):
    sent = []
    monkeypatch.setattr(server.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})
    monkeypatch.setattr(server.mail_router, "reply_message", lambda **kw: pytest.fail("Would reply to the portal"))
    args = {"account_id": 1, "message_id": "42", "folder": "Leads",
            "to": "client@example.test", "subject": "Re: Enquiry", "body": "approved body",
            "cc": ["colleague@example.test"]}
    rid = policy.store().create("reply_mail", args, {"to": args["to"]})
    policy.store().approve(rid)
    result = server.reply_mail("ignored", "ignored", request_id=rid)
    assert result["success"] is True
    assert sent[0]["to"] == args["to"]
    assert sent[0]["subject"] == args["subject"]
    assert sent[0]["body"] == args["body"]
    assert sent[0]["cc"] == args["cc"]
    assert sent[0]["auto_submitted"] is True


@pytest.mark.parametrize("tool,kwargs,backend,key", [
    ("move_message", {"message_id": "42", "folder_id": "Archive"}, "move_to_folder", "source_folder"),
    ("delete_message", {"message_id": "42"}, "delete_message", "folder"),
])
def test_empty_folder_is_bound_to_the_previewed_inbox(account_context, monkeypatch, tool, kwargs, backend, key):
    """L'anteprima legge il 42 di INBOX: senza cartella nell'approvazione,
    l'esecuzione cercava il 42 in tutte le cartelle e agiva sul primo."""
    calls = []
    monkeypatch.setattr(server.mail_router, backend, lambda **kw: calls.append(kw) or True)
    function = getattr(server, tool)
    pending = function(**kwargs)
    assert policy.store().get(pending["request_id"])["args"][key] == "INBOX"
    policy.store().approve(pending["request_id"])
    function(**kwargs, request_id=pending["request_id"])
    assert calls[0][key] == "INBOX"
