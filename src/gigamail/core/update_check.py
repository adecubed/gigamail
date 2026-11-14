# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Tell the user when a newer GigaMail is out, also where nothing updates
by itself.

The desktop app updates when its console is opened. An install from pip,
or a desktop install used only through the MCP server (from Claude Code,
Codex...), never opens the console: it stays on the version installed
until the user updates by hand, and nothing told them a new one was out.

So the MCP server looks up the latest version at most once a day, in the
background, and keeps the answer in a small file. When a newer version
is known, the server's instructions say so to the agent, with how to
update for this kind of install, and the CLI prints one line for the
human. Nothing is installed by itself: the user decides.

The lookup goes to PyPI for a pip install and to the GitHub releases for
the desktop app, whose updater reads them too. It sends nothing about
the user or the mail. With no network it fails quietly and is tried
again the next day. GIGAMAIL_NO_UPDATE_CHECK=1 switches it off.
"""
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

PYPI_URL = "https://pypi.org/pypi/gigamail/json"
GITHUB_URL = "https://api.github.com/repos/adecubed/gigamail/releases/latest"
CHECK_EVERY = 24 * 3600
TIMEOUT = 5
_CACHE_NAME = "update_check.json"


def enabled() -> bool:
    return os.environ.get("GIGAMAIL_NO_UPDATE_CHECK", "").strip().lower() not in ("1", "true", "yes")


def install_kind(executable: str | None = None) -> str:
    """"desktop" when this Python is the one bundled with the desktop app
    (it lives in the app's resources/python folder on every system),
    "pip" otherwise. GIGAMAIL_INSTALL_KIND overrides it."""
    forced = os.environ.get("GIGAMAIL_INSTALL_KIND", "").strip().lower()
    if forced in ("desktop", "pip"):
        return forced
    parts = [p.lower() for p in re.split(r"[\\/]+", executable or sys.executable) if p]
    for a, b in zip(parts, parts[1:], strict=False):
        if a == "resources" and b == "python":
            return "desktop"
    return "pip"


def _cache_path() -> Path:
    from gigamail.core import data_paths
    return data_paths.cache_dir() / _CACHE_NAME


def _read_cache() -> dict:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(data: dict) -> None:
    try:
        path = _cache_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _parse(v: str) -> tuple:
    """"0.6.10" > "0.6.9"; a leading "v" and anything after the numbers
    (rc1, +local) are ignored. Unreadable = (0,)."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", str(v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def newer(latest: str, current: str) -> bool:
    """latest is above current; an unknown current version (0.0.0, a
    source checkout without metadata) never is behind."""
    cur = _parse(current)
    return any(cur) and _parse(latest) > cur


def fetch_latest(kind: str) -> str | None:
    """The latest version for this kind of install, None when it cannot
    be read (no network, rate limit, unexpected answer)."""
    import requests
    try:
        if kind == "desktop":
            r = requests.get(GITHUB_URL, timeout=TIMEOUT,
                             headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            tag = str(r.json().get("tag_name") or "")
        else:
            r = requests.get(PYPI_URL, timeout=TIMEOUT)
            r.raise_for_status()
            tag = str((r.json().get("info") or {}).get("version") or "")
    except Exception:
        return None
    tag = tag.strip().lstrip("v")
    return tag if re.match(r"\d+(\.\d+)*", tag) else None


def refresh(now: float | None = None) -> None:
    """Look up the latest version if the last look is older than a day,
    and keep it. A failed look is kept too, so it is not retried before
    the next day."""
    if not enabled():
        return
    now = time.time() if now is None else now
    kind = install_kind()
    cache = _read_cache()
    if cache.get("kind") == kind and now - float(cache.get("checked_at") or 0) < CHECK_EVERY:
        return
    latest = fetch_latest(kind)
    if latest is None and cache.get("kind") == kind:
        latest = cache.get("latest")  # keep what was known before
    _write_cache({"checked_at": now, "kind": kind, "latest": latest})


def refresh_in_background() -> None:
    """refresh() in a thread that never holds the server up."""
    if enabled():
        threading.Thread(target=refresh, name="gigamail-update-check", daemon=True).start()


def available(current: str) -> str | None:
    """The newer version known for this install, None when there is none."""
    if not enabled():
        return None
    cache = _read_cache()
    if cache.get("kind") != install_kind():
        return None
    latest = str(cache.get("latest") or "")
    return latest if latest and newer(latest, current) else None


def agent_notice(current: str) -> str:
    """One paragraph for the MCP server's instructions, "" when up to
    date. It is for the agent, so it is in English."""
    latest = available(current)
    if not latest:
        return ""
    how = ("opening the GigaMail desktop app once installs it" if install_kind() == "desktop"
           else "update with: pip install -U gigamail")
    return (f" UPDATE: GigaMail {latest} is available (this install runs {current}). "
            f"Tell the user once, in their language, at a natural moment: {how}. "
            "Do not update anything yourself.")


def user_line(current: str, lang: str = "en") -> str:
    """One line for the human in the CLI, "" when up to date."""
    latest = available(current)
    if not latest:
        return ""
    desktop = install_kind() == "desktop"
    if lang == "it":
        how = "apri l'app GigaMail per installarla" if desktop else "aggiorna con: pip install -U gigamail"
        return f"È disponibile GigaMail {latest} (questa installazione è la {current}): {how}."
    how = "open the GigaMail app to install it" if desktop else "update with: pip install -U gigamail"
    return f"GigaMail {latest} is available (this install runs {current}): {how}."
