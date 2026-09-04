# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Ponte console → agente.

Quello che nella vecchia app era delegato all'LLM interno (llm.py) qui viene
delegato all'AGENTE dell'utente: la console inoltra l'istruzione ("scrivi la
bozza", "trova le mail di...") a un agente headless — di default Claude Code
in modalita' -p — che ha gia' i tool MCP ade-mail e quindi puo' cercare,
leggere e ragionare sulla posta con la conoscenza dell'account.

Configurazione (in ordine di precedenza):
1. env ADE_AGENT_CMD — JSON array, es. ["claude","-p","{prompt}"]
2. %APPDATA%/ADE/agent.json — {"command": [...], "timeout": 180}
3. default: ["claude", "-p", "{prompt}", "--allowedTools", "mcp__ade-mail__*"]

Il placeholder {prompt} viene sostituito con l'istruzione; se assente, il
prompt viene appeso come ultimo argomento.
"""
import json
import os
import shutil
import subprocess

DEFAULT_TIMEOUT = 180


class AgentUnavailable(Exception):
    pass


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


def _default_command() -> list:
    # "mcp__ade-mail" a livello server: consente tutti i tool del server MCP
    # ade-mail (i DANGEROUS restano comunque a due fasi lato server).
    return [_find_claude(), "-p", "{prompt}", "--allowedTools", "mcp__ade-mail"]


def _config_path() -> str:
    from ade_mail_agent.core.data_paths import app_root
    return os.path.join(str(app_root()), "agent.json")


def get_config() -> dict:
    env_cmd = os.environ.get("ADE_AGENT_CMD", "")
    if env_cmd:
        try:
            return {"command": json.loads(env_cmd), "timeout": DEFAULT_TIMEOUT}
        except Exception:
            pass
    try:
        with open(_config_path(), encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg.get("command"), list) and cfg["command"]:
            cfg.setdefault("timeout", DEFAULT_TIMEOUT)
            return cfg
    except Exception:
        pass
    return {"command": _default_command(), "timeout": DEFAULT_TIMEOUT}


def status() -> dict:
    cfg = get_config()
    exe = cfg["command"][0]
    found = shutil.which(exe) is not None or os.path.exists(exe)
    return {"available": found, "command": cfg["command"][0], "timeout": cfg["timeout"]}


# Limite pratico della riga di comando su Windows. CreateProcess si
# ferma a 32767 caratteri, ma un wrapper .cmd o .bat — ed e' cosi' che
# npm installa `claude` — passa da cmd.exe, che si ferma a 8191. Si usa
# la soglia piu' bassa con un margine, perche' sbagliare per eccesso
# significa un processo che muore invece di una bozza.
_MAX_RIGA_COMANDO = 6000


def _riga_troppo_lunga(cmd: list) -> bool:
    return sum(len(a) + 3 for a in cmd) > _MAX_RIGA_COMANDO


def run(prompt: str, timeout: int | None = None) -> str:
    """Esegue l'agente headless con il prompt e restituisce il testo prodotto."""
    cfg = get_config()
    cmd = list(cfg["command"])
    da_stdin = None
    if any("{prompt}" in a for a in cmd):
        pieno = [a.replace("{prompt}", prompt) for a in cmd]
        if _riga_troppo_lunga(pieno):
            # Il prompt porta identity, listino e il corpo della mail:
            # su Windows una riga di comando cosi' sfonda il limite e il
            # processo muore con "La riga di comando e' troppo lunga".
            # Il segnaposto sparisce e il prompt entra da stdin, che
            # limiti non ne ha.
            cmd = [a for a in cmd if "{prompt}" not in a]
            da_stdin = prompt.encode("utf-8")
        else:
            cmd = pieno
    else:
        cmd.append(prompt)
    exe = cmd[0]
    if shutil.which(exe) is None and not os.path.exists(exe):
        # Claude Code si aggiorna da solo e cancella la cartella della
        # versione precedente: un comando risolto poco prima punta a un
        # percorso che non esiste piu'. Prima di dichiarare l'agente
        # assente si prova a ri-risolverlo, altrimenti un
        # aggiornamento silenzioso ferma le bozze finche' qualcuno non
        # se ne accorge — e nessuno se ne accorge.
        # Solo per un comando che avremmo risolto noi: se l'utente ha
        # configurato un agente suo e quello manca, sostituirglielo di
        # nascosto con un altro sarebbe peggio dell'errore. Meglio dire
        # che il SUO comando non c'e'.
        nostro = os.path.basename(exe).lower().startswith("claude")
        fresco = _find_claude() if nostro else exe
        if nostro and fresco != exe and (shutil.which(fresco) is not None
                                         or os.path.exists(fresco)):
            cmd[0] = exe = fresco
        else:
            raise AgentUnavailable(
                f"Agente non trovato ('{exe}'). Installa Claude Code oppure configura "
                f"il comando in {_config_path()} "
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
        raise AgentUnavailable("L'agente non ha risposto entro il timeout.") from e
    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 and not out:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise AgentUnavailable(f"Agente terminato con errore: {err[:400]}")
    return out
