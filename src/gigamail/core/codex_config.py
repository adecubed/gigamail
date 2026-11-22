"""The GigaMail entry in Codex's config.toml, written by the console.

Codex CLI, the Codex IDE extension and the ChatGPT desktop app (ChatGPT
Work included) read their MCP servers from the same file,
$CODEX_HOME/config.toml (default ~/.codex/config.toml). The plugin from the
OpenAI Plugins Directory brings only the skill; without a server entry the
user's own Codex and the ChatGPT desktop app have no GigaMail tools. (The
console's own Codex run does not depend on this file: it ignores the user's
configuration and carries GigaMail's server on its command line.) Typing `codex mcp add` with the right paths is
not something a desktop user should have to do, so the console writes it.

The entry starts this installation's Python with -m gigamail.server
(gigamail-server is on PATH only where an installer puts it, Windows and
the .deb; the full path works on every install) and sets GIGAMAIL_ROOT to the
console's data folder, so server and console share accounts and approvals.
default_tools_approval_mode = "approve": `codex exec`, which the console's
agent bar runs, cannot ask for a confirmation and cancels every tool call
that needs one ("user cancelled MCP tool call"). Codex's own prompt adds
nothing here: GigaMail's tools that send, delete or write the calendar stay
two-phase on the server, and only a human approval in GigaMail runs them.

Only the [mcp_servers.gigamail] table and its sub-tables are touched. The
new file is parsed before it is written: if anything outside our entry
would change, nothing is written. The previous file is kept next to it as
config.toml.gigamail-bak.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: same parser, as a package
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

NAME = "gigamail"
_HEADER = re.compile(r'^\s*\[\s*mcp_servers\s*\.\s*(?:gigamail|"gigamail")\s*(?:\.[^\]]*)?\]\s*(?:#.*)?$')
_ANY_HEADER = re.compile(r"^\s*\[")


def config_path() -> Path:
    home = os.environ.get("CODEX_HOME", "").strip()
    return Path(home) if home else Path.home() / ".codex"


def _file() -> Path:
    return config_path() / "config.toml"


def desired() -> dict:
    from gigamail.core.data_paths import app_root
    return {
        "command": sys.executable,
        "args": ["-m", "gigamail.server"],
        "env": {"GIGAMAIL_ROOT": str(app_root())},
        "default_tools_approval_mode": "approve",
    }


def _q(value: str) -> str:
    """A TOML basic string: the JSON escapes are valid TOML."""
    import json
    return json.dumps(str(value), ensure_ascii=False)


def _block(entry: dict) -> str:
    args = ", ".join(_q(a) for a in entry["args"])
    env = "".join(f"{k} = {_q(v)}\n" for k, v in entry["env"].items())
    return (f"[mcp_servers.{NAME}]\n"
            f"command = {_q(entry['command'])}\n"
            f"args = [{args}]\n"
            f"default_tools_approval_mode = {_q(entry['default_tools_approval_mode'])}\n\n"
            f"[mcp_servers.{NAME}.env]\n{env}")


def _without_entry(text: str) -> str:
    """The file without our tables: from each [mcp_servers.gigamail...]
    header to the next table header."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if _HEADER.match(line):
            skipping = True
            continue
        if skipping and _ANY_HEADER.match(line):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def _parse(text: str) -> dict:
    if tomllib is None:
        raise RuntimeError("Python 3.11+ needed to check config.toml")
    return tomllib.loads(text)


def _strip_ours(data: dict) -> dict:
    data = dict(data)
    servers = dict(data.get("mcp_servers") or {})
    servers.pop(NAME, None)
    if servers:
        data["mcp_servers"] = servers
    else:
        data.pop("mcp_servers", None)
    return data


def _matches(current: dict, want: dict) -> bool:
    return (current.get("command") == want["command"]
            and list(current.get("args") or []) == want["args"]
            and (current.get("env") or {}).get("GIGAMAIL_ROOT") == want["env"]["GIGAMAIL_ROOT"]
            and current.get("default_tools_approval_mode") == want["default_tools_approval_mode"])


