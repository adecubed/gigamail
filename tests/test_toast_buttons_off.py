"""Toasts that had nothing to press.

Seen live: on a machine whose HKLM gigamail:// still ran the old
ade_mail_agent CLI every toast went out without its buttons and said
nothing about it; past three requests in a tick the summary toast had no
button at all, not even one to open the list.
"""
import pytest

from gigamail import policy
from gigamail.core import desktop_notify as d


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    monkeypatch.delenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", raising=False)
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


LEGACY = r'"C:\old\.venv\Scripts\python.exe" -m ade_mail_agent.cli open-url "%1"'


def test_the_reason_buttons_are_off(monkeypatch):
    monkeypatch.setattr(d.sys, "platform", "win32")
    monkeypatch.setattr(d, "_machine_command", lambda: LEGACY)
    assert d.buttons_off_reason() == "legacy"
    monkeypatch.setattr(d, "_machine_command", lambda: None)
    assert d.buttons_off_reason() == "missing"
    monkeypatch.setattr(d, "_machine_command", lambda: r'"C:\x\other.exe" "%1"')
    assert d.buttons_off_reason() == "missing"
    monkeypatch.setattr(d, "protocol_registered", lambda: True)
    assert d.buttons_off_reason() == ""
    monkeypatch.setattr(d.sys, "platform", "linux")
    assert d.buttons_off_reason() == "platform"


def test_a_toast_that_loses_its_buttons_says_why_and_where_to_fix_it():
    actions = policy.toast_actions("req_ab12")
    body, kept = d._buttons_or_note("GigaMail: reply_mail awaiting approval", actions, "legacy")
    assert kept is None
    assert "old installation" in body and "Enable buttons (UAC)" in body
    body, kept = d._buttons_or_note("b", actions, "missing")
    assert kept is None and "not registered" in body
    # with the scheme working nothing changes
    assert d._buttons_or_note("b", actions, "") == ("b", actions)
    assert d._buttons_or_note("b", None, "legacy") == ("b", None)


def test_the_audit_says_a_toast_went_out_without_buttons(monkeypatch):
    monkeypatch.setattr(d, "notify", lambda *a, **k: True)
    monkeypatch.setattr(d, "buttons_off_reason", lambda: "legacy")
    seen = []
    monkeypatch.setattr(policy, "audit", lambda tool, args, outcome, **kw: seen.append(kw.get("detail")))
    policy.notify_approval_requested("req_t", "reply_mail", {"subject": "s"},
                                     actions=policy.toast_actions("req_t"))
    assert "desktop, no buttons: legacy registration" in seen
    # a toast that never had buttons is just a toast
    seen.clear()
    policy.notify_approval_requested("req_u", "reply_mail", {"subject": "s"})
    assert "desktop" in seen
    # off Windows there are no buttons to lose
    seen.clear()
    monkeypatch.setattr(d, "buttons_off_reason", lambda: "platform")
    policy.notify_approval_requested("req_v", "reply_mail", {"subject": "s"},
                                     actions=policy.toast_actions("req_v"))
    assert "desktop" in seen


def test_the_summary_of_a_busy_tick_opens_waiting_for_you(monkeypatch):
    shown = []
    monkeypatch.setattr(d, "notify", lambda title, body, **k: shown.append(k.get("actions")) or True)
    monkeypatch.setattr(d, "buttons_off_reason", lambda: "")
    policy.begin_notify_batch()
    for i in range(5):
        policy.notify_approval_requested(f"req_{i}", "reply_mail", {"subject": f"Request {i}"})
    assert policy.end_notify_batch() == 5
    assert shown == [[("📋 Open", "gigamail://pending")]]
    # successive summaries replace each other instead of piling up
    assert d._toast_tag(shown[0]) == "pending"


def test_the_pending_link_without_a_console_lists_the_requests(monkeypatch):
    from gigamail import cli
    monkeypatch.setattr(cli, "_forward_to_console", lambda url: False)
    monkeypatch.setattr(cli, "_console_utf8", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    listed = []
    monkeypatch.setattr(cli, "cmd_approvals_list", lambda a: listed.append(a.url) or 0)

    class A:
        url = "gigamail://pending"
    assert cli.cmd_open_url(A) == 0
    assert listed == ["gigamail://pending"]


def test_the_console_status_tells_a_legacy_registration(monkeypatch):
    from gigamail.http_api import notify as notify_api
    monkeypatch.setattr(d, "buttons_off_reason", lambda: "legacy")
    monkeypatch.setattr(d, "actions_supported", lambda: False)
    out = notify_api.notify_status()
    assert out["desktop"]["buttons"] is False and out["desktop"]["buttons_off"] == "legacy"
