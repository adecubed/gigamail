"""agent_bridge: risoluzione comando, placeholder, timeout, errori."""
import json
import os
import sys

import pytest

from ade_mail_agent import agent_bridge


PY = sys.executable


def test_env_cmd_ha_precedenza(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(["mio-agente", "{prompt}"]))
    cfg = agent_bridge.get_config()
    assert cfg["command"][0] == "mio-agente"


def test_config_file_usato_senza_env(monkeypatch, tmp_ade_root):
    monkeypatch.delenv("ADE_AGENT_CMD", raising=False)
    cfg_path = agent_bridge._config_path()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"command": ["agente-da-file", "{prompt}"], "timeout": 33}, f)
    try:
        cfg = agent_bridge.get_config()
        assert cfg["command"][0] == "agente-da-file"
        assert cfg["timeout"] == 33
    finally:
        os.unlink(cfg_path)


def test_placeholder_sostituito(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; print('ARG:' + sys.argv[1])", "{prompt}"]))
    out = agent_bridge.run("ciao mondo")
    assert out == "ARG:ciao mondo"


def test_prompt_appeso_senza_placeholder(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; print(sys.argv[1])"]))
    out = agent_bridge.run("prompt-in-coda")
    assert out == "prompt-in-coda"


def test_timeout_solleva_agent_unavailable(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import time; time.sleep(30)", "{prompt}"]))
    with pytest.raises(agent_bridge.AgentUnavailable):
        agent_bridge.run("x", timeout=2)


def test_exe_mancante_messaggio_chiaro(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        ["eseguibile-che-non-esiste-xyz", "{prompt}"]))
    with pytest.raises(agent_bridge.AgentUnavailable) as exc:
        agent_bridge.run("x")
    assert "agent.json" in str(exc.value)


def test_exit_code_errore_senza_output(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; sys.stderr.write('rotto'); sys.exit(3)", "{prompt}"]))
    with pytest.raises(agent_bridge.AgentUnavailable) as exc:
        agent_bridge.run("x")
    assert "rotto" in str(exc.value)


def test_status_riporta_comando(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps([PY, "{prompt}"]))
    st = agent_bridge.status()
    assert st["available"] is True
    assert st["command"] == PY
