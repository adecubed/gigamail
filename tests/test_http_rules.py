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


def test_backend_start_brings_back_a_watcher_with_active_rules(client, monkeypatch):
    """The watcher dies with every update (the installer ends the python
    processes of the install folder); only the Automations button started
    it again, so a rule's mail went unanswered until someone noticed."""
    import subprocess

    from gigamail.http_api import rules as rules_api
    spawned = []

    class FakeProc:
        pid = 4242

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a[0]) or FakeProc())
    # no active rule: nothing to run
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
