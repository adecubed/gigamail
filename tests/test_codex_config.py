"""The console writes GigaMail's entry in Codex's config.toml (shared with the
ChatGPT desktop app): only that entry, and nothing when the rest would change."""
import sys

import pytest

tomllib = pytest.importorskip("tomllib")

from gigamail.core import codex_config  # noqa: E402  (after importorskip)


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path / "ade"))
    return home


def _cfg(home):
    return tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))


def test_no_file_creates_it_with_our_entry(codex_home, tmp_path):
    assert codex_config.status()["connected"] is False
    st = codex_config.connect()
    assert st["connected"] is True
    entry = _cfg(codex_home)["mcp_servers"]["gigamail"]
    assert entry == {"command": sys.executable, "args": ["-m", "gigamail.server"],
                     "default_tools_approval_mode": "approve",
                     "env": {"GIGAMAIL_ROOT": str(tmp_path / "ade")}}


def test_keeps_everything_else_and_replaces_an_old_entry(codex_home):
    codex_home.mkdir()
    original = (
        'model = "gpt-5"\n'
        '# my comment\n\n'
        '[mcp_servers.gigamail]\ncommand = "gigamail-server"\n\n'
        '[mcp_servers.gigamail.env]\nOLD = "1"\n\n'
        '[mcp_servers.other]\ncommand = "other"\nargs = [\n  "a",\n  "b",\n]\n\n'
        '[plugins."gigamail@gigamail"]\nenabled = true\n'
    )
    (codex_home / "config.toml").write_text(original, encoding="utf-8")
    codex_config.connect()
    cfg = _cfg(codex_home)
    assert cfg["model"] == "gpt-5"
    assert cfg["mcp_servers"]["other"] == {"command": "other", "args": ["a", "b"]}
    assert cfg["plugins"]["gigamail@gigamail"] == {"enabled": True}
    assert cfg["mcp_servers"]["gigamail"]["command"] == sys.executable
    assert "OLD" not in cfg["mcp_servers"]["gigamail"]["env"]
    text = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert "# my comment" in text
    assert (codex_home / "config.toml.gigamail-bak").read_text(encoding="utf-8") == original


def test_connect_twice_is_stable(codex_home):
    codex_config.connect()
    first = (codex_home / "config.toml").read_text(encoding="utf-8")
    codex_config.connect()
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == first


def test_an_entry_it_cannot_edit_leaves_the_file_alone(codex_home):
    codex_home.mkdir()
    original = 'mcp_servers.gigamail = { command = "gigamail-server" }\n'
    (codex_home / "config.toml").write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        codex_config.connect()
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == original


def test_an_entry_without_the_approval_mode_needs_reconnecting(codex_home, tmp_path):
    # codex exec cancels tool calls that would ask for a confirmation: an
    # entry from before default_tools_approval_mode is not "connected".
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        f'[mcp_servers.gigamail]\ncommand = {codex_config._q(sys.executable)}\n'
        'args = ["-m", "gigamail.server"]\n\n[mcp_servers.gigamail.env]\n'
        f'GIGAMAIL_ROOT = {codex_config._q(str(tmp_path / "ade"))}\n', encoding="utf-8")
    assert codex_config.status()["connected"] is False
    assert codex_config.connect()["connected"] is True


def test_status_reports_a_foreign_entry_as_not_connected(codex_home):
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('[mcp_servers.gigamail]\ncommand = "gigamail-server"\n', encoding="utf-8")
    st = codex_config.status()
    assert st["connected"] is False
    assert st["entry"]["command"] == "gigamail-server"


def test_windows_paths_survive_the_round_trip(codex_home, monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\Users\V\AppData\Local\Programs\GigaMail\resources\python\python.exe")
    want = dict(codex_config.desired(), env={"GIGAMAIL_ROOT": r"C:\Users\V\AppData\Roaming\ADE"})
    entry = tomllib.loads(codex_config._block(want))["mcp_servers"]["gigamail"]
    assert entry["command"] == want["command"]
    assert entry["env"]["GIGAMAIL_ROOT"] == r"C:\Users\V\AppData\Roaming\ADE"


def test_the_route_writes_only_on_a_console_click(codex_home):
    from fastapi.testclient import TestClient

    from gigamail import http_api
    from gigamail.http_api import console_click
    secret = "s" * 40
    console_click.set_secret(secret)
    try:
        with TestClient(http_api.app) as c:
            assert c.get("/agent/codex").json()["connected"] is False
            assert c.post("/agent/codex/connect").status_code == 403
            assert not (codex_home / "config.toml").exists()
            r = c.post("/agent/codex/connect", headers={console_click.HEADER: secret})
            assert r.status_code == 200 and r.json()["connected"] is True
    finally:
        console_click.set_secret("")


def test_the_agent_bar_with_codex_connects_it_first(codex_home, tmp_path, monkeypatch):
    # Codex as the agent and no entry: the run would have no GigaMail tools.
    # A click in the console writes the entry before Codex starts; a request
    # without the click secret does not touch the file.
    from fastapi.testclient import TestClient

    from gigamail import agent_bridge, http_api, policy
    from gigamail.http_api import console_click
    policy.set_store(policy.ApprovalStore(str(tmp_path / "approvals.db")))
    real = agent_bridge.get_config
    monkeypatch.setattr(agent_bridge, "get_config", lambda: dict(real(), agent="codex"))
    seen = []
    monkeypatch.setattr(agent_bridge, "run",
                        lambda p, **k: seen.append(codex_config.status()["connected"]) or "ok")
    secret = "s" * 40
    console_click.set_secret(secret)
    try:
        with TestClient(http_api.app) as c:
            assert c.post("/agent/command", json={"question": "hi"}).status_code == 200
            assert not (codex_home / "config.toml").exists()
            r = c.post("/agent/command", json={"question": "hi"}, headers={console_click.HEADER: secret})
            assert r.status_code == 200
        assert seen == [False, True]
    finally:
        console_click.set_secret("")
        policy.set_store(None)
