# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""What the agent will not read well in a document, said before it matters.

A rule answers from its documents. A price list too long to go in whole,
a workbook whose old sheets sit next to the current one, a floor plan
that is only a picture: each of them gave a wrong or empty draft weeks
after the document was attached, and nothing had said so. check() reads a
document the way a draft does and returns notes a person can act on.
"""
import os
import time
from typing import Any, Dict, List, Tuple

from . import file_extractor

# How much of one document a draft's prompt takes. Longer than this, the
# agent gets the beginning and the passages that match the mail.
PROMPT_DOC_CHARS = 30000
SLOW_SECONDS = 5.0
SHEET_MARK = "[Foglio: "

TOO_LONG = "too_long"
SHEETS = "sheets"
NO_TEXT = "no_text"
UNREADABLE = "unreadable"
SLOW = "slow"

_cache: Dict[Tuple[str, int, int], Dict[str, Any]] = {}


def _sheet_names(text: str) -> List[str]:
    return [line[len(SHEET_MARK):].rstrip("]") for line in text.splitlines()
            if line.startswith(SHEET_MARK) and line.endswith("]")]


def check(path: str) -> Dict[str, Any]:
    """{"path", "name", "chars", "notes": [{"code", ...}]} for one file.

    Notes, each with the numbers a message needs:
      unreadable  the file could not be read at all ("detail")
      no_text     read, but there is no text in it (a scanned page, a
                  drawing): the agent can attach it, not read it
      too_long    more text than a prompt takes ("chars", "limit")
      sheets      a workbook with several sheets ("names"): the agent
                  reads them all, the outdated ones too
      slow        reading it took long ("seconds"): every draft waits
    The result is kept until the file changes."""
    path = os.path.abspath(str(path))
    out: Dict[str, Any] = {"path": path, "name": os.path.basename(path),
                           "chars": 0, "notes": []}
    try:
        st = os.stat(path)
    except OSError as e:
        out["notes"].append({"code": UNREADABLE, "detail": str(e)[:200]})
        return out
    key = (path, st.st_mtime_ns, st.st_size)
    if key in _cache:
        return _cache[key]
    started = time.time()
    try:
        text, kind = file_extractor.extract_text(path)
        text = str(text or "")
    except Exception as e:
        out["notes"].append({"code": UNREADABLE, "detail": str(e)[:200]})
        _cache[key] = out
        return out
    seconds = time.time() - started
    out["chars"] = len(text)
    if not text.strip():
        out["notes"].append({"code": NO_TEXT})
    if len(text) > PROMPT_DOC_CHARS:
        out["notes"].append({"code": TOO_LONG, "chars": len(text),
                             "limit": PROMPT_DOC_CHARS})
    if kind == "excel":
        names = _sheet_names(text)
        if len(names) > 1:
            out["notes"].append({"code": SHEETS, "names": names})
    if seconds > SLOW_SECONDS:
        out["notes"].append({"code": SLOW, "seconds": round(seconds, 1)})
    _cache[key] = out
    return out


def check_many(paths: List[str]) -> List[Dict[str, Any]]:
    return [check(p) for p in paths or []]
