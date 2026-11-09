"""Console API 0.2.1: regole, watcher, notifiche. Creare/riattivare una
regola passa da consent.require_human anche dal backend (il token della
console non basta); pausa/elimina sono liberi."""
import importlib

import pytest
from fastapi.testclient import TestClient

from gigamail import policy
from gigamail.core import rules as rules_mod

H = {"X-ADE-Token": "t-rules"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "t-rules")
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    from gigamail import http_api
    importlib.reload(http_api)
    from gigamail.http_api import rules as rules_api
    rules_api._SPAWNED.clear()
    rules_api._SPAWNED_AT.clear()
    with TestClient(http_api.app) as c:
        yield c
    rules_mod.set_store(None)
    policy.set_store(None)
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


BODY = {"account_id": 1, "trigger_kind": "senders",
        "trigger_values": ["Cliente@Fidato.it"], "reply_style": "cordiale",
        "doc_paths": [], "mode": "semi"}


def test_create_senza_consenso_403(client):
    # conftest: GIGAMAIL_CONSENT_BACKEND=deny
    r = client.post("/rules", json=BODY, headers=H)
    assert r.status_code == 403
    assert client.get("/rules", headers=H).json() == []


def test_create_con_consenso_dryrun(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    r = client.post("/rules", json=BODY, headers=H)
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["trigger_values"] == ["cliente@fidato.it"]  # normalizzato
    assert rule["state"] == "active" and rule["sent_today"] == 0
    assert rule["created_by"].startswith("console")


def test_pause_libera_resume_con_hello(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    rid = client.post("/rules", json=BODY, headers=H).json()["rule_id"]
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert client.post(f"/rules/{rid}/pause", headers=H).json()["state"] == "paused"
    assert client.post(f"/rules/{rid}/resume", headers=H).status_code == 403
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    assert client.post(f"/rules/{rid}/resume", headers=H).json()["state"] == "active"
    assert client.delete(f"/rules/{rid}", headers=H).json()["success"]
    assert client.get("/rules", headers=H).json() == []


def test_renew_needs_hello_and_moves_the_expiry(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    rid = client.post("/rules", json=dict(BODY, expiry_days=30), headers=H).json()["rule_id"]
    with rules_mod.store()._conn() as conn:
        conn.execute("UPDATE rules SET expires_at=1 WHERE rule_id=?", (rid,))
    assert client.get("/rules", headers=H).json()[0]["state"] == "expired"
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert client.post(f"/rules/{rid}/renew", headers=H).status_code == 403
    assert client.get("/rules", headers=H).json()[0]["state"] == "expired"
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    renewed = client.post(f"/rules/{rid}/renew", headers=H).json()
    assert renewed["state"] == "active" and not renewed["expiring"]
    assert client.post("/rules/rule_missing/renew", headers=H).status_code == 404


def test_update_needs_hello_and_changes_the_rule_in_place(client, monkeypatch, tmp_path):
    """Edit on a rule card: the instruction (and the rest) change in
    place behind Hello; the rule keeps its id, state and expiry. A rule
    whose prompt hard-coded the wrong floor plans is corrected without
    deleting it."""
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    rule = client.post("/rules", json=BODY, headers=H).json()
    rid = rule["rule_id"]
    doc = tmp_path / "listino.txt"
    doc.write_text("prezzi")
    change = {"reply_style": "attach the plans the customer asks for",
              "daily_cap": 3, "doc_paths": [str(doc)], "cc": ["ufficio@example.com "],
              "trigger_values": ["Cliente@Fidato.it", "Nuovo@Cliente.it"]}
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "deny")
    assert client.put(f"/rules/{rid}", json=change, headers=H).status_code == 403
    assert client.get("/rules", headers=H).json()[0]["reply_style"] == "cordiale"
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    updated = client.put(f"/rules/{rid}", json=change, headers=H).json()
    assert updated["rule_id"] == rid and updated["state"] == "active"
    assert updated["reply_style"] == change["reply_style"]
    assert updated["daily_cap"] == 3
    assert updated["doc_paths"] == [str(doc)]
    assert updated["cc"] == ["ufficio@example.com"]
    assert updated["trigger_values"] == ["cliente@fidato.it", "nuovo@cliente.it"]
    assert updated["expires_at"] == rule["expires_at"]
    # only what is sent changes
    again = client.put(f"/rules/{rid}", json={"cooldown_hours": 1}, headers=H).json()
    assert again["reply_style"] == change["reply_style"] and again["cooldown_hours"] == 1
    # refusals: nothing, a missing document, an attachment the identity
    # does not know, an unknown rule
    assert client.put(f"/rules/{rid}", json={}, headers=H).status_code == 400
    assert client.put(f"/rules/{rid}", json={"doc_paths": ["C:/nonexistent/x.pdf"]}, headers=H).status_code == 400
    assert client.put(f"/rules/{rid}", json={"attachments": ["plan-that-does-not-exist.pdf"]}, headers=H).status_code == 400
    assert client.put(f"/rules/{rid}", json={"trigger_values": [" "]}, headers=H).status_code == 400
    assert client.put("/rules/rule_missing", json={"daily_cap": 1}, headers=H).status_code == 404


def test_validazioni(client, monkeypatch):
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    bad = dict(BODY, doc_paths=["C:/nonexistent/listino.pdf"])
    assert client.post("/rules", json=bad, headers=H).status_code == 400
    assert client.post("/rules", json=dict(BODY, mode="yolo"), headers=H).status_code == 400
    assert client.post("/rules", json=dict(BODY, trigger_values=[" "]), headers=H).status_code == 400


def test_watch_status_senza_processo(client):
    st = client.get("/watch/status", headers=H).json()
    assert st["running"] is False and st["pid"] is None
    assert client.get("/watch/log", headers=H).json() == []


def test_notify_status_forma(client):
    st = client.get("/notify/status", headers=H).json()
    assert set(st) >= {"agent", "consent_backend", "desktop", "telegram", "lang"}
    assert st["telegram"]["configured"] is False


def _guard_sees_no_live_watcher(monkeypatch, rules_api):
    monkeypatch.setattr(rules_api, "_watch_state",
                        lambda: {"running": False, "pid": 9001, "active_rules": 1, "code_stamp": ""})


class _Running:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def test_a_hung_watcher_is_ended_before_another_starts(client, monkeypatch):
    """A watcher stuck inside a tick stops beating and looks dead, but never
    leaves: the guard started a new one every few minutes and seven worked
    the same mail."""
    from gigamail.http_api import rules as rules_api
    _guard_sees_no_live_watcher(monkeypatch, rules_api)
    stopped, spawned = [], []
    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: stopped.append(pid))
    next_pid = iter([9002, 9003])

    def spawn(interval):
        pid = next(next_pid)
        spawned.append(pid)
        rules_api._SPAWNED[pid] = _Running(pid)
        return pid

    monkeypatch.setattr(rules_api, "_spawn_watch", spawn)
    rules_api._SPAWNED[9001] = _Running(9001)
    assert rules_api.watch_autostart() == 9002
    assert stopped == [9001] and list(rules_api._SPAWNED) == [9002]
    assert rules_api.watch_autostart() == 9003
    assert stopped == [9001, 9002] and list(rules_api._SPAWNED) == [9003]


def test_a_watcher_just_started_is_given_time_to_beat(client, monkeypatch):
    """It has no heartbeat yet: taken for hung, it was ended every eleven
    seconds and no watcher ever ran."""
    import time

    from gigamail.http_api import rules as rules_api
    _guard_sees_no_live_watcher(monkeypatch, rules_api)
    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: 1 / 0)
    monkeypatch.setattr(rules_api, "_spawn_watch", lambda interval: 1 / 0)
    rules_api._SPAWNED[9001] = _Running(9001)
    rules_api._SPAWNED_AT[9001] = time.time()
    assert rules_api.watch_autostart() is None
    started = client.post("/watch/start", headers=H).json()
    assert started["running"] is True and started["pid"] == 9001
    assert list(rules_api._SPAWNED) == [9001]


