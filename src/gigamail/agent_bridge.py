# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Ponte console → agente.

Quello che nella vecchia app era delegato all'LLM interno (llm.py) qui viene
delegato all'AGENTE dell'utente: la console inoltra l'istruzione ("scrivi la
bozza", "trova le mail di...") a un agente headless — Claude Code in modalita'
-p, oppure Codex CLI in modalita' exec — che ha gia' i tool MCP di GigaMail e
quindi puo' cercare, leggere e ragionare sulla posta con la conoscenza
dell'account.

Configurazione (in ordine di precedenza):
1. env ADE_AGENT_CMD — JSON array, es. ["claude","-p","{prompt}"]
2. %APPDATA%/ADE/agent.json — {"agent": "codex"} per uno degli agenti noti
   (il comando viene risolto a ogni avvio, cosi' segue gli aggiornamenti
   della CLI), oppure {"command": [...], "timeout": 180} per un comando tuo
3. default: il primo agente noto trovato sul PC (Claude Code, poi Codex)

Segnaposto nel comando: {prompt} viene sostituito con l'istruzione (se
assente, il prompt viene appeso come ultimo argomento); {output} con un file
temporaneo da cui leggere la risposta finale, per le CLI che su stdout
stampano anche il resto (Codex).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

DEFAULT_TIMEOUT = 180


def _say(it: str, en: str) -> str:
    """An error for the console bar, in the user's language: these strings
    reach the person, who may not read Italian."""
    try:
        from gigamail import policy
        return it if policy.user_lang() == "it" else en
    except Exception:
        return en


class AgentUnavailable(Exception):
    pass


class AgentCancelled(AgentUnavailable):
    """The user pressed Stop in the console: the agent's process was ended."""


# Runs started with a run_id, so that the console's Stop can end them. The
# agent spawns its own children (claude.cmd -> node, MCP server): the whole
# tree goes.
_RUNNING: dict = {}
_CANCELLED: set = set()
_LOCK = threading.Lock()


def _kill_tree(proc) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10, **_quiet_kw())
        else:
            import signal
            os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def cancel(run_id: str) -> bool:
    """End the run started with this id. False when nothing is running
    under it (already finished, or never started)."""
    with _LOCK:
        # Recorded even before the process exists: a Stop pressed while the
        # run is still starting ends it as soon as it is spawned.
        if len(_CANCELLED) > 100:
            _CANCELLED.clear()
        _CANCELLED.add(run_id)
        proc = _RUNNING.get(run_id)
    if proc is None:
        return False
    _kill_tree(proc)
    return True


