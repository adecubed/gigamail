"""agent_bridge: risoluzione comando, placeholder, timeout, errori."""
import json
import os
import sys

import pytest

from gigamail import agent_bridge

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


def test_status_riporta_il_python_del_backend(monkeypatch):
    # L'onboarding lo fa usare ai client MCP: -m gigamail.server con il
    # Python dell'app, perche' gigamail-server non e' nel PATH dell'utente.
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps([PY, "{prompt}"]))
    assert agent_bridge.status()["python"] == sys.executable


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


# --- ANTHROPIC_API_KEY versus the claude.ai login ---------------------------

_PRINT_KEY = "import os; print(os.environ.get('ANTHROPIC_API_KEY', 'ABSENT'))"


def _claude_login(tmp_path, monkeypatch, token: str):
    """A Claude Code config dir whose credentials file holds `token`."""
    cfg_dir = tmp_path / "claude-config"
    cfg_dir.mkdir()
    (cfg_dir / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": token}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg_dir))


def _as_claude_agent(monkeypatch):
    """The test command runs Python, not claude: tell the bridge it is Claude Code."""
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps([PY, "-c", _PRINT_KEY, "{prompt}"]))
    monkeypatch.setattr(agent_bridge, "_agent_of", lambda cfg: "claude")


def test_api_key_dropped_for_claude_when_logged_in(tmp_path, monkeypatch):
    """Claude Code lets ANTHROPIC_API_KEY win over the claude.ai login, so a
    user who keeps the key for other programs would pay per token and lose
    the account's connectors: with a login present the key must not reach
    the child."""
    _as_claude_agent(monkeypatch)
    _claude_login(tmp_path, monkeypatch, token="yes")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert agent_bridge.run("x") == "ABSENT"


def test_api_key_kept_without_claude_login(tmp_path, monkeypatch):
    """No login: the key is the only way the CLI can authenticate."""
    _as_claude_agent(monkeypatch)
    _claude_login(tmp_path, monkeypatch, token="")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert agent_bridge.run("x") == "set"


def test_api_key_kept_when_credentials_file_missing(tmp_path, monkeypatch):
    _as_claude_agent(monkeypatch)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert agent_bridge.run("x") == "set"


def test_api_key_kept_with_gateway_base_url(tmp_path, monkeypatch):
    """ANTHROPIC_BASE_URL means a gateway that authenticates with the key."""
    _as_claude_agent(monkeypatch)
    _claude_login(tmp_path, monkeypatch, token="yes")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com")
    assert agent_bridge.run("x") == "set"


def test_api_key_untouched_for_other_agents(tmp_path, monkeypatch):
    """Only Claude Code has this precedence rule: a custom command keeps
    its environment exactly as the user set it."""
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps([PY, "-c", _PRINT_KEY, "{prompt}"]))
    _claude_login(tmp_path, monkeypatch, token="yes")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert agent_bridge.run("x") == "set"
def _fake_claude_exe(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"MZ")


def test_find_claude_desktop_layouts(monkeypatch, tmp_path):
    """The desktop app's bundled CLI is found in both layouts: the old
    <version>/claude.exe and the current <version>/<hash>/claude.exe, and the
    newest version wins regardless of layout."""
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda name: None)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = tmp_path / "Claude" / "claude-code"

    # Nothing installed yet: the bare name is returned for the caller to report.
    assert agent_bridge._find_claude() == "claude"

    old = base / "2.1.100" / "claude.exe"
    _fake_claude_exe(str(old))
    assert agent_bridge._find_claude() == str(old)

    nested = base / "2.1.295" / "abcdef012345" / "claude.exe"
    _fake_claude_exe(str(nested))
    assert agent_bridge._find_claude() == str(nested)

    # A newer direct-layout version beats an older nested one (version
    # order is numeric, not lexical: 2.1.1000 > 2.1.295).
    newer_direct = base / "2.1.1000" / "claude.exe"
    _fake_claude_exe(str(newer_direct))
    assert agent_bridge._find_claude() == str(newer_direct)

    # A version folder without any exe (e.g. a half-finished update) is skipped.
    (base / "2.1.2000" / "0123456789ab").mkdir(parents=True)
    assert agent_bridge._find_claude() == str(newer_direct)