def test_a_new_watcher_is_ended_once_its_time_is_up(client, monkeypatch):
    import time

    from gigamail.http_api import rules as rules_api
    _guard_sees_no_live_watcher(monkeypatch, rules_api)
    stopped = []
    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: stopped.append(pid))
    monkeypatch.setattr(rules_api, "_spawn_watch", lambda interval: 9002)
    rules_api._SPAWNED[9001] = _Running(9001)
    rules_api._SPAWNED_AT[9001] = time.time() - rules_api.WATCH_START_GRACE_SECONDS - 1
    assert rules_api.watch_autostart() == 9002
    assert stopped == [9001]


def test_no_new_watcher_when_the_hung_one_cannot_be_ended(client, monkeypatch):
    from gigamail.http_api import rules as rules_api
    _guard_sees_no_live_watcher(monkeypatch, rules_api)

    def refuse(pid):
        raise OSError("access denied")

    monkeypatch.setattr(rules_api, "_stop_watch_process", refuse)
    monkeypatch.setattr(rules_api, "_spawn_watch", lambda interval: 1 / 0)
    rules_api._SPAWNED[9001] = _Running(9001)
    assert rules_api.watch_autostart() is None
    assert list(rules_api._SPAWNED) == [9001]


def test_a_finished_watcher_is_forgotten_not_killed(client, monkeypatch):
    """Windows reuses pids: an exited watcher must never be killed by pid."""
    from gigamail.http_api import rules as rules_api

    class Exited:
        def poll(self):
            return 0

    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: 1 / 0)
    rules_api._SPAWNED[9001] = Exited()
    assert rules_api._stop_left_behind() is True
    assert rules_api._SPAWNED == {}


