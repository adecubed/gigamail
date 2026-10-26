"""A send clicked in the console needs no Windows Hello; any other caller does.

The console token sits in a file every process of the user can read, an
agent with a shell included, so it cannot prove a person clicked. The
console's main process makes a click secret at every launch, keeps it in
memory, hands it to the backend on stdin and adds it only to the requests of
its own windows (http_api/console_click.py).
"""
import importlib
import io

import pytest
from fastapi.testclient import TestClient

from gigamail import consent, policy
from gigamail.http_api import console_click, mail

SECRET = "a" * 64


@pytest.fixture
def client(monkeypatch):
    from gigamail import http_api
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "local-test-token")
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    importlib.reload(http_api)
    console_click.set_secret(SECRET)
    # the user's real setting must not decide the tests: off unless a test turns it on
    monkeypatch.setattr(console_click, "send_requires_hello", lambda: False)
    with TestClient(http_api.app, headers={"X-ADE-Token": "local-test-token"}) as c:
        yield c
    console_click.set_secret("")
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


@pytest.fixture
def provider(monkeypatch):
    sent, outcomes = [], []
    monkeypatch.setattr(mail, "_save_address", lambda addr: None)
    monkeypatch.setattr(mail.mail_router, "send_message", lambda **kw: sent.append(kw) or {"success": True})
    monkeypatch.setattr(policy, "audit",
                        lambda tool, args, outcome, **kw: outcomes.append((tool, outcome, kw.get("detail"))))
    return sent, outcomes


BODY = {"account_id": 1, "to": "mario.rossi@example.com", "subject": "Visit", "body": "hello"}


def test_a_send_clicked_in_the_console_needs_no_os_prompt(client, provider, monkeypatch):
    sent, outcomes = provider

    def no_prompt(reason):
        raise AssertionError("Windows Hello must not be asked for a console click")
    monkeypatch.setattr(consent, "require_human", no_prompt)
    response = client.post("/mail/send", json=BODY, headers={"X-ADE-Human": SECRET})
    assert response.status_code == 200, response.text
    assert len(sent) == 1 and sent[0]["to"] == "mario.rossi@example.com"
    assert outcomes[-1][1] == "executed"
    assert outcomes[-1][2].endswith("(console click)")


@pytest.mark.parametrize("header", [None, "", "b" * 64, SECRET[:-1]])
def test_without_the_click_secret_the_os_prompt_is_still_asked(client, provider, monkeypatch, header):
    """The token alone (an agent, a script reading the token file) or a wrong
    secret: Windows Hello decides, and a refusal sends nothing."""
    sent, _ = provider
    asked = []
    monkeypatch.setattr(consent, "require_human", lambda reason: asked.append(reason) or False)
    monkeypatch.setattr(consent, "last_reason", lambda: "")
    headers = {} if header is None else {"X-ADE-Human": header}
    response = client.post("/mail/send", json=BODY, headers=headers)
    assert response.status_code == 403
    assert len(asked) == 1
    assert sent == []


def test_a_backend_without_a_secret_treats_nothing_as_a_click(client, provider, monkeypatch):
    """Started by hand or by an older console: every send asks the OS."""
    sent, _ = provider
    console_click.set_secret("")
    asked = []
    monkeypatch.setattr(consent, "require_human", lambda reason: asked.append(reason) or False)
    monkeypatch.setattr(consent, "last_reason", lambda: "")
    response = client.post("/mail/send", json=BODY, headers={"X-ADE-Human": SECRET})
    assert response.status_code == 403
    assert asked and sent == []


def test_a_console_click_in_dry_run_still_writes_nothing(client, provider, monkeypatch):
    sent, _ = provider
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    response = client.post("/mail/send", json=BODY, headers={"X-ADE-Human": SECRET})
    assert response.status_code == 200 and response.json()["dryrun"] is True
    assert sent == []


def test_the_console_can_ask_whether_the_backend_knows_its_clicks(client):
    assert client.get("/console/human", headers={"X-ADE-Human": SECRET}).json() == {"known": True}
    assert client.get("/console/human", headers={"X-ADE-Human": "c" * 64}).json() == {"known": False}
    assert client.get("/console/human").json() == {"known": False}


def test_the_secret_is_read_from_stdin_only_when_the_console_sends_one(monkeypatch):
    monkeypatch.setenv(console_click.STDIN_FLAG, "1")
    assert console_click.read_from_stdin(io.StringIO(SECRET + "\n")) == SECRET
    assert console_click.read_from_stdin(io.StringIO("short\n")) == ""      # not a secret
    assert console_click.read_from_stdin(io.StringIO("")) == ""
    monkeypatch.delenv(console_click.STDIN_FLAG)
    # without the flag stdin is never read: a backend started by hand does
    # not wait on the keyboard
    assert console_click.read_from_stdin(io.StringIO(SECRET + "\n")) == ""


