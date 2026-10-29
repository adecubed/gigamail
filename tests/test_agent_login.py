"""Claude Code without a valid login: the bar says so and signs in again.

Seen live (26/10): the claude.ai session expired and could not be
refreshed, the CLI wiped its tokens, and the next request went out on the
user's ANTHROPIC_API_KEY, whose account had no credit. The bar showed two
raw errors and nobody could tell that one sign-in fixed both."""
import json
import sys
import textwrap
import time

import pytest

from gigamail import agent_bridge

PY = sys.executable


def _as_claude(monkeypatch, script: str):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps([PY, "-c", script, "{prompt}"]))
    monkeypatch.setattr(agent_bridge, "_agent_of", lambda cfg: "claude")


def _fails_with(text: str) -> str:
    return f"import sys; sys.stderr.write({text!r}); sys.exit(1)"


def _no_login(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nowhere"))


def test_expired_oauth_session_asks_to_sign_in(tmp_path, monkeypatch):
    _no_login(tmp_path, monkeypatch)
    _as_claude(monkeypatch, _fails_with(
        "Failed to authenticate: OAuth session expired and could not be refreshed"))
    with pytest.raises(agent_bridge.AgentLoginRequired) as exc:
        agent_bridge.run("x")
    assert "OAuth session expired" in str(exc.value)


def test_not_logged_in_on_stdout_asks_to_sign_in(tmp_path, monkeypatch):
    _no_login(tmp_path, monkeypatch)
    _as_claude(monkeypatch, "print('Not logged in · Please run /login')")
    with pytest.raises(agent_bridge.AgentLoginRequired):
        agent_bridge.run("x")


def test_no_credit_on_the_api_key_without_a_login_asks_to_sign_in(tmp_path, monkeypatch):
    """Without a claude.ai login the CLI falls back to the API key: the fix
    is the sign-in, not topping up an account the user may not know about."""
    _no_login(tmp_path, monkeypatch)
    _as_claude(monkeypatch, _fails_with("Credit balance is too low"))
    with pytest.raises(agent_bridge.AgentLoginRequired):
        agent_bridge.run("x")


def test_no_credit_with_a_login_is_not_a_sign_in_problem(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "claude-config"
    cfg_dir.mkdir()
    (cfg_dir / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "yes"}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg_dir))
    _as_claude(monkeypatch, _fails_with("Credit balance is too low"))
    with pytest.raises(agent_bridge.AgentUnavailable) as exc:
        agent_bridge.run("x")
    assert not isinstance(exc.value, agent_bridge.AgentLoginRequired)


def test_a_custom_agent_never_gets_the_claude_sign_in(tmp_path, monkeypatch):
    _no_login(tmp_path, monkeypatch)
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", _fails_with("OAuth session expired"), "{prompt}"]))
    with pytest.raises(agent_bridge.AgentUnavailable) as exc:
        agent_bridge.run("x")
    assert not isinstance(exc.value, agent_bridge.AgentLoginRequired)


# --- the sign-in itself -----------------------------------------------------

_FAKE_CLAUDE = textwrap.dedent("""
    import json, os, sys
    flag = os.environ["FAKE_CLAUDE_FLAG"]
    args = sys.argv[1:]
    if args[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": os.path.exists(flag)}))
        sys.exit(0)
    assert args == ["auth", "login", "--claudeai"], args
    print("Opening browser to sign in...")
    print("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&state=abc")
    sys.stdout.write("Paste code here if prompted >")
    sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if code != "good-code":
        sys.exit(1)
    open(flag, "w").close()
""")


