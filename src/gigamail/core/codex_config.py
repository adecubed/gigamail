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

The installers write an entry too, so that the plugin finds its server on
a computer where the console has not started since Codex or the plugin
arrived. The Windows installer, for a per-user install, does what the
console does at its start (`at-install`). The Linux .deb, which runs as
root and belongs to every user of the machine, writes Codex's system file
/etc/codex/config.toml (`system-connect`): Codex reads it under the user's
own config.toml, so an entry the console or the user writes later wins.
That entry names the installed gigamail-server and no data folder: each
user's server finds their own.

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
SYSTEM_FILE = Path("/etc/codex/config.toml")
# What a system-wide entry lets through from the user's environment: where
# their data is, when they moved it.
SYSTEM_ENV_VARS = ["GIGAMAIL_ROOT", "ADE_ROOT"]
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
    out = (f"[mcp_servers.{NAME}]\n"
           f"command = {_q(entry['command'])}\n"
           f"args = [{args}]\n")
    if entry.get("env_vars"):
        out += f"env_vars = [{', '.join(_q(v) for v in entry['env_vars'])}]\n"
    out += f"default_tools_approval_mode = {_q(entry['default_tools_approval_mode'])}\n"
    if entry.get("env"):
        env = "".join(f"{k} = {_q(v)}\n" for k, v in entry["env"].items())
        out += f"\n[mcp_servers.{NAME}.env]\n{env}"
    return out


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
    """In Codex's own folder, not in GigaMail's data: one GigaMail can serve
    several Codex profiles (CODEX_HOME), and each must get its entry."""
    return config_path() / ".gigamail_connected_at_start"


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


def _write_entry(path: Path, want: dict, matches) -> None:
    """Write (or replace) the gigamail entry in `path`. Raises ValueError,
    writing nothing, when the result would change anything else in the file.

    The file keeps the permissions it had, and so does the copy kept next
    to it: a config.toml can hold other servers' keys, and one its owner
    closed to other users must not come back readable by them."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    mode = (path.stat().st_mode & 0o777) if path.exists() else None
    before = _parse(old) if old.strip() else {}
    base = _without_entry(old)
    if base and not base.endswith("\n"):
        base += "\n"
    new = base + ("\n" if base.strip() else "") + _block(want)
    try:
        after = _parse(new)
    except Exception as e:
        raise ValueError(
            f"{path} defines the gigamail server in a form GigaMail cannot edit "
            f"safely ({type(e).__name__}). Remove that entry and try again.") from e
    if _strip_ours(after) != _strip_ours(before):
        raise ValueError(f"editing {path} would change other settings: nothing written")
    if not matches((after.get("mcp_servers") or {}).get(NAME) or {}, want):
        raise ValueError(f"the gigamail entry in {path} did not come out as expected: nothing written")
    path.parent.mkdir(parents=True, exist_ok=True)
    if old:
        bak = str(path) + ".gigamail-bak"
        fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        os.chmod(bak, mode)  # a copy left by an earlier write keeps its old mode otherwise
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(old)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".toml")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def connect() -> dict:
    """Write (or replace) our entry in the user's config.toml. Raises
    ValueError, writing nothing, when the result would change anything else
    in the file."""
    _write_entry(_file(), desired(), _matches)
    return status()


def system_desired(command: str) -> dict:
    return {
        "command": command,
        "args": [],
        "env_vars": list(SYSTEM_ENV_VARS),
        "default_tools_approval_mode": "approve",
    }


def _system_matches(current: dict, want: dict) -> bool:
    return (current.get("command") == want["command"]
            and list(current.get("args") or []) == want["args"]
            and list(current.get("env_vars") or []) == want["env_vars"]
            and current.get("default_tools_approval_mode") == want["default_tools_approval_mode"])


def connect_system(command: str, path: Path | None = None) -> str:
    """Write the machine-wide entry that starts `command`, the installed
    gigamail-server, for every user: run as root by the .deb's postinst.

    Written whether or not Codex is installed: the file is ready when it
    arrives. A gigamail entry that starts something else was put there by
    an administrator and is left alone. A file this creates is readable by
    everyone, as a system configuration must be (a temporary file is born
    private); one that was already there keeps its permissions. Returns
    what happened, for the installer's output."""
    path = path or SYSTEM_FILE
    want = system_desired(command)
    if path.exists():
        try:
            current = (_parse(path.read_text(encoding="utf-8")).get("mcp_servers") or {}).get(NAME)
        except Exception as e:
            return f"{path} unreadable, left alone: {type(e).__name__}: {e}"
        if isinstance(current, dict):
            if current.get("command") != command:
                return "entry points to another GigaMail: left alone"
            if _system_matches(current, want):
                return "already connected"
    created = not path.exists()
    _write_entry(path, want, _system_matches)
    if created:
        os.chmod(path, 0o644)
    return f"connected in {path}"


def main(argv: list[str]) -> int:
    """For the installers. Never fails them: a Codex entry that could not be
    written is said and left to the console's start."""
    try:
        if argv == ["at-install"]:
            print(f"Codex: {connect_at_start()}")
        elif len(argv) == 2 and argv[0] == "system-connect":
            print(f"Codex: {connect_system(argv[1])}")
        else:
            print("usage: python -m gigamail.core.codex_config at-install | system-connect <gigamail-server path>")
            return 2
    except Exception as e:
        print(f"Codex: entry not written: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
