# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Fingerprint of the package's sources on disk: how many .py files and
the newest modification time. It changes when an update, or an edit,
replaces the code a running process loaded: the backend reports itself
stale, and the watcher is restarted with the new code."""
from pathlib import Path


def code_stamp() -> str:
    import gigamail
    newest, count = 0, 0
    for path in Path(gigamail.__file__).parent.rglob("*.py"):
        try:
            modified = path.stat().st_mtime_ns
        except OSError:
            continue
        count += 1
        newest = max(newest, modified)
    return f"{count}-{newest}"