@pytest.fixture()
def fake_claude(tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(_FAKE_CLAUDE, encoding="utf-8")
    flag = tmp_path / "logged-in"
    monkeypatch.setenv("FAKE_CLAUDE_FLAG", str(flag))
    monkeypatch.setattr(agent_bridge, "_claude_cmd", lambda *args: [PY, str(script), *args])
    yield flag
    agent_bridge.claude_login_stop()


def _until(cond, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end:
        value = cond()
        if value:
            return value
        time.sleep(0.05)
    return cond()


def test_status_reads_the_cli(fake_claude):
    assert agent_bridge.claude_login_state()["logged_in"] is False
    fake_claude.touch()
    assert agent_bridge.claude_login_state()["logged_in"] is True


def test_sign_in_with_the_pasted_code(fake_claude):
    st = agent_bridge.claude_login_start()
    assert st["pending"] is True
    # the address to open by hand, when the browser did not open
    url = _until(lambda: agent_bridge.claude_login_state()["url"])
    assert url == "https://claude.com/cai/oauth/authorize?code=true&state=abc"
    # a second press while it waits does not start a second sign-in
    assert agent_bridge.claude_login_start()["pending"] is True

    agent_bridge.claude_login_code("good-code")
    st = _until(lambda: (lambda s: s if not s["pending"] else None)(agent_bridge.claude_login_state()))
    assert st["logged_in"] is True


def test_a_wrong_code_leaves_the_user_signed_out(fake_claude):
    agent_bridge.claude_login_start()
    _until(lambda: agent_bridge.claude_login_state()["url"])
    agent_bridge.claude_login_code("bad-code")
    st = _until(lambda: (lambda s: s if not s["pending"] else None)(agent_bridge.claude_login_state()))
    assert st["logged_in"] is False


def test_a_code_needs_a_sign_in_waiting_for_it(fake_claude):
    with pytest.raises(agent_bridge.AgentUnavailable):
        agent_bridge.claude_login_code("good-code")


@pytest.mark.parametrize("code", ["", "a\nb", "x" * 600])
def test_a_code_is_one_short_line(fake_claude, code):
    agent_bridge.claude_login_start()
    with pytest.raises(ValueError):
        agent_bridge.claude_login_code(code)


# --- the console API --------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from gigamail import http_api, policy
    policy.set_store(policy.ApprovalStore(str(tmp_path / "approvals.db")))
    with TestClient(http_api.app) as c:
        yield c
    policy.set_store(None)


def test_the_bar_learns_it_is_a_sign_in_problem(client, monkeypatch):
    """A header, not a different body: every other caller of these routes
    keeps reading detail as the message it always was."""
    def scaduto(prompt, **kw):
        raise agent_bridge.AgentLoginRequired("La sessione di Claude Code e' scaduta")

    monkeypatch.setattr(agent_bridge, "run", scaduto)
    r = client.post("/agent/command", json={"question": "riassumi"},
                    headers={"Origin": "http://127.0.0.1"})
    assert r.status_code == 503
    assert r.json()["detail"] == "La sessione di Claude Code e' scaduta"
    assert r.headers["X-GigaMail-Error"] == "agent_login"
    # the console runs on another origin: the header must be readable there
    assert "x-gigamail-error" in r.headers.get("access-control-expose-headers", "").lower()


def test_other_agent_errors_carry_no_sign_in_header(client, monkeypatch):
    def assente(prompt, **kw):
        raise agent_bridge.AgentUnavailable("nessun agente")

    monkeypatch.setattr(agent_bridge, "run", assente)
    r = client.post("/agent/command", json={"question": "riassumi"})
    assert r.status_code == 503
    assert "X-GigaMail-Error" not in r.headers


def test_sign_in_routes(client, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_bridge, "claude_login_state",
                        lambda: {"pending": False, "logged_in": True, "url": ""})
    monkeypatch.setattr(agent_bridge, "claude_login_start",
                        lambda: calls.append("start") or {"pending": True, "logged_in": False, "url": ""})
    monkeypatch.setattr(agent_bridge, "claude_login_code",
                        lambda code: calls.append(code) or {"pending": False, "logged_in": True, "url": ""})
    assert client.get("/agent/claude/login").json()["logged_in"] is True
    assert client.post("/agent/claude/login").json()["pending"] is True
    assert client.post("/agent/claude/login/code", json={"code": "abc"}).json()["logged_in"] is True
    assert calls == ["start", "abc"]

    def bad(code):
        raise ValueError("codice non valido")
    monkeypatch.setattr(agent_bridge, "claude_login_code", bad)
    assert client.post("/agent/claude/login/code", json={"code": "a b"}).status_code == 400
