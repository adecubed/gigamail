"""agent_bridge: risoluzione comando, placeholder, timeout, errori."""
import json
import os
import sys

import pytest

from ade_mail_agent import agent_bridge

PY = sys.executable


def _righe(s: str) -> str:
    """Su Windows print() converte gli a capo in CRLF: qui interessa il
    testo, non il modo in cui il figlio l'ha stampato."""
    return s.replace("\r\n", "\n")


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


# ── agenti noti: Claude Code e Codex CLI ──────────────────────────────────

def test_comando_codex_ha_exec_output_e_prompt():
    cmd = agent_bridge.AGENTS["codex"]["command"]("codex")
    assert cmd[:2] == ["codex", "exec"]
    assert "{prompt}" in cmd and "{output}" in cmd
    assert "read-only" in cmd  # sandbox: scrive la bozza, non il disco


def test_output_placeholder_letto_da_file(monkeypatch):
    """Con {output} la risposta arriva dal file, non da stdout (Codex stampa
    su stdout anche il resto della sessione)."""
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; open(sys.argv[1], 'w').write('RISPOSTA FINALE'); print('rumore su stdout')",
         "{output}", "{prompt}"]))
    assert agent_bridge.run("ciao") == "RISPOSTA FINALE"


def test_select_agent_scrive_agent_json_e_status_lo_riporta(monkeypatch, tmp_ade_root):
    monkeypatch.delenv("ADE_AGENT_CMD", raising=False)
    cfg_path = agent_bridge._config_path()
    try:
        st = agent_bridge.select_agent("codex")
        assert st["agent"] == "codex"
        assert json.load(open(cfg_path, encoding="utf-8"))["agent"] == "codex"
        assert agent_bridge.get_config()["command"][1] == "exec"
        ids = [a["id"] for a in st["agents"]]
        assert ids[:2] == ["claude", "codex"]
        assert all("found" in a and "mcp" in a for a in st["agents"])
    finally:
        os.unlink(cfg_path)


def test_select_agent_conserva_il_comando_custom(monkeypatch, tmp_ade_root):
    monkeypatch.delenv("ADE_AGENT_CMD", raising=False)
    cfg_path = agent_bridge._config_path()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"command": ["mio", "{prompt}"], "timeout": 44}, f)
    try:
        assert agent_bridge.get_config()["agent"] == "custom"
        agent_bridge.select_agent("claude")
        saved = json.load(open(cfg_path, encoding="utf-8"))
        assert saved["command_custom"] == ["mio", "{prompt}"] and saved["agent"] == "claude"
        assert agent_bridge.get_config()["timeout"] == 44
    finally:
        os.unlink(cfg_path)


def test_select_agent_sconosciuto():
    with pytest.raises(ValueError):
        agent_bridge.select_agent("skynet")


def test_prompt_su_piu_righe_passa_da_stdin(monkeypatch):
    """cmd.exe tronca la riga di comando al primo a capo, e npm installa
    claude e codex come wrapper .cmd: un prompt multiriga passato come
    argomento arriva mutilato. Deve andare su stdin anche quando e' corto."""
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; sys.stdout.write(sys.stdin.read())", "{prompt}"]))
    prompt = "prima riga\nseconda riga\nterza riga"
    assert _righe(agent_bridge.run(prompt)) == prompt


def test_prompt_multiriga_da_stdin_anche_senza_placeholder(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; sys.stdout.write(sys.stdin.read())"]))
    prompt = "riga uno\nriga due"
    assert _righe(agent_bridge.run(prompt)) == prompt


def test_prompt_di_una_riga_resta_un_argomento(monkeypatch):
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import sys; print('ARG:' + sys.argv[1])", "{prompt}"]))
    assert agent_bridge.run("una riga sola") == "ARG:una riga sola"