def _quiet_kw() -> dict:
    """Popen arguments that keep the agent off the screen on Windows. The
    npm wrappers (claude.cmd, codex.cmd) and codex.exe are console programs:
    started from the backend, which has no console, Windows gave them a new
    one, and a black "claude" terminal popped over the mail while the bar
    worked. CREATE_NO_WINDOW starts them with no console at all; stdin,
    stdout and stderr are pipes anyway."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}


def _spawn(cmd, stdin_bytes, timeout, env, run_id, cwd=None):
    """(returncode, stdout, stderr). Without a run_id, subprocess.run as
    always; with one, the process is registered so cancel() can end it."""
    if not run_id:
        p = subprocess.run(cmd, capture_output=True, input=stdin_bytes,
                           stdin=None if stdin_bytes is not None else subprocess.DEVNULL,
                           timeout=timeout, shell=False, env=env, cwd=cwd, **_quiet_kw())
        return p.returncode, p.stdout, p.stderr
    kw = {"start_new_session": True} if os.name != "nt" else _quiet_kw()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                            shell=False, env=env, cwd=cwd, **kw)
    with _LOCK:
        _RUNNING[run_id] = proc
        early = run_id in _CANCELLED
    if early:
        _kill_tree(proc)
    try:
        try:
            out, err = proc.communicate(input=stdin_bytes, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            raise
    finally:
        with _LOCK:
            _RUNNING.pop(run_id, None)
            stopped = run_id in _CANCELLED
            _CANCELLED.discard(run_id)
    if stopped:
        raise AgentCancelled("Fermato dall'utente.")
    return proc.returncode, out, err


def _found(exe: str) -> bool:
    return bool(exe) and (shutil.which(exe) is not None or os.path.exists(exe))


def _version_key(name: str) -> list:
    return [int(x) for x in name.split(".") if x.isdigit()]


def _find_claude() -> str:
    """Find the Claude Code CLI: PATH first, otherwise the newest versioned
    install bundled with the desktop app under %APPDATA%/Claude/claude-code.

    Older desktop builds put the binary at <version>/claude.exe; current
    ones nest it one level deeper, in a hash-named folder
    (<version>/<hash>/claude.exe). Both layouts are searched, newest
    version wins."""
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    base = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code")
    try:
        found = {}
        for ver in os.listdir(base):
            direct = os.path.join(base, ver, "claude.exe")
            if os.path.isfile(direct):
                found[ver] = direct
                continue
            nested = sorted(glob.glob(os.path.join(base, ver, "*", "claude.exe")))
            if nested:
                found[ver] = nested[0]
        if found:
            return found[max(found, key=_version_key)]
    except Exception:
        pass
    return "claude"  # let the caller report that it is missing


def _codex_app_candidates() -> list:
    """Where the Codex / ChatGPT desktop app keeps its own codex.exe on
    Windows, newest first. A user who installed only the app has no npm
    CLI, and must not need one: the app's binary runs `codex exec` the same
    way. Seen on a Windows 11 PC:
    %LOCALAPPDATA%/OpenAI/Codex/bin/<hash>/codex.exe, one hash-named folder
    per update; reported elsewhere: %LOCALAPPDATA%/Programs/OpenAI/Codex/bin
    (openai/codex#26423). Directly in bin/ or one folder below, both."""
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    found = []
    for base in (os.path.join(local, "OpenAI", "Codex", "bin"),
                 os.path.join(local, "Programs", "OpenAI", "Codex", "bin")):
        for pattern in (os.path.join(base, "codex.exe"), os.path.join(base, "*", "codex.exe")):
            try:
                found.extend(glob.glob(pattern))
            except Exception:
                pass

    def mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0
    return sorted(set(found), key=mtime, reverse=True)


def _find_codex() -> str:
    """Find Codex: the codex.exe of the Codex / ChatGPT desktop app first,
    then the CLI on PATH or in %APPDATA%/npm (npm's codex.cmd), for a
    process that did not inherit the PATH.

    The app comes first because it updates itself: an npm CLI left behind
    shares ~/.codex with the app and fails on what a newer app wrote there
    ("unknown variant `max`" reading the models cache)."""
    for cand in _codex_app_candidates():
        if os.path.isfile(cand):
            return cand
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    for name in ("codex.cmd", "codex"):
        cand = os.path.join(os.environ.get("APPDATA", ""), "npm", name)
        if os.path.exists(cand):
            return cand
    return "codex"


# The names the GigaMail MCP server goes by in Claude Code: "gigamail" when
# registered by hand (claude mcp add gigamail), "plugin_gigamail_gigamail"
# when it comes from the plugin, "ade-mail" in installs from before the
# rename. Allowing only "ade-mail" left today's installs without permission
# in -p mode: every tool call was refused, including the completion of a
# request the user had just approved.
CLAUDE_MCP_SERVERS = ("gigamail", "plugin_gigamail_gigamail", "ade-mail")


def _cmd_claude(exe: str) -> list:
    # Server-level rules (mcp__<server>) allow every tool of the GigaMail
    # server; DANGEROUS tools stay two-phase on the server side regardless.
    allowed = ",".join(f"mcp__{name}" for name in CLAUDE_MCP_SERVERS)
    return [exe, "-p", "{prompt}", "--allowedTools", allowed]


def _cmd_codex(exe: str) -> list:
    # exec = non interattivo. Sandbox in sola lettura: l'agente scrive la
    # bozza, non tocca il disco; --skip-git-repo-check perche' la cartella di
    # lavoro della console non e' un repository. La risposta finale va in un
    # file ({output}): su stdout Codex stampa anche il resto della sessione.
    # -m: il modello scelto (agent.json "codex_model"), quando c'e': batte un
    # `model = ...` in config.toml che l'account non ha piu' (vedi run()).
    cmd = [exe, "exec", "--skip-git-repo-check", "-s", "read-only", "--color", "never"]
    model = codex_model()
    if model:
        cmd += ["-m", model]
    return cmd + ["-o", "{output}", "{prompt}"]


def codex_model() -> str:
    """The model Codex is asked for, from agent.json ("codex_model"); empty
    lets Codex pick its default."""
    m = _read_config_file().get("codex_model")
    return m.strip() if isinstance(m, str) else ""


def set_codex_model(model: str) -> None:
    cfg = _read_config_file()
    if model:
        cfg["codex_model"] = model
    else:
        cfg.pop("codex_model", None)
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


_MODEL_REFUSED = re.compile(
    r"model is not supported|Model metadata for ['`\"]?[\w.\-]+['`\"]? not found|"
    r"model[^\n]{0,60}(not available|does not exist|unknown model)", re.I)


def _codex_models_available() -> list:
    """The models the signed-in account can use, from Codex's own
    models_cache.json ($CODEX_HOME, default ~/.codex), listed ones first in
    their priority order. Empty when there is no cache."""
    home = os.environ.get("CODEX_HOME", "").strip() or os.path.join(os.path.expanduser("~"), ".codex")
    try:
        with open(os.path.join(home, "models_cache.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    found = []

    def walk(node):
        if isinstance(node, dict):
            slug = node.get("slug")
            if isinstance(slug, str) and slug:
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(data)
    listed = [m for m in found if str(m.get("visibility", "list")).lower() not in ("hide", "hidden")]
    pool = listed or found
    pool.sort(key=lambda m: (m.get("priority") if isinstance(m.get("priority"), (int, float)) else 1e9))
    out = []
    for m in pool:
        if m["slug"] not in out:
            out.append(m["slug"])
    return out


def _with_model(cmd: list, model: str) -> list:
    """The codex command with -m <model> (replacing an earlier -m)."""
    out, skip = [], False
    for a in cmd:
        if skip:
            skip = False
            continue
        if a == "-m":
            skip = True
            continue
        out.append(a)
    i = out.index("exec") + 1 if "exec" in out else 1
    return out[:i] + ["-m", model] + out[i:]


def _find_antigravity() -> str:
    """Find the Google Antigravity CLI (agy): PATH first, then where its
    install script puts it, for a process that did not inherit the PATH:
    %LOCALAPPDATA%/agy/bin/agy.exe on Windows, ~/.local/bin/agy on macOS
    and Linux."""
    on_path = shutil.which("agy")
    if on_path:
        return on_path
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [os.path.join(local, "agy", "bin", "agy.exe")] if local else []
    candidates.append(os.path.join(os.path.expanduser("~"), ".local", "bin", "agy"))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return "agy"


def _cmd_antigravity(exe: str) -> list:
    # Headless mode with the prompt as a stream-json event on stdin: agy -p
    # takes the prompt only as an argument, which cannot carry a long or
    # multi-line prompt, and with --input-format text agy does not read
    # stdin. --sandbox: the agent writes a draft, it runs no commands.
    return [exe, "--input-format", "stream-json", "--output-format", "stream-json", "--sandbox"]


def _antigravity_stdin(prompt: str) -> bytes:
    """One user event, then EOF: agy ends the session after that turn."""
    event = {"event": "user", "message": {"content": prompt}}
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


def _antigravity_answer(stdout: str) -> str:
    """The response of the last `result` event of agy's NDJSON stream.
    Anything but SUCCESS is an error, not an answer: a failed run must not
    come back as the body of a draft."""
    result = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
    if result is None:
        raise AgentUnavailable(f"Antigravity returned no result: {(stdout or '')[:400]}")
    if result.get("status") != "SUCCESS":
        err = result.get("error")
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        raise AgentUnavailable(f"Antigravity: {result.get('status')} {str(err or '')[:400]}".strip())
    response = result.get("response")
    return response.strip() if isinstance(response, str) else ""


def _antigravity_workspace() -> str:
    """An empty folder as agy's workspace. agy lets the agent read and write
    files in its workspace without asking: the console's own folder is no
    place for an agent that reads untrusted mail."""
    from gigamail.core.data_paths import app_root
    path = os.path.join(str(app_root()), "agent-workspace")
    os.makedirs(path, exist_ok=True)
    return path


# Agenti che la console sa riconoscere da sola. L'ordine e' quello del default.
# `find` passa dal nome del modulo a ogni chiamata (lambda), non da un
# riferimento preso all'import: cosi' i test possono sostituire _find_claude
# e la ri-risoluzione dopo un aggiornamento usa davvero la funzione nuova.
AGENTS = {
    "claude": {"label": "Claude Code", "find": lambda: _find_claude(), "command": _cmd_claude,
               "mcp": "json"},
    "codex": {"label": "Codex", "find": lambda: _find_codex(), "command": _cmd_codex,
              "mcp": "toml"},
    # stdin / answer / cwd: an agent whose prompt travels as data on stdin
    # and whose answer is parsed out of its stdout.
    "antigravity": {"label": "Antigravity", "find": lambda: _find_antigravity(),
                    "command": _cmd_antigravity, "mcp": "json",
                    "stdin": _antigravity_stdin, "answer": _antigravity_answer,
                    "cwd": lambda: _antigravity_workspace()},
}


def _config_path() -> str:
    from gigamail.core.data_paths import app_root
    return os.path.join(str(app_root()), "agent.json")


def _read_config_file() -> dict:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _default_agent() -> str:
    for agent_id, spec in AGENTS.items():
        if _found(spec["find"]()):
            return agent_id
    return next(iter(AGENTS))


def get_config() -> dict:
    """{"command": [...], "timeout": int, "agent": "claude"|"codex"|"antigravity"|"custom"}"""
    env_cmd = os.environ.get("ADE_AGENT_CMD", "")
    if env_cmd:
        try:
            cmd = json.loads(env_cmd)
            if isinstance(cmd, list) and cmd:
                return {"command": cmd, "timeout": DEFAULT_TIMEOUT, "agent": "custom"}
        except Exception:
            pass
    cfg = _read_config_file()
    timeout = cfg.get("timeout") if isinstance(cfg.get("timeout"), int) else DEFAULT_TIMEOUT
    if isinstance(cfg.get("command"), list) and cfg["command"]:
        return {"command": cfg["command"], "timeout": timeout, "agent": "custom"}
    agent_id = cfg.get("agent") if cfg.get("agent") in AGENTS else _default_agent()
    spec = AGENTS[agent_id]
    return {"command": spec["command"](spec["find"]()), "timeout": timeout, "agent": agent_id}


def available_agents() -> list:
    """Gli agenti noti, con esito del rilevamento; piu' l'eventuale comando
    personalizzato di agent.json / ADE_AGENT_CMD."""
    out = []
    for agent_id, spec in AGENTS.items():
        exe = spec["find"]()
        out.append({"id": agent_id, "label": spec["label"], "found": _found(exe),
                    "exe": exe, "mcp": spec["mcp"]})
    cfg = get_config()
    if cfg["agent"] == "custom":
        out.append({"id": "custom", "label": "Custom (agent.json)", "found": _found(cfg["command"][0]),
                    "exe": cfg["command"][0], "mcp": "json"})
    return out


def select_agent(agent_id: str) -> dict:
    """Scrive la scelta in agent.json e restituisce lo stato aggiornato.
    Un comando personalizzato presente nel file viene lasciato da parte
    (chiave `command_custom`), non cancellato."""
    if agent_id not in AGENTS:
        raise ValueError(f"agente sconosciuto: {agent_id!r} (noti: {', '.join(AGENTS)})")
    cfg = _read_config_file()
    if isinstance(cfg.get("command"), list):
        cfg["command_custom"] = cfg.pop("command")
    cfg["agent"] = agent_id
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return status()


def status() -> dict:
    from gigamail.core.data_paths import app_root
    cfg = get_config()
    exe = cfg["command"][0]
    return {
        "available": _found(exe),
        "command": exe,
        "timeout": cfg["timeout"],
        "agent": cfg["agent"],
        "agents": available_agents(),
        "root": str(app_root()),
        # The Python running this backend: in the desktop app the bundled
        # one. The onboarding tells MCP clients to start the server with it
        # (-m gigamail.server), since gigamail-server is on no user's PATH.
        "python": sys.executable,
        "codex_model": codex_model(),
    }


# Limite pratico della riga di comando su Windows. CreateProcess si
# ferma a 32767 caratteri, ma un wrapper .cmd o .bat — ed e' cosi' che
# npm installa `claude` e `codex` — passa da cmd.exe, che si ferma a
# 8191. Si usa la soglia piu' bassa con un margine, perche' sbagliare per
# eccesso significa un processo che muore invece di una bozza.
_MAX_RIGA_COMANDO = 6000


def _riga_troppo_lunga(cmd: list) -> bool:
    return sum(len(a) + 3 for a in cmd) > _MAX_RIGA_COMANDO


def _va_a_capo(prompt: str) -> bool:
    """Un prompt su piu' righe non puo' viaggiare sulla riga di comando.

    npm installa `claude` e `codex` come wrapper .cmd, quindi CreateProcess
    li lancia attraverso cmd.exe, che la riga di comando la TRONCA al primo
    a capo. Non e' un errore: il processo parte, l'agente riceve la prima
    riga e basta. La bozza tornava con 'non vedo l'email a cui rispondere'
    e sembrava un problema del modello — invece identity, documenti e corpo
    della mail non erano mai usciti da qui."""
    return "\n" in (prompt or "") or "\r" in (prompt or "")


def _claude_config_dir() -> str:
    """Where Claude Code keeps its own state: CLAUDE_CONFIG_DIR, else ~/.claude."""
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def _claude_login_present() -> bool:
    """True when Claude Code holds a claude.ai login (a non-empty OAuth
    access token in its credentials file). Any problem reading the file
    counts as "no login": then nothing is taken away from the child."""
    path = os.path.join(_claude_config_dir(), ".credentials.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        return bool(isinstance(oauth, dict) and oauth.get("accessToken"))
    except Exception:
        return False


def _env_for_child(cfg: dict, quiet_desktop: bool = False) -> dict | None:
    """Environment for the agent process, or None to inherit ours as is.

    Claude Code gives ANTHROPIC_API_KEY precedence over the claude.ai
    login: with the key in the user's environment the drafts are billed
    per token on the API instead of the subscription, the account's
    connectors are disabled, and the CLI prints a warning in place of the
    draft. A user who keeps that key for other programs cannot remove it,
    so when Claude Code is the agent and a claude.ai login exists the key
    is dropped from the child's environment only. The key stays when
    there is no login (it is then the only way to authenticate) and when
    ANTHROPIC_BASE_URL points at a gateway that needs it."""
    env = None
    if (_agent_of(cfg) == "claude" and "ANTHROPIC_API_KEY" in os.environ
            and not os.environ.get("ANTHROPIC_BASE_URL") and _claude_login_present()):
        env = dict(os.environ)
        del env["ANTHROPIC_API_KEY"]
    server = _our_server()
    if server and not os.environ.get("GIGAMAIL_SERVER"):
        env = env if env is not None else dict(os.environ)
        env["GIGAMAIL_SERVER"] = server
    if quiet_desktop:
        # The agent bar shows its approval cards on screen: the desktop toast
        # for the same request was a duplicate. Telegram still notifies.
        env = env if env is not None else dict(os.environ)
        env["GIGAMAIL_NOTIFY_DESKTOP"] = "0"
    return env


def _our_server() -> str:
    """The gigamail-server of this very installation, next to the Python
    running the console's backend. The plugin starts
    ${GIGAMAIL_SERVER:-gigamail-server}: without this the agent launched by
    the console could run another GigaMail found on the PATH (an older pip
    install), whose tools answer differently from the console's code."""
    import sys
    folder = os.path.dirname(sys.executable)
    for name in ("gigamail-server.exe", "gigamail-server"):
        for cand in (os.path.join(folder, name), os.path.join(folder, "Scripts", name)):
            if os.path.isfile(cand):
                return cand
    return ""


def _error_excerpt(text: str, limit: int = 600) -> str:
    """The part of the agent's output that says why it failed. codex exec
    opens stderr with a header (version, model, sandbox, ...) longer than
    the message the console can show: cut to the first 400 characters, the
    user saw the header and never the error. From the first line that
    names an error, else the end of the output, where the reason is."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines)
                  if re.search(r"\b(ERROR|error|Error|failed|Failed)\b", ln)), None)
    body = "\n".join(lines[start:] if start is not None else lines)
    return body[-limit:]


def run(prompt: str, timeout: int | None = None, run_id: str | None = None,
        quiet_desktop: bool = False) -> str:
    """Esegue l'agente headless con il prompt e restituisce il testo prodotto."""
    cfg = get_config()
    cmd = list(cfg["command"])
    da_stdin = None
    spec = AGENTS.get(cfg.get("agent"))
    if spec and spec.get("stdin"):
        da_stdin = spec["stdin"](prompt)
    elif any("{prompt}" in a for a in cmd):
        pieno = [a.replace("{prompt}", prompt) for a in cmd]
        if _riga_troppo_lunga(pieno) or _va_a_capo(prompt):
            # Il prompt porta identity, listino e il corpo della mail:
            # su Windows una riga di comando cosi' sfonda il limite e il
            # processo muore con "La riga di comando e' troppo lunga".
            # Il segnaposto sparisce e il prompt entra da stdin, che
            # limiti non ne ha (claude -p e codex exec lo leggono da li').
            cmd = [a for a in cmd if "{prompt}" not in a]
            da_stdin = prompt.encode("utf-8")
        else:
            cmd = pieno
    elif _riga_troppo_lunga(cmd + [prompt]) or _va_a_capo(prompt):
        da_stdin = prompt.encode("utf-8")
    else:
        cmd.append(prompt)
    out_file = None
    if any("{output}" in a for a in cmd):
        fd, out_file = tempfile.mkstemp(prefix="gigamail-agent-", suffix=".txt")
        os.close(fd)
        cmd = [a.replace("{output}", out_file) for a in cmd]
    exe = cmd[0]
    if not _found(exe):
        # Le CLI si aggiornano da sole e cancellano la cartella della
        # versione precedente: un comando risolto poco prima punta a un
        # percorso che non esiste piu'. Prima di dichiarare l'agente
        # assente si prova a ri-risolverlo, altrimenti un aggiornamento
        # silenzioso ferma le bozze finche' qualcuno non se ne accorge —
        # e nessuno se ne accorge. Solo per un agente noto: se l'utente
        # ha configurato un comando suo e quello manca, sostituirglielo
        # di nascosto sarebbe peggio dell'errore.
        spec = AGENTS.get(_agent_of(cfg))
        fresco = spec["find"]() if spec else exe
        if spec and fresco != exe and _found(fresco):
            cmd[0] = exe = fresco
        else:
            if out_file:
                _unlink(out_file)
            example = '{"command": ["claude", "-p", "{prompt}"]}'
            raise AgentUnavailable(_say(
                f"Agente non trovato ('{exe}'). Installa Claude Code, l'app Codex / ChatGPT o Antigravity, "
                f"scegli l'agente dalla console (Automazioni), oppure configura il "
                f"comando in {_config_path()} (es. {example}).",
                f"Agent not found ('{exe}'). Install Claude Code, the Codex / ChatGPT app or Antigravity, "
                f"pick the agent in the console (Automations), or set the "
                f"command in {_config_path()} (e.g. {example})."))
    cwd = spec["cwd"]() if spec and spec.get("cwd") else None
    try:
        returncode, stdout, stderr = _spawn(
            cmd, da_stdin, timeout or cfg["timeout"], _env_for_child(cfg, quiet_desktop), run_id, cwd)
        # Codex refused the model: a `model = ...` pinned in config.toml (or
        # the default of this build) that the ChatGPT account cannot use.
        # Codex keeps the account's own list in models_cache.json: try those,
        # and remember the one that works, so the next run starts with it.
        if returncode != 0 and _agent_of(cfg) == "codex":
            err_text = (stderr or b"").decode("utf-8", errors="replace")
            if _MODEL_REFUSED.search(err_text):
                refused = re.search(r"['`\"]([\w.\-]+)['`\"] model", err_text)
                tried = {refused.group(1)} if refused else set()
                tried.add(codex_model())
                for cand in [m for m in _codex_models_available() if m not in tried][:3]:
                    if out_file:
                        open(out_file, "w").close()
                    returncode, stdout, stderr = _spawn(
                        _with_model(cmd, cand), da_stdin, timeout or cfg["timeout"],
                        _env_for_child(cfg, quiet_desktop), run_id, cwd)
                    if returncode == 0:
                        set_codex_model(cand)
                        break
                    if not _MODEL_REFUSED.search((stderr or b"").decode("utf-8", errors="replace")):
                        break
    except subprocess.TimeoutExpired as e:
        if out_file:
            _unlink(out_file)
        raise AgentUnavailable(_say(
            "L'agente non ha risposto entro il tempo massimo e si e' fermato.",
            "The agent did not answer in time and was stopped.")) from e
    except AgentCancelled:
        if out_file:
            _unlink(out_file)
        raise
    out = (stdout or b"").decode("utf-8", errors="replace").strip()
    if out_file:
        try:
            with open(out_file, encoding="utf-8", errors="replace") as f:
                finale = f.read().strip()
            if finale:
                out = finale
        except OSError:
            pass
        _unlink(out_file)
    err = (stderr or b"").decode("utf-8", errors="replace").strip()
    if returncode != 0:
        # Un'uscita con errore non e' una risposta, anche se ha scritto
        # qualcosa: Claude Code scollegato stampa "Not logged in · Please
        # run /login" su stdout ed esce con 1. Prima quel testo tornava
        # come se fosse la bozza, e sarebbe finito in approvazione come
        # corpo della mail a un cliente.
        raise AgentUnavailable(_say(
            f"Agente terminato con errore ({returncode}): {_error_excerpt(err or out)}",
            f"Agent ended with an error ({returncode}): {_error_excerpt(err or out)}"))
    if spec and spec.get("answer"):
        out = spec["answer"](out)
    if _non_collegato(out):
        raise AgentUnavailable(_say(f"Agente non collegato: {out[:200]}",
                                    f"Agent not signed in: {out[:200]}"))
    return out


_NON_COLLEGATO = ("not logged in", "please run /login", "invalid api key")


def _non_collegato(out: str) -> bool:
    """Un messaggio di login al posto della risposta. Solo su output brevi:
    una bozza vera che nomina il login non deve diventare un guasto."""
    testo = (out or "").strip().lower()
    return len(testo) < 200 and any(s in testo for s in _NON_COLLEGATO)


def _agent_of(cfg: dict) -> str:
    """L'agente di una configurazione; se manca la chiave (config di un
    chiamante esterno o vecchia), lo si deduce dal nome dell'eseguibile."""
    if cfg.get("agent") in AGENTS:
        return cfg["agent"]
    base = os.path.basename(str(cfg.get("command", [""])[0])).lower()
    for agent_id in AGENTS:
        if base.startswith(agent_id):
            return agent_id
    return "custom"


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
