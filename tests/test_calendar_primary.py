"""Il calendario Microsoft non eredita l'identita' dell'ultima mail."""
from types import SimpleNamespace

import pytest

from ade_mail_agent.core import auth, calendar_router, mail_router, ms_calendar


@pytest.fixture(autouse=True)
def auth_context():
    auth.clear_current_account()
    yield
    auth.clear_current_account()


@pytest.mark.parametrize("operation", ["read", "create"])
def test_primary_calendar_overrides_last_mail_account(monkeypatch, operation):
    primary = {"id": 1, "email": "calendar@example.com", "type": "microsoft",
               "data": {"token_cache": "primary-cache"}}
    mail_account = {"id": 2, "email": "mail@example.com", "type": "microsoft"}
    accounts = calendar_router.core_accounts
    monkeypatch.setattr(accounts, "get_active_account", lambda: mail_account)
    monkeypatch.setattr(accounts, "get_calendar_provider", lambda: "microsoft")
    monkeypatch.setattr(accounts, "get_calendar_primary", lambda: 1)
    monkeypatch.setattr(accounts, "get_account_by_id",
                        lambda aid: {1: primary, 2: mail_account}.get(aid))
    fake_app = SimpleNamespace(
        get_accounts=lambda: [{"username": a["email"]}
                              for a in (mail_account, primary)],
        acquire_token_silent=lambda scopes, account: {
            "access_token": "token-" + account["username"]})
    monkeypatch.setattr(auth, "_get_app",
                        lambda: (fake_app, SimpleNamespace(has_state_changed=False)))
    headers = []

    def request(url, **kwargs):
        headers.append(kwargs["headers"])
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"value": [], "id": "created"})

    monkeypatch.setattr(ms_calendar.requests, "get", request)
    monkeypatch.setattr(ms_calendar.requests, "post", request)
    mail_router._account(2)
    assert auth.get_token() == "token-mail@example.com"
    if operation == "read":
        calendar_router.get_events()
    else:
        calendar_router.create_event("Meeting", "2026-10-01T09:00", "2026-10-01T10:00")
    assert headers[0]["Authorization"] == "Bearer token-calendar@example.com"


@pytest.mark.parametrize("primary_id, account", [
    (None, None),
    (99, None),
    (2, {"id": 2, "type": "imap", "email": "imap@example.com"}),
    (1, {"id": 1, "type": "microsoft", "email": ""}),
])
def test_invalid_primary_does_not_use_last_mail_identity(monkeypatch, primary_id, account):
    monkeypatch.setattr(calendar_router, "provider", lambda: "microsoft")
    monkeypatch.setattr(calendar_router.core_accounts, "get_calendar_primary",
                        lambda: primary_id)
    monkeypatch.setattr(calendar_router.core_accounts, "get_account_by_id",
                        lambda aid: account)
    called = []
    monkeypatch.setattr(ms_calendar, "get_events", lambda **kw: called.append(kw))
    auth.set_current_account("last-mail@example.com", 3)
    with pytest.raises(auth.AuthRequired, match="calendario primario"):
        calendar_router.get_events()
    assert called == []


@pytest.mark.parametrize("provider", ["google", "demo"])
def test_non_microsoft_provider_does_not_resolve_microsoft_primary(monkeypatch, provider):
    monkeypatch.setattr(calendar_router, "provider", lambda: provider)

    def forbidden():
        raise AssertionError("Microsoft primary must not be consulted")

    monkeypatch.setattr(calendar_router.core_accounts, "get_calendar_primary", forbidden)
    backend = calendar_router._backend()
    if provider == "demo":
        assert backend is calendar_router._CalendarioDemo
    else:
        assert backend.__name__.endswith("google_calendar")


def test_bound_action_preserves_microsoft_primary_during_confirmation(monkeypatch):
    primary = [1]
    accounts = {1: {"id": 1, "type": "microsoft", "email": "first@example.com"},
                2: {"id": 2, "type": "microsoft", "email": "second@example.com"}}
    monkeypatch.setattr(calendar_router, "provider", lambda: "microsoft")
    monkeypatch.setattr(calendar_router.core_accounts, "get_calendar_primary", lambda: primary[0])
    monkeypatch.setattr(calendar_router.core_accounts, "get_account_by_id", accounts.get)
    selected = []
    monkeypatch.setattr(auth, "set_current_account", lambda email, *a: selected.append(email))
    monkeypatch.setattr(ms_calendar, "create_event", lambda **kw: {"id": "created"})
    execute = calendar_router.bind_action("create_event")
    primary[0] = 2
    assert execute(subject="meeting", start="2026-10-01T10:00", end="2026-10-01T11:00")["id"] == "created"
    assert selected == ["first@example.com"]


def test_bound_action_preserves_google_identity_during_confirmation(monkeypatch):
    from ade_mail_agent.core import google_calendar
    email = ["first@example.com"]
    monkeypatch.setattr(calendar_router, "provider", lambda: "google")
    monkeypatch.setattr(calendar_router.core_accounts, "get_google_identity",
                        lambda selected=None: {"email": selected or email[0]})
    selected = []
    monkeypatch.setattr(google_calendar, "delete_event", lambda **kw: selected.append(kw) or True)
    execute = calendar_router.bind_action("delete_event")
    email[0] = "second@example.com"
    assert execute(event_id="event") is True
    assert selected == [{"event_id": "event", "email": "first@example.com",
                         "calendar_id": "primary"}]