def test_stop_ends_every_watcher_this_backend_started(client, monkeypatch):
    from gigamail.http_api import rules as rules_api
    stopped = []
    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: stopped.append(pid))
    monkeypatch.setattr(rules_api, "_pid_alive", lambda pid: True)
    rules_mod.store().kv_set("watch_pid", "9002")
    rules_api._SPAWNED.update({9001: _Running(9001), 9002: _Running(9002)})
    assert client.post("/watch/stop", headers=H).status_code == 200
    assert sorted(stopped) == [9001, 9002] and rules_api._SPAWNED == {}


def test_backend_start_brings_back_a_watcher_with_active_rules(client, monkeypatch):
    """The watcher dies with every update (the installer ends the python
    processes of the install folder); only the Automations button started
    it again, so a rule's mail went unanswered until someone noticed."""
    import subprocess

    from gigamail.http_api import rules as rules_api
    spawned = []

    class FakeProc:
        pid = 4242

        def poll(self):
            return 0   # exited: nothing for the guard to end

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a[0]) or FakeProc())
    monkeypatch.setattr(rules_api, "_archive_accounts", lambda: 0)
    # no active rule and no account to archive: nothing to run
    assert rules_api.watch_autostart() is None and spawned == []

    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    assert client.post("/rules", json=BODY, headers=H).status_code == 200
    rules_mod.store().kv_set("watch_interval", "45")
    assert rules_api.watch_autostart() == 4242
    assert spawned[0][-4:] == ["watch", "--verbose", "--interval", "45"]
    assert rules_mod.store().kv_get("watch_pid", "0") == "4242"

    # a watcher that is alive, ticking and on the current code is left alone
    from gigamail.core.code_stamp import code_stamp
    monkeypatch.setattr(rules_api, "_watch_state",
                        lambda: {"running": True, "pid": 4242, "active_rules": 1,
                                 "code_stamp": code_stamp()})
    assert rules_api.watch_autostart() is None and len(spawned) == 1
    # one running old code (an update, a git pull) is stopped and started again
    stopped = []
    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: stopped.append(pid))
    monkeypatch.setattr(rules_api, "_watch_state",
                        lambda: {"running": True, "pid": 4242, "active_rules": 1,
                                 "code_stamp": "old-1"})
    assert rules_api.watch_autostart() == 4242
    assert stopped == [4242] and len(spawned) == 2
    # a watcher from before the stamp existed is not restarted on a guess
    monkeypatch.setattr(rules_api, "_watch_state",
                        lambda: {"running": True, "pid": 4242, "active_rules": 1, "code_stamp": ""})
    assert rules_api.watch_autostart() is None and len(spawned) == 2


def test_stop_holds_until_start_even_with_the_guard(client, monkeypatch):
    """Stop in Automations zeroed pid and heartbeat; the guard, a minute
    later, saw active rules and no watcher and started one again. An
    explicit stop is a choice: it holds until Start, or until a watcher
    is started by hand."""
    import subprocess

    from gigamail.http_api import rules as rules_api
    from gigamail.watcher import process_state
    spawned = []

    class P:
        pid = 777

        def poll(self):
            return 0   # exited: nothing for the guard to end

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a[0]) or P())
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    assert client.post("/rules", json=BODY, headers=H).status_code == 200
    assert client.post("/watch/stop", headers=H).status_code == 200
    assert rules_api.watch_autostart() is None and spawned == []
    # Start clears it: the guard may act again afterwards
    assert client.post("/watch/start", headers=H).status_code == 200
    assert len(spawned) == 1
    rules_mod.store().kv_set("watch_pid", "0")
    assert rules_api.watch_autostart() == 777 and len(spawned) == 2
    # a heartbeat never lifts a stop (a watcher the guard started would
    # undo the user's choice); `gigamail watch` by hand does
    client.post("/watch/stop", headers=H)
    assert rules_mod.store().kv_get(rules_api.USER_STOPPED_KEY, "0") == "1"
    process_state.heartbeat(60, force=True)
    assert rules_mod.store().kv_get(rules_api.USER_STOPPED_KEY, "0") == "1"
    from gigamail import cli
    from gigamail import watcher as watcher_mod
    monkeypatch.setattr(watcher_mod.Watcher, "run", lambda self, once=False: None)

    class A:
        interval, verbose, once = 60, False, True
    cli.cmd_watch(A)
    assert rules_mod.store().kv_get(rules_api.USER_STOPPED_KEY, "0") == "0"


