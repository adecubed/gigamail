"""The agent's tool for the identity texts: two-phase, approved at the PC."""
import asyncio
from types import SimpleNamespace

import pytest

from gigamail import policy, server, tools_identity
from gigamail.core import identity_requests

MARKER = "MARKER-7f3a-identity-text"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """An approvals store in tmp_path and the accounts and their identity
    kept in memory: nothing touches the accounts database."""
    approvals = policy.ApprovalStore(tmp_path / "approvals.db")
    policy.set_store(approvals)
    accounts = {1: {"id": 1, "email": "mario.rossi@example.com", "active": 1},
                2: {"id": 2, "email": "info@example.com", "active": 0}}
    identities = {1: {"account_id": 1, "who_am_i": "Mario, sales office",
                      "what_i_do": "I sell flats", "tone": "warm",
                      "key_info": "Open 9-18", "file_paths": ["C:/docs/prices.pdf"],
                      "folder_identities": {"f1": {"tone": "dry"}}}}
    writes = []
    core = tools_identity.core_accounts

    def get_identity(aid):
        return dict(identities.get(aid) or {
            "account_id": aid, "who_am_i": "", "what_i_do": "", "tone": "",
            "key_info": "", "file_paths": [], "folder_identities": {}})

    def set_identity(aid, who_am_i="", what_i_do="", tone="", key_info="", file_paths=None):
        writes.append({"account_id": aid, "who_am_i": who_am_i, "what_i_do": what_i_do,
                       "tone": tone, "key_info": key_info, "file_paths": file_paths})
        old = identities.get(aid) or {}
        identities[aid] = {**old, "account_id": aid, "who_am_i": who_am_i,
                           "what_i_do": what_i_do, "tone": tone, "key_info": key_info,
                           "file_paths": list(file_paths or [])}
        return get_identity(aid)

    def active():
        return next((dict(a) for a in accounts.values() if a["active"]), None)

    monkeypatch.setattr(core, "get_identity", get_identity)
    monkeypatch.setattr(core, "set_identity", set_identity)
    monkeypatch.setattr(core, "get_account_by_id", lambda aid: accounts.get(aid))
    monkeypatch.setattr(core, "get_active_account", active)
    monkeypatch.setattr(core, "get_accounts", lambda: [dict(a) for a in accounts.values()])
    yield SimpleNamespace(approvals=approvals, accounts=accounts, identities=identities,
                          writes=writes)
    policy.set_store(None)


def _approve(world, out):
    assert world.approvals.approve(out["request_id"], by="console:mario", verified=True)


def _run(out, **kw):
    return tools_identity.update_identity(request_id=out["request_id"], **kw)


def test_the_first_call_asks_for_approval_and_writes_nothing(world):
    out = tools_identity.update_identity(account_id=1, tone="formal")
    assert out["status"] == "approval_required"
    assert out["preview"]["action"] == "identity_update"
    assert world.writes == []
    args = world.approvals.get(out["request_id"])["args"]
    assert args == {"account_id": 1, "changes": {"tone": "formal"},
                    "expected": {"who_am_i": "Mario, sales office",
                                 "what_i_do": "I sell flats", "tone": "warm",
                                 "key_info": "Open 9-18"}}


