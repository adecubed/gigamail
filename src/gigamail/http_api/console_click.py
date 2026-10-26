# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Telling a click in the console apart from any other caller.

The console token (X-ADE-Token) sits in a file that every process of the
user can read, an agent with a shell included: it authenticates a process,
not a person. So every send from the console asked Windows Hello / Touch ID,
even when the person was clicking Send.

The console's main process now makes a secret at every launch, keeps it in
memory only, hands it to the backend it starts over stdin (never on disk,
never in the environment) and adds it as X-ADE-Human to the requests of its
own windows. A request that carries it is a click in the console and sends
without the OS prompt; every other caller (the agent, a script holding the
token file) still goes through the OS verification.

What this does not stop: a local program able to read another process's
memory. That is the remaining gap SECURITY.md describes.
"""
import hmac
import os
import sys

HEADER = "X-ADE-Human"
STDIN_FLAG = "ADE_CONSOLE_HUMAN_STDIN"
ENV_NAME = "ADE_CONSOLE_HUMAN"
_MIN_LEN, _MAX_LEN = 32, 256

_secret = ""


def set_secret(value: str) -> None:
    global _secret
    value = (value or "").strip()
    _secret = value if _MIN_LEN <= len(value) <= _MAX_LEN else ""


def has_secret() -> bool:
    return bool(_secret)


def is_console_click(headers) -> bool:
    """True when the request carries the secret of the console that started
    this backend. Without a secret nothing is a console click."""
    if not _secret:
        return False
    given = (headers.get(HEADER) or "") if headers is not None else ""
    return bool(given) and hmac.compare_digest(given.encode(), _secret.encode())


# The user's choice: whether a click in the console still asks the OS prompt
# before sending. Off by default. It only decides for requests that carry the
# click secret: any other caller meets the prompt whatever it says.
SETTING_KEY = "console_send_requires_hello"


def send_requires_hello() -> bool:
    from gigamail.core import accounts
    try:
        return accounts.get_setting(SETTING_KEY, "0") == "1"
    except Exception:
        return True   # cannot read the choice: keep the stricter behaviour


def set_send_requires_hello(enabled: bool) -> None:
    from gigamail.core import accounts
    accounts.set_setting(SETTING_KEY, "1" if enabled else "0")


def read_from_stdin(stream=None) -> str:
    """The secret the console writes on stdin, read only when the console
    says it sends one (otherwise a backend started by hand would wait on the
    keyboard)."""
    if os.environ.get(STDIN_FLAG) != "1":
        return ""
    stream = stream if stream is not None else sys.stdin
    try:
        line = stream.readline() if stream is not None else ""
    except Exception:
        return ""
    value = (line or "").strip()
    return value if _MIN_LEN <= len(value) <= _MAX_LEN else ""


def read_from_env() -> str:
    """The secret the console also puts in the backend's environment. It is
    removed from os.environ here, at start, so no process the backend
    launches later (the agent, a draft) inherits it."""
    value = (os.environ.pop(ENV_NAME, "") or "").strip()
    return value if _MIN_LEN <= len(value) <= _MAX_LEN else ""