def test_the_agent_runs_the_gigamail_server_of_this_install(tmp_path, monkeypatch):
    """The plugin starts ${GIGAMAIL_SERVER:-gigamail-server}: the agent the
    console launches gets the server next to the console's own Python, not
    whatever gigamail-server the PATH finds first."""
    import sys
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python").write_text("")
    server = fake_bin / "gigamail-server"
    server.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_bin / "python"))
    monkeypatch.delenv("GIGAMAIL_SERVER", raising=False)
    env = agent_bridge._env_for_child({"agent": "codex", "command": ["codex"]})
    assert env["GIGAMAIL_SERVER"] == str(server)
    monkeypatch.setenv("GIGAMAIL_SERVER", "/custom/server")
    env = agent_bridge._env_for_child({"agent": "codex", "command": ["codex"]})
    assert env is None or env.get("GIGAMAIL_SERVER") == "/custom/server"


def test_agent_bar_runs_send_no_desktop_toast(monkeypatch):
    """The agent bar shows its approval cards in the console: the MCP server
    it starts gets GIGAMAIL_NOTIFY_DESKTOP=0, other runs keep the toast."""
    monkeypatch.delenv("GIGAMAIL_NOTIFY_DESKTOP", raising=False)
    cfg = {"agent": "codex", "command": ["codex"]}
    quiet = agent_bridge._env_for_child(cfg, quiet_desktop=True)
    assert quiet["GIGAMAIL_NOTIFY_DESKTOP"] == "0"
    loud = agent_bridge._env_for_child(cfg)
    assert loud is None or "GIGAMAIL_NOTIFY_DESKTOP" not in loud


def test_codex_from_the_desktop_app_without_the_npm_cli(tmp_path, monkeypatch):
    # Only the Codex / ChatGPT app installed: no codex on PATH, no npm
    # folder. The app keeps codex.exe in a hash-named folder per update
    # (%LOCALAPPDATA%/OpenAI/Codex/bin/<hash>/codex.exe): the newest is used.
    import os
    bin_ = tmp_path / "Local" / "OpenAI" / "Codex" / "bin"
    old, new = bin_ / "1111aaaa" / "codex.exe", bin_ / "9614f1d9b40d9c4f" / "codex.exe"
    for exe, t in ((old, 1_000_000), (new, 2_000_000)):
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        os.utime(exe, (t, t))
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda name: None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert agent_bridge._find_codex() == str(new)


def test_the_desktop_app_codex_wins_over_an_npm_cli(tmp_path, monkeypatch):
    # The npm CLI does not update itself; the app does, and they share
    # ~/.codex. With both present the app's binary is the one started.
    app = tmp_path / "Local" / "OpenAI" / "Codex" / "bin" / "abc" / "codex.exe"
    app.parent.mkdir(parents=True)
    app.write_bytes(b"")
    monkeypatch.setattr(agent_bridge.shutil, "which", lambda name: str(tmp_path / "npm" / "codex.cmd"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert agent_bridge._find_codex() == str(app)


def test_the_error_shown_is_the_reason_not_codex_header():
    # codex exec's stderr starts with a header longer than the console's
    # message; the ERROR line after it is what the user needs to see.
    header = "\n".join(f"{k}: {v}" for k, v in [
        ("OpenAI Codex", "v0.163.0-alpha.10.2"), ("workdir", "C:\\Users\\V"),
        ("model", "gpt-5.5"), ("provider", "openai"), ("approval", "never"),
        ("sandbox", "read-only"), ("reasoning effort", "medium"),
        ("reasoning summaries", "auto"), ("session id", "0" * 36)] * 3)
    err = header + "\n2026-10-21T10:00:00Z ERROR codex_core: Not logged in: run codex login\n"
    assert len(header) > 400
    msg = agent_bridge._error_excerpt(err)
    assert msg.startswith("2026-10-21T10:00:00Z ERROR")
    assert "Not logged in" in msg
    assert "reasoning summaries" not in msg
    # no error line: the tail, where a plain message ends up
    assert agent_bridge._error_excerpt("x" * 1000 + "the end").endswith("the end")


# ── Codex: a model the ChatGPT account cannot use ─────────────────────────

def _models_cache(tmp_path, monkeypatch, models):
    home = tmp_path / "codex"
    home.mkdir()
    (home / "models_cache.json").write_text(json.dumps(
        {"fetched_at": "2026-10-21T00:00:00Z", "client_version": "0.163.0",
         "models": models}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))


def test_models_available_lists_visible_models_in_priority_order(tmp_path, monkeypatch):
    _models_cache(tmp_path, monkeypatch, [
        {"slug": "gpt-5.4-mini", "priority": 5, "visibility": "list"},
        {"slug": "gpt-5.6-sol", "priority": 1, "visibility": "list"},
        {"slug": "secret-model", "priority": 0, "visibility": "hide"},
        {"slug": "gpt-5.6-luna", "priority": 2},
    ])
    assert agent_bridge._codex_models_available() == ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.4-mini"]
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))
    assert agent_bridge._codex_models_available() == []