# --- the user's choice: keep the OS prompt for console sends too ------------

def test_with_the_option_on_a_console_click_asks_the_os_prompt_too(client, provider, monkeypatch):
    sent, _ = provider
    monkeypatch.setattr(console_click, "send_requires_hello", lambda: True)
    asked = []
    monkeypatch.setattr(consent, "require_human", lambda reason: asked.append(reason) or True)
    response = client.post("/mail/send", json=BODY, headers={"X-ADE-Human": SECRET})
    assert response.status_code == 200, response.text
    assert len(asked) == 1 and len(sent) == 1


def test_only_the_console_window_can_change_the_choice(client, monkeypatch):
    chosen = []
    monkeypatch.setattr(console_click, "set_send_requires_hello", lambda enabled: chosen.append(enabled))
    monkeypatch.setattr(console_click, "send_requires_hello", lambda: bool(chosen and chosen[-1]))
    assert client.post("/console/send-hello", json={"enabled": False}).status_code == 403
    assert client.post("/console/send-hello", json={"enabled": False},
                       headers={"X-ADE-Human": "d" * 64}).status_code == 403
    assert chosen == []
    r = client.post("/console/send-hello", json={"enabled": True}, headers={"X-ADE-Human": SECRET})
    assert r.status_code == 200 and r.json() == {"console_send_hello": True}
    assert chosen == [True]


def test_the_status_reports_the_choice(client, monkeypatch):
    monkeypatch.setattr(console_click, "send_requires_hello", lambda: True)
    assert client.get("/notify/status").json()["console_send_hello"] is True


def test_an_unreadable_choice_keeps_the_os_prompt(monkeypatch):
    from gigamail.core import accounts

    def broken(key, default=""):
        raise RuntimeError("settings database locked")
    monkeypatch.setattr(accounts, "get_setting", broken)
    assert console_click.send_requires_hello() is True


def test_the_choice_is_off_by_default_and_stored(monkeypatch):
    from gigamail.core import accounts
    store = {}
    monkeypatch.setattr(accounts, "get_setting", lambda key, default="": store.get(key, default))
    monkeypatch.setattr(accounts, "set_setting", lambda key, value: store.__setitem__(key, str(value)))
    assert console_click.send_requires_hello() is False
    console_click.set_send_requires_hello(True)
    assert console_click.send_requires_hello() is True
    console_click.set_send_requires_hello(False)
    assert console_click.send_requires_hello() is False


def test_approve_clicked_in_the_console_needs_no_hello(client, monkeypatch, tmp_path):
    """Approve in the agent bar's card: the click secret is a person at the
    console, as for a send. Seen live: the Hello prompt opened behind the
    windows and the button stayed greyed out."""
    policy.set_store(policy.ApprovalStore(str(tmp_path / "a.db")))
    monkeypatch.setattr(consent, "require_human",
                        lambda reason: (_ for _ in ()).throw(AssertionError("no prompt for a console click")))
    rid = policy.store().create("send_mail", {"to": "x@example.com"}, {"subject": "Invito"})
    r = client.post(f"/approvals/{rid}/approve", headers={"X-ADE-Human": SECRET})
    # approved by the click, then carried out at once (dryrun here)
    assert r.status_code == 200 and r.json()["status"] == "executed"
    assert "console click" in (policy.store().get(rid).get("decided_by") or "")
    policy.set_store(None)


def test_approve_without_the_secret_still_meets_the_os_prompt(client, monkeypatch, tmp_path):
    policy.set_store(policy.ApprovalStore(str(tmp_path / "a.db")))
    asked = []
    monkeypatch.setattr(consent, "require_human", lambda reason: asked.append(reason) or False)
    rid = policy.store().create("send_mail", {"to": "x@example.com"}, {"subject": "Invito"})
    assert client.post(f"/approvals/{rid}/approve").status_code == 403
    assert client.post(f"/approvals/{rid}/approve", headers={"X-ADE-Human": "b" * 64}).status_code == 403
    assert len(asked) == 2
    monkeypatch.setattr(console_click, "send_requires_hello", lambda: True)
    assert client.post(f"/approvals/{rid}/approve", headers={"X-ADE-Human": SECRET}).status_code == 403
    assert len(asked) == 3   # the user asked for the prompt on console clicks too
    policy.set_store(None)


def test_the_secret_also_comes_from_the_environment_and_leaves_it(monkeypatch):
    """On Windows the venv launcher did not always pass the stdin line on:
    the console puts the secret in the environment too, and the backend
    removes it at once so the agents it starts do not inherit it."""
    import os
    monkeypatch.setenv(console_click.ENV_NAME, SECRET)
    assert console_click.read_from_env() == SECRET
    assert console_click.ENV_NAME not in os.environ
    monkeypatch.setenv(console_click.ENV_NAME, "short")
    assert console_click.read_from_env() == ""
    assert console_click.ENV_NAME not in os.environ
