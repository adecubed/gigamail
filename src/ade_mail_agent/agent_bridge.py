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
import json
import os
import shutil
import subprocess
import tempfile

DEFAULT_TIMEOUT = 180


class AgentUnavailable(Exception):
    pass


def _found(exe: str) -> bool:
    return bool(exe) and (shutil.which(exe) is not None or os.path.exists(exe))


def _find_claude() -> str:
    """Trova la CLI di Claude Code: PATH, oppure l'installazione versionata
    piu' recente dell'app desktop (%APPDATA%/Claude/claude-code/<ver>/claude.exe)."""
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    base = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code")
    try:
        versions = [d for d in os.listdir(base)
                    if os.path.exists(os.path.join(base, d, "claude.exe"))]
        if versions:
            newest = max(versions, key=lambda v: [int(x) for x in v.split(".") if x.isdigit()])
            return os.path.join(base, newest, "claude.exe")
    except Exception:
        pass
    return "claude"  # lasciamo che il chiamante segnali l'assenza


def _find_codex() -> str:
    """Trova Codex CLI: PATH (npm mette codex.cmd in %APPDATA%/npm), oppure
    quella cartella direttamente, se il processo non ha ereditato il PATH."""
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    for name in ("codex.cmd", "codex"):
        cand = os.path.join(os.environ.get("APPDATA", ""), "npm", name)
        if os.path.exists(cand):
            return cand
    return "codex"


def _cmd_claude(exe: str) -> list:
    # "mcp__ade-mail" a livello server: consente tutti i tool del server MCP
    # ade-mail (i DANGEROUS restano comunque a due fasi lato server).
    return [exe, "-p", "{prompt}", "--allowedTools", "mcp__ade-mail"]


def _cmd_codex(exe: str) -> list:
    # exec = non interattivo. Sandbox in sola lettura: l'agente scrive la
    # bozza, non tocca il disco; --skip-git-repo-check perche' la cartella di
    # lavoro della console non e' un repository. La risposta finale va in un
    # file ({output}): su stdout Codex stampa anche il resto della sessione.
    return [exe, "exec", "--skip-git-repo-check", "-s", "read-only",
            "--color", "never", "-o", "{output}", "{prompt}"]


# Agenti che la console sa riconoscere da sola. L'ordine e' quello del default.
# `find` passa dal nome del modulo a ogni chiamata (lambda), non da un
# riferimento preso all'import: cosi' i test possono sostituire _find_claude
# e la ri-risoluzione dopo un aggiornamento usa davvero la funzione nuova.
AGENTS = {
    "claude": {"label": "Claude Code", "find": lambda: _find_claude(), "command": _cmd_claude,
               "mcp": "json"},
    "codex": {"label": "Codex CLI", "find": lambda: _find_codex(), "command": _cmd_codex,
              "mcp": "toml"},
}


def _config_path() -> str:
    from ade_mail_agent.core.data_paths import app_root
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
    """{"command": [...], "timeout": int, "agent": "claude"|"codex"|"custom"}"""
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
    from ade_mail_agent.core.data_paths import app_root
    cfg = get_config()
    exe = cfg["command"][0]
    return {
        "available": _found(exe),
        "command": exe,
        "timeout": cfg["timeout"],
        "agent": cfg["agent"],
        "agents": available_agents(),
        "root": str(app_root()),
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


def run(prompt: str, timeout: int | None = None) -> str:
    """Esegue l'agente headless con il prompt e restituisce il testo prodotto."""
    cfg = get_config()
    cmd = list(cfg["command"])
    da_stdin = None
    if any("{prompt}" in a for a in cmd):
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
            raise AgentUnavailable(
                f"Agente non trovato ('{exe}'). Installa Claude Code o Codex CLI, "
                f"scegli l'agente dalla console (Automazioni), oppure configura il "
                f"comando in {_config_path()} "
                '(es. {"command": ["claude", "-p", "{prompt}"]}).'
            )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            input=da_stdin,
            stdin=None if da_stdin is not None else subprocess.DEVNULL,
            timeout=timeout or cfg["timeout"],
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        if out_file:
            _unlink(out_file)
        raise AgentUnavailable("L'agente non ha risposto entro il timeout.") from e
    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if out_file:
        try:
            with open(out_file, encoding="utf-8", errors="replace") as f:
                finale = f.read().strip()
            if finale:
                out = finale
        except OSError:
            pass
        _unlink(out_file)
    if proc.returncode != 0 and not out:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise AgentUnavailable(f"Agente terminato con errore: {err[:400]}")
    return out


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