def test_refused_model_is_retried_with_the_accounts_own_and_remembered(tmp_path, monkeypatch, tmp_ade_root):
    _models_cache(tmp_path, monkeypatch, [{"slug": "gpt-5.6-sol", "priority": 1}, {"slug": "gpt-5.6-luna", "priority": 2}])
    monkeypatch.setattr(agent_bridge, "_find_codex", lambda: PY)
    agent_bridge.select_agent("codex")
    calls = []

    def fake_spawn(cmd, stdin_bytes, timeout, env, run_id, cwd=None):
        calls.append(list(cmd))
        if "-m" not in cmd:
            return 1, b"", (b"model: gpt-5.5\nERROR: {\"type\":\"error\",\"status\":400,\"error\":{\"message\":"
                            b"\"The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account.\"}}\n")
        out = cmd[cmd.index("-o") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write("Three unread mails.")
        return 0, b"", b""
    monkeypatch.setattr(agent_bridge, "_spawn", fake_spawn)
    assert agent_bridge.run("what is new?") == "Three unread mails."
    assert len(calls) == 2
    assert calls[1][calls[1].index("-m") + 1] == "gpt-5.6-sol"
    assert agent_bridge.codex_model() == "gpt-5.6-sol"
    # the next run asks for it from the start
    assert "-m" in agent_bridge.get_config()["command"]
    assert agent_bridge.status()["codex_model"] == "gpt-5.6-sol"


def test_refused_model_with_no_cache_reports_the_reason(tmp_path, monkeypatch, tmp_ade_root):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty"))
    monkeypatch.setattr(agent_bridge, "_find_codex", lambda: PY)
    agent_bridge.select_agent("codex")
    monkeypatch.setattr(agent_bridge, "_spawn", lambda *a, **k: (1, b"", b"ERROR: The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account."))
    with pytest.raises(agent_bridge.AgentUnavailable) as e:
        agent_bridge.run("hi")
    assert "gpt-5.5" in str(e.value)


@pytest.mark.parametrize("lang, expected", [
    ("en", "The agent did not answer in time"),
    ("it", "L'agente non ha risposto entro il tempo massimo"),
])
def test_timeout_message_follows_the_user_language(monkeypatch, lang, expected):
    """The console bar shows this text to the user: an English console got
    it in Italian."""
    monkeypatch.setenv("GIGAMAIL_LANG", lang)
    monkeypatch.setenv("ADE_AGENT_CMD", json.dumps(
        [PY, "-c", "import time; time.sleep(30)", "{prompt}"]))
    with pytest.raises(agent_bridge.AgentUnavailable) as exc:
        agent_bridge.run("x", timeout=2)
    assert expected in str(exc.value)
