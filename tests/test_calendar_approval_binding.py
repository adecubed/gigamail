"""Calendar approvals keep the provider and identity shown before approval."""
import json

import pytest

from ade_mail_agent import policy, server
from ade_mail_agent.core import calendar_router, google_calendar, ms_calendar


@pytest.fixture
def calendar_context(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    state = {"provider": "microsoft", "microsoft": 1, "google": "first@gmail.test"}
    microsoft = {
        aid: {"id": aid, "type": "microsoft", "email": f"ms{aid}@example.test",
              "data": {"token_cache": "secret-ms-token"}}
        for aid in (1, 2)}
    google = {
        email: {"email": email, "data": {"refresh_token": "secret-google-token"}}
        for email in ("first@gmail.test", "second@gmail.test")}
    monkeypatch.setattr(calendar_router, "provider", lambda: state["provider"])
    monkeypatch.setattr(calendar_router.core_accounts, "get_calendar_primary",
                        lambda: state["microsoft"])
    monkeypatch.setattr(calendar_router.core_accounts, "get_account_by_id", microsoft.get)
    monkeypatch.setattr(calendar_router.core_accounts, "get_google_identity",
                        lambda email=None: google.get(email or state["google"]))
    monkeypatch.setattr(policy, "notify_approval_requested", lambda *a, **kw: None)
    selected, calls = [], []
    monkeypatch.setattr(calendar_router, "_select_microsoft",
                        lambda account: selected.append(account["email"]))

    def microsoft_call(**args):
        calls.append(("microsoft", selected[-1], args))
        return {"id": "created"} if "subject" in args else True

    def google_call(**args):
        calls.append(("google", args["email"], args))
        return {"id": "created"} if "subject" in args else True

    for operation in ("create_event", "delete_event"):
        monkeypatch.setattr(ms_calendar, operation, microsoft_call)
        monkeypatch.setattr(google_calendar, operation, google_call)
    yield state, microsoft, google, calls
    policy.set_store(None)


_TOOLS = [
    ("create_event", {"subject": "Approved meeting", "start": "2026-10-01T10:00",
                      "end": "2026-10-01T11:00", "body": "", "location": ""}),
    ("delete_event", {"event_id": "approved-event"}),
]


@pytest.mark.parametrize("operation,args", _TOOLS)
@pytest.mark.parametrize("provider", ["microsoft", "google"])
@pytest.mark.parametrize("switch_provider", [False, True])
def test_calendar_approval_cannot_switch_destination(
        calendar_context, monkeypatch, operation, args, provider, switch_provider):
    state, _microsoft, _google, calls = calendar_context
    state["provider"] = provider
    function = getattr(server, operation)
    pending = function(**args)
    record = policy.store().get(pending["request_id"])
    target = record["args"]["destination"]
    expected_email = "ms1@example.test" if provider == "microsoft" else "first@gmail.test"
    assert target["provider"] == provider and target["email"] == expected_email
    assert pending["preview"]["destination"] == target
    assert "secret-" not in json.dumps(record["args"])

    state["microsoft"] = 2
    state["google"] = "second@gmail.test"
    if switch_provider:
        state["provider"] = "google" if provider == "microsoft" else "microsoft"
    monkeypatch.setattr(calendar_router, "capture_destination",
                        lambda: pytest.fail("Execution must use the approved destination"))
    policy.store().approve(pending["request_id"])
    changed = dict(args)
    changed["subject" if operation == "create_event" else "event_id"] = "unapproved-change"
    function(**changed, request_id=pending["request_id"])
    assert len(calls) == 1
    assert calls[0][:2] == (provider, expected_email)
    for name, value in args.items():
        assert calls[0][2][name] == value


@pytest.mark.parametrize("operation,args", _TOOLS)
def test_legacy_calendar_approval_without_destination_fails_closed(
        calendar_context, monkeypatch, operation, args):
    *_context, calls = calendar_context
    request_id = policy.store().create(operation, args, {})
    policy.store().approve(request_id)
    monkeypatch.setattr(calendar_router, "capture_destination",
                        lambda: pytest.fail("Legacy approval must not capture a new destination"))
    with pytest.raises(ValueError, match="destinazione calendario fissata"):
        getattr(server, operation)(**args, request_id=request_id)
    assert calls == []


@pytest.mark.parametrize("provider", ["microsoft", "google"])
def test_removed_approved_identity_does_not_fall_back(calendar_context, provider):
    state, microsoft, google, calls = calendar_context
    state["provider"] = provider
    pending = server.delete_event("approved-event")
    if provider == "microsoft":
        del microsoft[1]
        state["microsoft"] = 2
    else:
        del google["first@gmail.test"]
        state["google"] = "second@gmail.test"
    policy.store().approve(pending["request_id"])
    with pytest.raises(ValueError, match="non piu disponibile"):
        server.delete_event("approved-event", request_id=pending["request_id"])
    assert calls == []