def status() -> dict:
    """Whether config.toml already starts this installation's server."""
    path = _file()
    out = {"path": str(path), "exists": path.exists(), "connected": False,
           "entry": None, "error": ""}
    if not path.exists():
        return out
    try:
        current = (_parse(path.read_text(encoding="utf-8")).get("mcp_servers") or {}).get(NAME)
    except Exception as e:  # unreadable file: say so, do not guess
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    if isinstance(current, dict):
        out["entry"] = {"command": current.get("command"), "args": current.get("args") or []}
        out["connected"] = _matches(current, desired())
    return out


def plugin_installed() -> bool:
    """Whether Codex holds a GigaMail plugin from any marketplace: Codex
    keeps installed plugins in $CODEX_HOME/plugins/cache/<marketplace>/<name>/."""
    cache = config_path() / "plugins" / "cache"
    try:
        return any((m / NAME).is_dir() for m in cache.iterdir() if m.is_dir())
    except OSError:
        return False


def connect_for_plugin() -> str:
    """Write our entry when the user has installed the GigaMail plugin in
    Codex and config.toml has no gigamail server yet.

    The plugin from the OpenAI Plugins Directory brings only the skill, and
    the one from the repository marketplace starts `gigamail-server`, which
    macOS, AppImage and older Windows installs do not have on PATH: either
    way Codex has no GigaMail tools until something writes the entry, and installing the plugin is the user
    asking for them. An entry that is already there, ours or another
    installation's (a pip install, a hand-written one), is left alone.
    Returns what happened, for the log."""
    if not plugin_installed():
        return "no plugin"
    st = status()
    if st["error"]:
        return f"config.toml unreadable: {st['error']}"
    if st["connected"]:
        return "already connected"
    if st["entry"]:
        return "entry points to another GigaMail: left alone"
    connect()
    return "connected"


def codex_present() -> bool:
    """Whether this user has Codex or the ChatGPT desktop app: both keep
    their settings in $CODEX_HOME, and neither works without it."""
    return config_path().is_dir()


def _once_marker() -> Path:
    from gigamail.core.data_paths import app_root
    return app_root() / ".codex_connected_at_start"


def connect_at_start() -> str:
    """What the console does about Codex when it starts.

    With the GigaMail plugin installed: connect_for_plugin(), at every
    start. Without it, when Codex is on this computer and config.toml has
    no gigamail server: write our entry, once. Somebody who installed
    GigaMail first and adds the plugin later, the common order for a user
    who finds it in the OpenAI Plugins Directory, then has the tools without
    coming back to the console: when they last opened it there was no
    plugin to see. Once, because an entry the user later removes by hand
    must stay removed; the Connect button and installing the plugin still
    write it. Returns what happened, for the log."""
    if plugin_installed():
        return connect_for_plugin()
    if not codex_present():
        return "no Codex"
    marker = _once_marker()
    if marker.exists():
        return "no plugin, entry already offered once"
    st = status()
    if st["error"]:
        return f"config.toml unreadable: {st['error']}"
    if st["connected"]:
        result = "already connected"
    elif st["entry"]:
        result = "entry points to another GigaMail: left alone"
    else:
        connect()
        result = "connected (Codex found, no plugin yet)"
    marker.write_text("", encoding="utf-8")
    return result


def connect() -> dict:
    """Write (or replace) our entry. Raises ValueError, writing nothing, when
    the result would change anything else in the file."""
    path = _file()
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    before = _parse(old) if old.strip() else {}
    base = _without_entry(old)
    if base and not base.endswith("\n"):
        base += "\n"
    want = desired()
    new = base + ("\n" if base.strip() else "") + _block(want)
    try:
        after = _parse(new)
    except Exception as e:
        raise ValueError(
            f"{path} defines the gigamail server in a form GigaMail cannot edit "
            f"safely ({type(e).__name__}). Remove that entry and try again.") from e
    if _strip_ours(after) != _strip_ours(before):
        raise ValueError(f"editing {path} would change other settings: nothing written")
    if not _matches((after.get("mcp_servers") or {}).get(NAME) or {}, want):
        raise ValueError(f"the gigamail entry in {path} did not come out as expected: nothing written")
    path.parent.mkdir(parents=True, exist_ok=True)
    if old:
        Path(str(path) + ".gigamail-bak").write_text(old, encoding="utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".toml")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(tmp, path)
    return status()