def test_the_preview_shows_before_and_after_and_names_the_account(world, monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    out = tools_identity.update_identity(account_id=1, tone="formal")
    p = out["preview"]
    assert "mario.rossi@example.com" in p["subject"]
    assert identity_requests.BLOCK_PREFIX + "warm" in p["body"]
    assert identity_requests.BLOCK_PREFIX + "formal" in p["body"]


def test_the_active_account_is_used_when_none_is_given(world):
    out = tools_identity.update_identity(tone="formal")
    assert world.approvals.get(out["request_id"])["args"]["account_id"] == 1


def test_an_unknown_account_is_refused(world):
    with pytest.raises(ValueError, match="99"):
        tools_identity.update_identity(account_id=99, tone="x")
    assert world.approvals.list_pending() == []


def test_no_account_at_all_is_refused(world):
    world.accounts.clear()
    with pytest.raises(ValueError):
        tools_identity.update_identity(tone="x")


def test_nothing_to_change_is_refused(world):
    with pytest.raises(ValueError, match="nothing to change"):
        tools_identity.update_identity(account_id=1, tone="warm")
    with pytest.raises(ValueError, match="nothing to change"):
        tools_identity.update_identity(account_id=1)
    assert world.approvals.list_pending() == []


@pytest.mark.parametrize("value", ["x" * 4001, "\n".join(["l"] * 121), "a\x1bb"])
def test_an_over_limit_or_unsafe_value_is_refused_before_any_approval(world, value):
    with pytest.raises(ValueError, match="key_info"):
        tools_identity.update_identity(account_id=1, key_info=value)
    assert world.approvals.list_pending() == []


def test_an_approved_request_writes_only_the_changed_fields(world):
    out = tools_identity.update_identity(account_id=1, tone="formal", key_info="Open 8-17")
    _approve(world, out)
    # The second call's arguments are ignored: the approved ones run.
    done = _run(out, account_id=2, tone="other")
    assert done == {"success": True, "account_id": 1, "changed": ["key_info", "tone"]}
    assert world.writes == [{"account_id": 1, "who_am_i": "Mario, sales office",
                             "what_i_do": "I sell flats", "tone": "formal",
                             "key_info": "Open 8-17", "file_paths": ["C:/docs/prices.pdf"]}]


def test_emptying_a_field_is_a_change(world):
    out = tools_identity.update_identity(account_id=1, who_am_i="")
    _approve(world, out)
    _run(out)
    assert world.identities[1]["who_am_i"] == ""


def test_an_identity_edited_after_the_request_is_refused(world):
    out = tools_identity.update_identity(account_id=1, tone="formal")
    world.identities[1]["what_i_do"] = "I rent flats"   # edited in the console
    _approve(world, out)
    with pytest.raises(ValueError, match="changed after this request was made"):
        _run(out)
    assert world.writes == []
    assert world.identities[1]["tone"] == "warm"


def test_new_knowledge_files_added_meanwhile_are_kept(world):
    out = tools_identity.update_identity(account_id=1, tone="formal")
    world.identities[1]["file_paths"] = ["C:/docs/prices.pdf", "C:/docs/new.pdf"]
    _approve(world, out)
    assert _run(out)["success"] is True
    assert world.writes[-1]["file_paths"] == ["C:/docs/prices.pdf", "C:/docs/new.pdf"]
    assert world.identities[1]["tone"] == "formal"


def test_an_account_removed_after_the_request_is_refused(world):
    out = tools_identity.update_identity(account_id=1, tone="formal")
    _approve(world, out)
    del world.accounts[1]
    with pytest.raises(ValueError, match="no longer exists"):
        _run(out)
    assert world.writes == []


def test_the_request_is_not_approved_without_a_verified_human(world):
    out = tools_identity.update_identity(account_id=1, tone="formal")
    assert world.approvals.approve(out["request_id"], by="console:mario") is False
    assert world.approvals.approve(out["request_id"], by="telegram:123", verified=True) is False
    assert _run(out)["status"] == "awaiting_approval"
    assert world.writes == []


def _audit_text():
    path = policy._audit_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_no_identity_text_reaches_the_audit_log(world):
    world.identities[1]["key_info"] = "old " + MARKER
    start = len(_audit_text())
    out = tools_identity.update_identity(account_id=1, tone="new " + MARKER,
                                         who_am_i="me " + MARKER)
    _run(out)                                           # still pending
    _approve(world, out)
    assert _run(out)["success"] is True
    _run(out)                                           # already used
    rejected = tools_identity.update_identity(account_id=1, what_i_do="x " + MARKER)
    world.approvals.reject(rejected["request_id"], by="console:mario")
    _run(rejected)
    log = _audit_text()[start:]
    assert "identity_updated" in log and "approval_requested" in log
    assert MARKER not in log


def test_the_executor_audits_the_field_names_only(world):
    import json
    out = tools_identity.update_identity(account_id=1, tone="formal " + MARKER)
    _approve(world, out)
    _run(out)
    lines = [json.loads(x) for x in _audit_text().splitlines()]
    done = [x for x in lines if x["outcome"] == "identity_updated"][-1]
    assert done["args"] == {"account_id": 1, "fields": ["tone"]}


def test_a_refused_stale_request_leaves_no_text_in_the_audit_log(world):
    start = len(_audit_text())
    out = tools_identity.update_identity(account_id=1, tone="new " + MARKER)
    world.identities[1]["key_info"] = "edited " + MARKER
    _approve(world, out)
    with pytest.raises(ValueError, match="changed after"):
        _run(out)
    log = _audit_text()[start:]
    assert '"error"' in log and MARKER not in log


def test_the_request_phases_audit_the_asked_field_names(world):
    import json
    start = len(_audit_text())
    tools_identity.update_identity(account_id=1, tone="formal " + MARKER, key_info="k")
    lines = [json.loads(x) for x in _audit_text()[start:].splitlines()]
    asked = [x for x in lines if x["outcome"] == "approval_requested"][-1]
    assert asked["args"] == {"account_id": 1, "fields": ["key_info", "tone"]}


def test_only_the_four_texts_of_a_stored_request_reach_the_identity(world):
    expected = identity_requests.snapshot(world.identities[1])
    rid = world.approvals.create(
        "update_identity",
        {"account_id": 1, "changes": {"tone": "formal", "file_paths": ["C:/evil.exe"],
                                      "signature": "x"},
         "expected": expected}, {"subject": "x"})
    assert world.approvals.approve(rid, by="console:mario", verified=True)
    done = tools_identity.update_identity(request_id=rid)
    assert done["changed"] == ["tone"]
    assert world.writes[-1]["file_paths"] == ["C:/docs/prices.pdf"]
    assert world.writes[-1]["tone"] == "formal"


@pytest.fixture()
def real_db(tmp_path, monkeypatch):
    """The real accounts store, in the tests' temporary data folder."""
    import sqlite3

    from gigamail.core import accounts, identity_backup
    monkeypatch.setattr(identity_backup, "cartella", lambda root=None: str(tmp_path / "ib"))
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    aid = 4242

    def wipe():
        with sqlite3.connect(accounts.DB_PATH) as conn:
            conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
            conn.execute("DELETE FROM account_identity WHERE account_id=?", (aid,))
            conn.commit()
    wipe()
    with sqlite3.connect(accounts.DB_PATH) as conn:
        conn.execute("INSERT INTO accounts (id, name, type, email) VALUES (?,?,?,?)",
                     (aid, "Mario", "imap", "mario.rossi@example.com"))
        conn.commit()
    accounts.set_identity(aid, who_am_i="Mario", tone="warm",
                          file_paths=["C:/docs/prices.pdf"])
    accounts.set_folder_identity(aid, "folder-1", tone="dry")
    yield SimpleNamespace(aid=aid, accounts=accounts)
    wipe()
    policy.set_store(None)


def test_an_approved_update_keeps_folder_identities_and_files_in_the_real_store(real_db):
    out = tools_identity.update_identity(account_id=real_db.aid, tone="formal")
    assert policy.store().approve(out["request_id"], by="console:mario", verified=True)
    assert tools_identity.update_identity(request_id=out["request_id"])["success"] is True
    ident = real_db.accounts.get_identity(real_db.aid)
    assert ident["tone"] == "formal" and ident["who_am_i"] == "Mario"
    assert ident["file_paths"] == ["C:/docs/prices.pdf"]
    assert ident["folder_identities"]["folder-1"]["tone"] == "dry"


def test_the_cli_prints_the_whole_identity_request_before_asking(world, monkeypatch, capsys):
    from gigamail import cli, consent
    world.identities[1]["who_am_i"] = "o" * 4000
    out = tools_identity.update_identity(account_id=1, who_am_i="n" * 3999 + "Z")
    shown = []

    def require(reason):
        shown.append(capsys.readouterr().out)
        return False
    monkeypatch.setattr(consent, "require_human", require)
    assert cli.cmd_approvals_approve(SimpleNamespace(request_id=out["request_id"])) == 1
    assert shown and "o" * 4000 in shown[0] and "n" * 3999 + "Z" in shown[0]
    assert "mario.rossi@example.com" in shown[0]
    assert world.approvals.get(out["request_id"])["status"] == policy.PENDING


def test_the_tool_is_registered_dangerous_with_its_executor():
    assert server.APPROVED_EXECUTORS["update_identity"] is tools_identity._exec_update_identity
    tools = asyncio.new_event_loop().run_until_complete(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "update_identity")
    assert tool.annotations == server.DANGEROUS
    text = tool.description
    for part in ("4000", "120", "Windows Hello", "never from Telegram", "signature",
                 "knowledge files", "changed after"):
        assert part in text, part
    assert set(tool.input_schema["properties"]) == {
        "account_id", "who_am_i", "what_i_do", "tone", "key_info", "request_id"}
