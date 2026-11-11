"""Archive sync status per account: recorded by every sync, shown in
Automations, added to search results for the agent, and told to the user
when an account stops syncing.

Before, an account whose sync kept failing (a changed password, a login
refused) only left lines in the watcher log: the agent answered "nothing
arrived" from an archive that had stopped growing days earlier.
"""
import importlib

import pytest

from gigamail.core import archive_health, archivio, archivio_sync

NOW = 1_800_000_000.0
HOUR = 3600.0
ACCOUNTS = [{"id": 1, "name": "Office", "email": "mario.rossi@example.com", "type": "imap"},
            {"id": 2, "name": "Foundation", "email": "info@example.org", "type": "imap"},
            {"id": 9, "name": "Demo", "email": "demo@example.com", "type": "demo"}]


@pytest.fixture()
def st(tmp_path, monkeypatch):
    s = archivio.ArchiveStore(tmp_path / "a.db", tmp_path / "mail")
    archivio.set_store(s)
    from gigamail.core import accounts as core_accounts
    monkeypatch.setattr(core_accounts, "get_accounts", lambda: list(ACCOUNTS))
    yield s
    archivio.set_store(None)


def _row(rows, aid):
    return next(r for r in rows if r["account_id"] == aid)


# -- every sync records its outcome ----------------------------------------

def test_a_sync_that_works_is_recorded(st, monkeypatch):
    monkeypatch.setattr(archivio_sync, "_sync_account", lambda aid, **kw: {"nuovi": 3})
    assert archivio_sync.sincronizza(1)["nuovi"] == 3
    r = st.sync_rows()[1]
    assert r["last_ok_at"] > 0 and r["error"] == ""


def test_a_sync_that_fails_is_recorded_and_still_raises(st, monkeypatch):
    def down(aid, **kw):
        raise OSError("LOGIN failed")
    monkeypatch.setattr(archivio_sync, "_sync_account", down)
    with pytest.raises(OSError):
        archivio_sync.sincronizza(1)
    r = st.sync_rows()[1]
    assert r["error"] == "OSError: LOGIN failed" and r["error_since"] > 0
    assert r["last_ok_at"] == 0


def test_repeated_failures_keep_the_first_one(st):
    st.sync_ok(1, now=NOW - 10 * HOUR)
    st.sync_failed(1, "first", now=NOW - 8 * HOUR)
    st.sync_failed(1, "second", now=NOW - HOUR)
    r = st.sync_rows()[1]
    assert r["error"] == "second" and r["error_since"] == NOW - 8 * HOUR
    st.sync_ok(1, now=NOW)
    r = st.sync_rows()[1]
    assert r["error"] == "" and r["error_since"] == 0 and r["last_ok_at"] == NOW


# -- the status row in Automations ------------------------------------------

def test_status_lists_every_real_account_with_its_count(st):
    st.salva(1, b"Message-ID: <1@example.com>\r\nSubject: a\r\n\r\nhi")
    st.salva(1, b"Message-ID: <2@example.com>\r\nSubject: b\r\n\r\nhi")
    st.sync_ok(1, now=NOW - HOUR)
    rows = archive_health.status(NOW)
    assert [r["account_id"] for r in rows] == [1, 2]          # no demo
    one, two = _row(rows, 1), _row(rows, 2)
    assert one["messages"] == 2 and one["last_ok_at"] == NOW - HOUR
    assert not one["behind"]
    assert two["messages"] == 0 and two["last_ok_at"] is None
    assert not two["behind"]          # never synced on this PC: no alarm


def test_an_account_is_behind_after_hours_without_a_good_sync(st):
    st.sync_ok(1, now=NOW - 7 * HOUR)
    st.sync_failed(1, "LOGIN failed", now=NOW - 6.5 * HOUR)
    one = _row(archive_health.status(NOW), 1)
    assert one["behind"] and one["error"] == "LOGIN failed"


def test_a_failure_only_minutes_old_is_not_behind(st):
    st.sync_ok(1, now=NOW - 0.5 * HOUR)
    st.sync_failed(1, "timeout", now=NOW - 60)
    one = _row(archive_health.status(NOW), 1)
    assert one["error"] and not one["behind"]


# -- the agent is told in the search result ---------------------------------

def test_no_warning_while_the_archive_is_fresh(st):
    st.sync_ok(1, now=NOW - HOUR)
    assert archive_health.warning_for(1, NOW) is None
    assert archive_health.warning_for(2, NOW) is None       # never synced


def test_the_warning_says_how_old_and_why(st):
    st.sync_ok(1, now=NOW - 30 * HOUR)
    st.sync_failed(1, "LOGIN failed", now=NOW - 29 * HOUR)
    w = archive_health.warning_for(1, NOW)
    assert "30 hours ago" in w and "LOGIN failed" in w
    assert "nothing arrived" in w