def test_stop_and_the_guard_cannot_overlap(client, monkeypatch):
    """The flag was written after the kill: a guard that woke up in
    between saw a dead watcher and started one. The flag now goes first,
    under the lock the guard takes: a guard racing the stop waits, then
    reads the flag and starts nothing."""
    import subprocess
    import threading

    from gigamail.http_api import rules as rules_api
    spawned = []

    class P:
        pid = 778

        def poll(self):
            return 0   # exited: nothing for the guard to end

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a[0]) or P())
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    assert client.post("/rules", json=BODY, headers=H).status_code == 200
    rules_mod.store().kv_set("watch_pid", "4242")
    monkeypatch.setattr(rules_api, "_pid_alive", lambda pid: pid == 4242)
    guard_result = []

    def slow_kill(pid, wait=10.0):
        # the guard fires while the stop is still killing: it must block
        t = threading.Thread(target=lambda: guard_result.append(rules_api.watch_autostart()))
        t.start()
        t.join(0.3)
        assert t.is_alive(), "the guard must wait for the stop"
        monkeypatch.setattr(rules_api, "_pid_alive", lambda p: False)
        slow_kill.thread = t

    monkeypatch.setattr(rules_api, "_stop_watch_process", slow_kill)
    assert client.post("/watch/stop", headers=H).status_code == 200
    slow_kill.thread.join(2)
    assert guard_result == [None] and spawned == []


def _fake_spawn(monkeypatch, pid=4343):
    import subprocess
    spawned = []

    class P:
        def poll(self):
            return 0   # exited: nothing for the guard to end
    P.pid = pid
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a[0]) or P())
    return spawned


def test_the_archive_alone_keeps_the_watcher_running(client, monkeypatch):
    """The watcher also fills the local archive that search and the agents
    read. With no rules the guard left it stopped after a restart or an
    update, and the archive stopped growing without a word."""
    from gigamail.core import accounts as core_accounts
    from gigamail.http_api import rules as rules_api
    spawned = _fake_spawn(monkeypatch)
    monkeypatch.setattr(core_accounts, "get_accounts",
                        lambda: [{"id": 1, "type": "imap"}, {"id": 2, "type": "demo"}])
    assert rules_api._watch_state()["archive_accounts"] == 1
    assert rules_api.watch_autostart() == 4343 and len(spawned) == 1
    # an explicit Stop still wins
    rules_mod.store().kv_set("watch_pid", "0")
    assert client.post("/watch/stop", headers=H).status_code == 200
    assert rules_api.watch_autostart() is None and len(spawned) == 1


def test_a_demo_account_alone_starts_nothing(client, monkeypatch):
    from gigamail.core import accounts as core_accounts
    from gigamail.http_api import rules as rules_api
    spawned = _fake_spawn(monkeypatch)
    monkeypatch.setattr(core_accounts, "get_accounts", lambda: [{"id": 1, "type": "demo"}])
    assert rules_api.watch_autostart() is None and spawned == []


def test_new_code_restarts_an_archive_only_watcher(client, monkeypatch):
    from gigamail.http_api import rules as rules_api
    spawned = _fake_spawn(monkeypatch)
    stopped = []
    monkeypatch.setattr(rules_api, "_stop_watch_process", lambda pid: stopped.append(pid))
    monkeypatch.setattr(rules_api, "_watch_state",
                        lambda: {"running": True, "pid": 4242, "active_rules": 0,
                                 "archive_accounts": 1, "code_stamp": "old-1"})
    assert rules_api.watch_autostart() == 4343
    assert stopped == [4242] and len(spawned) == 1
