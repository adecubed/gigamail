"""Google Antigravity (agy) as the console's agent: detection, the headless
stream-json round trip, and the config the console writes for it."""
import json
import sys
from types import SimpleNamespace

import pytest

from gigamail import agent_bridge
from gigamail.core import antigravity_config

PY = sys.executable

# A stand-in for `agy --input-format stream-json --output-format stream-json`:
# reads one user event from stdin, answers with init / step_update / result
# events. The answer echoes the prompt, so the test sees what arrived.
FAKE_AGY = r'''
import json, sys
event = json.loads(sys.stdin.readline())
prompt = event["message"]["content"]
status = "ERROR" if "FAIL" in prompt else "SUCCESS"
print(json.dumps({"event": "init", "conversation_id": "c1", "init": {"cwd": "."}}))
print(json.dumps({"event": "step_update", "step_update": {"conversation_id": "c1"}}))
result = {"conversation_id": "c1", "status": status, "response": "GOT:" + prompt}
if status != "SUCCESS":
    result["error"] = {"message": "quota exhausted"}
print(json.dumps({"event": "result", "result": result}))
'''


@pytest.fixture
def agy(tmp_path, monkeypatch, tmp_ade_root):
    """Antigravity selected in agent.json, its binary replaced by FAKE_AGY."""
    monkeypatch.delenv("ADE_AGENT_CMD", raising=False)
    script = tmp_path / "fake_agy.py"
    script.write_text(FAKE_AGY, encoding="utf-8")
    spec = agent_bridge.AGENTS["antigravity"]
    monkeypatch.setitem(spec, "find", lambda: PY)
    monkeypatch.setitem(spec, "command", lambda exe: [exe, str(script)])
    monkeypatch.setitem(spec, "cwd", lambda: str(tmp_path))
    cfg_path = agent_bridge._config_path()
    agent_bridge.select_agent("antigravity")
    yield
    try:
        import os
        os.unlink(cfg_path)
    except OSError:
        pass


def test_antigravity_is_a_known_agent_after_the_others():
    # The default stays the first agent found: Claude Code, then Codex.
    assert list(agent_bridge.AGENTS)[:3] == ["claude", "codex", "antigravity"]
    assert agent_bridge.AGENTS["antigravity"]["label"] == "Antigravity"


def test_command_is_headless_stream_json_without_the_prompt():
    cmd = agent_bridge.AGENTS["antigravity"]["command"]("agy")
    assert cmd[0] == "agy"
    assert cmd[cmd.index("--input-format") + 1] == "stream-json"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert not any("{prompt}" in a for a in cmd)
    # never auto-approve every tool: GigaMail's own approval stays the gate
    assert "--dangerously-skip-permissions" not in cmd


def test_multiline_prompt_travels_whole_on_stdin(agy):
    prompt = "Write a reply\nto mario.rossi@example.com\n\nabout Via Roma 10"
    assert agent_bridge.run(prompt) == "GOT:" + prompt


def test_select_and_status_report_antigravity(agy):
    st = agent_bridge.status()
    assert st["agent"] == "antigravity"
    assert st["available"] is True
    assert any(a["id"] == "antigravity" and a["found"] for a in st["agents"])


def test_an_error_result_is_not_a_draft(agy):
    with pytest.raises(agent_bridge.AgentUnavailable) as exc:
        agent_bridge.run("FAIL please")
    assert "quota exhausted" in str(exc.value)


def test_stdout_without_a_result_event_is_an_error():
    with pytest.raises(agent_bridge.AgentUnavailable):
        agent_bridge._antigravity_answer('{"event": "init"}\nnot json\n')


def test_last_result_event_wins_and_noise_is_skipped():
    out = "\n".join([
        "warning: something",
        json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "first"}}),
        json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": " last \n"}}),
    ])
    assert agent_bridge._antigravity_answer(out) == "last"


def test_stdin_is_one_json_line():
    data = agent_bridge._antigravity_stdin("a\nb")
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    assert json.loads(data) == {"event": "user", "message": {"content": "a\nb"}}


def test_find_agy_on_windows_install_path(tmp_path, monkeypatch):
    exe = tmp_path / "Local" / "agy" / "bin" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert agent_bridge._find_antigravity() == str(exe)