def test_stale_without_an_error_points_at_the_watcher(st):
    st.sync_ok(1, now=NOW - 3 * 24 * HOUR)
    w = archive_health.warning_for(1, NOW)
    assert "3 days ago" in w and "watcher may not be running" in w


def test_search_mail_carries_the_warning(st, monkeypatch):
    from gigamail import server as srv
    from gigamail.core import mail_router
    monkeypatch.setattr(srv.core_accounts, "get_active_account", lambda: {"id": 1})
    monkeypatch.setattr(mail_router, "search_messages", lambda **kw: [])
    assert "archive_warning" not in srv.search_mail(query="anything")
    st.sync_ok(1, now=1.0)
    st.sync_failed(1, "LOGIN failed", now=2.0)
    r = srv.search_mail(query="anything")
    assert "LOGIN failed" in r["archive_warning"]


# -- the user is told once, and told when it is back ------------------------

def test_behind_is_told_once_then_back_once(st):
    st.sync_ok(1, now=NOW - 7 * HOUR)
    st.sync_failed(1, "LOGIN failed", now=NOW - 6.5 * HOUR)
    due = archive_health.alerts_due(NOW)
    assert [(r["account_id"], k) for r, k in due] == [(1, "behind")]
    assert archive_health.alerts_due(NOW + 60) == []
    st.sync_failed(1, "LOGIN failed", now=NOW + 120)
    assert archive_health.alerts_due(NOW + 180) == []
    st.sync_ok(1, now=NOW + 240)
    due = archive_health.alerts_due(NOW + 300)
    assert [(r["account_id"], k) for r, k in due] == [(1, "back")]
    assert archive_health.alerts_due(NOW + 360) == []


def test_stale_without_an_error_is_not_alerted(st):
    # The PC was off for a weekend: the next sync works, nothing to say.
    st.sync_ok(1, now=NOW - 60 * HOUR)
    assert archive_health.alerts_due(NOW) == []


def test_a_first_failure_after_a_weekend_waits_before_alerting(st):
    # Monday morning: the last good sync is from Friday and the first tick
    # fails because the network is not up yet. No alert, and no "back"
    # right after it.
    st.sync_ok(1, now=NOW - 60 * HOUR)
    st.sync_failed(1, "getaddrinfo failed", now=NOW)
    assert archive_health.alerts_due(NOW + 60) == []
    st.sync_ok(1, now=NOW + 120)
    assert archive_health.alerts_due(NOW + 180) == []


def test_after_a_weekend_an_account_still_failing_an_hour_later_is_alerted(st):
    st.sync_ok(1, now=NOW - 60 * HOUR)
    st.sync_failed(1, "LOGIN failed", now=NOW)
    st.sync_failed(1, "LOGIN failed", now=NOW + 0.5 * HOUR)
    assert archive_health.alerts_due(NOW + 0.5 * HOUR) == []
    st.sync_failed(1, "LOGIN failed", now=NOW + HOUR)
    due = archive_health.alerts_due(NOW + HOUR)
    assert [(r["account_id"], k) for r, k in due] == [(1, "behind")]


def test_the_watcher_sends_the_alert_on_telegram_and_desktop(st, monkeypatch):
    from gigamail.core import desktop_notify, telegram_channel
    from gigamail.watcher import runner

    sent, shown = [], []

    class Tg:
        def send(self, text):
            sent.append(text)
    monkeypatch.setattr(telegram_channel, "channel", lambda: Tg())
    monkeypatch.setattr(desktop_notify, "notify",
                        lambda title, body, **kw: shown.append(body))
    st.sync_ok(1, now=1.0)
    st.sync_failed(1, "LOGIN failed", now=2.0)
    w = runner.Watcher.__new__(runner.Watcher)
    w.verbose = False
    assert w.archive_sync_alerts() == 1
    assert len(sent) == 1 and len(shown) == 1
    assert "mario.rossi@example.com" in sent[0] and "LOGIN failed" in sent[0]
    assert w.archive_sync_alerts() == 0


# -- the console reads it from the watcher status ---------------------------

def test_watch_status_carries_the_sync_rows(st, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from gigamail import policy
    from gigamail.core import rules as rules_mod
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "t-sync")
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    from gigamail import http_api
    importlib.reload(http_api)
    st.sync_ok(1)
    try:
        with TestClient(http_api.app) as c:
            body = c.get("/watch/status", headers={"X-ADE-Token": "t-sync"}).json()
    finally:
        rules_mod.set_store(None)
        policy.set_store(None)
        monkeypatch.delenv("ADE_CONSOLE_TOKEN")
        importlib.reload(http_api)
    rows = {r["account_id"]: r for r in body["archive_sync"]}
    assert set(rows) == {1, 2} and rows[1]["last_ok_at"] and not rows[1]["error"]
