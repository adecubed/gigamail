"""GigaMail's entries in Google Antigravity's config, written by the console.

Antigravity (the IDE and the agy CLI) reads its MCP servers from
~/.gemini/config/mcp_config.json. The console's agent bar runs `agy` in
headless mode, where a tool that would ask for a permission is soft-denied:
GigaMail's tools default to Ask, so the agent would have none of them. The
rule mcp(gigamail/*) in ~/.gemini/antigravity-cli/settings.json lets them
through. Antigravity's own prompt adds nothing here: GigaMail's tools that
send, delete or write the calendar stay two-phase on the server, and only a
human approval in GigaMail runs them.

The server entry starts this installation's Python with -m gigamail.server
(gigamail-server is on no desktop user's PATH) and sets GIGAMAIL_ROOT to the
console's data folder, so server and console share accounts and approvals.

Only mcpServers.gigamail and one rule in permissions.allow are touched; the
rest of each file is kept as it is. A file that is not plain JSON is left
alone (ValueError). The previous file is kept next to it with the suffix
.gigamail-bak.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

NAME = "gigamail"
RULE = f"mcp({NAME}/*)"


def gemini_dir() -> Path:
    return Path.home() / ".gemini"


def mcp_file() -> Path:
    return gemini_dir() / "config" / "mcp_config.json"


def settings_file() -> Path:
    return gemini_dir() / "antigravity-cli" / "settings.json"


def desired() -> dict:
    from gigamail.core.data_paths import app_root
    return {
        "command": sys.executable,
        "args": ["-m", "gigamail.server"],
        "env": {"GIGAMAIL_ROOT": str(app_root())},
    }


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{path} is not plain JSON ({e}): nothing written") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object: nothing written")
    return data


def _matches(current, want: dict) -> bool:
    return (isinstance(current, dict)
            and current.get("command") == want["command"]
            and list(current.get("args") or []) == want["args"]
            and (current.get("env") or {}).get("GIGAMAIL_ROOT") == want["env"]["GIGAMAIL_ROOT"])


def _allowed(settings: dict) -> bool:
    allow = (settings.get("permissions") or {}).get("allow")
    return isinstance(allow, list) and RULE in allow


def status() -> dict:
    """Whether Antigravity starts this installation's server and lets the
    headless agent call its tools."""
    out = {"mcp_path": str(mcp_file()), "settings_path": str(settings_file()),
           "registered": False, "allowed": False, "connected": False, "error": ""}
    try:
        servers = _load(mcp_file()).get("mcpServers") or {}
        out["registered"] = _matches(servers.get(NAME), desired())
        out["allowed"] = _allowed(_load(settings_file()))
    except Exception as e:  # unreadable file: say so, do not guess
        out["error"] = f"{type(e).__name__}: {e}"
    out["connected"] = out["registered"] and out["allowed"]
    return out


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        Path(str(path) + ".gigamail-bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def connect() -> dict:
    """Write our server entry and our permission rule. Raises ValueError,
    writing nothing, when either file cannot be edited safely."""
    mcp = _load(mcp_file())
    settings = _load(settings_file())
    servers = mcp.get("mcpServers", {})
    permissions = settings.get("permissions", {})
    if not isinstance(servers, dict) or not isinstance(permissions, dict) \
            or not isinstance(permissions.get("allow", []), list):
        raise ValueError("Antigravity's config has an unexpected shape: nothing written")
    want = desired()
    if not _matches(servers.get(NAME), want):
        mcp["mcpServers"] = {**servers, NAME: want}
        _write(mcp_file(), mcp)
    if not _allowed(settings):
        settings["permissions"] = {**permissions, "allow": list(permissions.get("allow", [])) + [RULE]}
        _write(settings_file(), settings)
    return status()