def test_find_agy_in_local_bin_on_macos(tmp_path, monkeypatch):
    exe = tmp_path / "home" / ".local" / "bin" / "agy"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(agent_bridge.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home")))
    assert agent_bridge._find_antigravity() == str(exe)


def test_find_agy_prefers_path(monkeypatch):
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda name: "/usr/bin/agy" if name == "agy" else None)
    assert agent_bridge._find_antigravity() == "/usr/bin/agy"


# ── the config the console writes for Antigravity ─────────────────────────

@pytest.fixture
def gemini(tmp_path, monkeypatch):
    home = tmp_path / ".gemini"
    monkeypatch.setattr(antigravity_config, "gemini_dir", lambda: home)
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path / "ade"))
    return home


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_connect_creates_server_entry_and_permission(gemini, tmp_path):
    assert antigravity_config.status()["connected"] is False
    st = antigravity_config.connect()
    assert st["connected"] is True
    entry = _json(gemini / "config" / "mcp_config.json")["mcpServers"]["gigamail"]
    assert entry == {"command": sys.executable, "args": ["-m", "gigamail.server"],
                     "env": {"GIGAMAIL_ROOT": str(tmp_path / "ade")}}
    allow = _json(gemini / "antigravity-cli" / "settings.json")["permissions"]["allow"]
    assert allow == ["mcp(gigamail/*)"]


def test_connect_keeps_everything_else(gemini):
    (gemini / "config").mkdir(parents=True)
    (gemini / "antigravity-cli").mkdir()
    mcp = {"mcpServers": {"other": {"command": "other"},
                          "gigamail": {"command": "gigamail-server"}}, "x": 1}
    settings = {"theme": "dark", "permissions": {"allow": ["command(git)"], "deny": ["command(rm -rf)"]}}
    (gemini / "config" / "mcp_config.json").write_text(json.dumps(mcp), encoding="utf-8")
    (gemini / "antigravity-cli" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    antigravity_config.connect()
    new_mcp = _json(gemini / "config" / "mcp_config.json")
    assert new_mcp["x"] == 1 and new_mcp["mcpServers"]["other"] == {"command": "other"}
    assert new_mcp["mcpServers"]["gigamail"]["command"] == sys.executable
    new_settings = _json(gemini / "antigravity-cli" / "settings.json")
    assert new_settings["theme"] == "dark"
    assert new_settings["permissions"] == {"allow": ["command(git)", "mcp(gigamail/*)"],
                                           "deny": ["command(rm -rf)"]}
    assert _json(gemini / "config" / "mcp_config.json.gigamail-bak") == mcp


def test_connect_twice_is_stable(gemini):
    antigravity_config.connect()
    first = (gemini / "antigravity-cli" / "settings.json").read_text(encoding="utf-8")
    antigravity_config.connect()
    assert (gemini / "antigravity-cli" / "settings.json").read_text(encoding="utf-8") == first
    assert not (gemini / "antigravity-cli" / "settings.json.gigamail-bak").exists()


def test_a_file_that_is_not_json_is_left_alone(gemini):
    (gemini / "antigravity-cli").mkdir(parents=True)
    original = '{ // my comment\n "theme": "dark" }'
    (gemini / "antigravity-cli" / "settings.json").write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        antigravity_config.connect()
    assert (gemini / "antigravity-cli" / "settings.json").read_text(encoding="utf-8") == original
    assert not (gemini / "config" / "mcp_config.json").exists()
    assert antigravity_config.status()["error"]


def test_selecting_antigravity_in_the_console_writes_its_config(monkeypatch):
    from gigamail.http_api import agent as agent_api
    from gigamail.http_api import console_click
    calls = []
    monkeypatch.setattr(console_click, "is_console_click", lambda headers: True)
    monkeypatch.setattr(agent_bridge, "get_config", lambda: {"agent": "antigravity"})
    monkeypatch.setattr(antigravity_config, "status", lambda: {"connected": False})
    monkeypatch.setattr(antigravity_config, "connect", lambda: calls.append("connect"))
    agent_api._ensure_agent_config(SimpleNamespace(headers={}))
    assert calls == ["connect"]
    # not a click in the console: nothing is written
    monkeypatch.setattr(console_click, "is_console_click", lambda headers: False)
    agent_api._ensure_agent_config(SimpleNamespace(headers={}))
    assert calls == ["connect"]
