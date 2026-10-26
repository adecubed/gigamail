# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Spam filters: block mails by what they say, not by who sends them.

A filter is "subject contains X" (or sender / text contains X): every
inbox mail that matches goes to the spam folder (or the bin), from any
sender. The case the sender block does not cover: a web form that mails
"Messaggio inviato dal sito" from a legitimate address, or the same
newsletter arriving from a different address every week.

Deterministic and local, like mail_guard: no model decides. The watcher
applies the filters on every tick; the console applies them at once when
one is created. Matching is a case-insensitive substring; a word or two
is all a user types.

Only the console (its click secret) and the CLI create or remove filters:
an instruction inside a mail cannot make the agent hide mail. The filters
live in spam_filters.json under app_root(), shared by watcher and console.
"""
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

FIELDS = ("subject", "from", "body")
ACTIONS = ("spam", "trash")
# How many inbox mails a run looks at per account: the newest ones, where
# what just arrived is. Older mail was seen by a previous run.
SCAN_TOP = 50
MAX_FILTERS = 200
_LOCK = threading.Lock()


def _path() -> Path:
    from gigamail.core.data_paths import app_root
    return app_root() / "spam_filters.json"


def _load() -> List[Dict[str, Any]]:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(filters: List[Dict[str, Any]]) -> None:
    path = _path()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".spam_filters.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(filters, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_all(account_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every filter, or those that apply to one account (its own and the
    ones for every account)."""
    out = _load()
    if account_id is not None:
        out = [f for f in out if f.get("account_id") in (None, int(account_id))]
    return out


def add(field: str, contains: str, action: str = "spam",
        account_id: Optional[int] = None) -> Dict[str, Any]:
    field = (field or "").strip().lower()
    action = (action or "spam").strip().lower()
    text = " ".join((contains or "").split())
    if field not in FIELDS:
        raise ValueError(f"field must be one of {', '.join(FIELDS)}")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    if len(text) < 3:
        raise ValueError("the text to match must be at least 3 characters")
    if len(text) > 200:
        raise ValueError("the text to match is too long (200 characters at most)")
    with _LOCK:
        filters = _load()
        for f in filters:
            if (f.get("field") == field and f.get("contains", "").lower() == text.lower()
                    and f.get("account_id") == account_id):
                return f
        if len(filters) >= MAX_FILTERS:
            raise ValueError(f"too many filters ({MAX_FILTERS} at most)")
        entry = {"id": "sf_" + secrets.token_hex(5), "field": field, "contains": text,
                 "action": action, "account_id": int(account_id) if account_id is not None else None,
                 "created_at": time.time(), "hits": 0}
        filters.append(entry)
        _save(filters)
    return entry


def remove(filter_id: str) -> bool:
    with _LOCK:
        filters = _load()
        kept = [f for f in filters if f.get("id") != filter_id]
        if len(kept) == len(filters):
            return False
        _save(kept)
    return True


def _text_of(message: Dict[str, Any], field: str) -> str:
    if field == "subject":
        return str(message.get("subject") or "")
    if field == "from":
        fr = message.get("from") or {}
        ea = fr.get("emailAddress") if isinstance(fr, dict) else None
        if isinstance(ea, dict):
            return f"{ea.get('name') or ''} {ea.get('address') or ''}"
        return str(message.get("sender") or fr or "")
    body = message.get("body_text") or message.get("bodyPreview") or ""
    if not body and isinstance(message.get("body"), dict):
        body = message["body"].get("content") or ""
    return f"{message.get('subject') or ''}\n{body}"


def matching(message: Dict[str, Any], filters: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first filter the message matches, or None."""
    for f in filters:
        needle = str(f.get("contains") or "").lower()
        if needle and needle in _text_of(message, str(f.get("field") or "subject")).lower():
            return f
    return None


def _record_hits(counts: Dict[str, int]) -> None:
    if not counts:
        return
    with _LOCK:
        filters = _load()
        for f in filters:
            if f.get("id") in counts:
                f["hits"] = int(f.get("hits") or 0) + counts[f["id"]]
        _save(filters)


# Mails already read in full for a text filter, per account: the listing
# of an IMAP account carries no body at all (and Graph's bodyPreview is
# the first lines), so a "text contains" filter never saw the text it
# was written for. A mail is fetched once per process and remembered.
_CHECKED: Dict[int, Dict[str, bool]] = {}
_CHECKED_MAX = 500


def _has_text(message: Dict[str, Any]) -> bool:
    return bool(message.get("body_text")
                or (isinstance(message.get("body"), dict) and message["body"].get("content")))


def _with_text(account_id: int, message: Dict[str, Any], fetcher=None) -> Dict[str, Any]:
    """The message with its whole text, read from the server once."""
    if _has_text(message):
        return message
    seen = _CHECKED.setdefault(int(account_id), {})
    mid = str(message.get("id"))
    if mid in seen:
        return message
    if len(seen) >= _CHECKED_MAX:
        for k in list(seen)[: _CHECKED_MAX // 2]:
            seen.pop(k, None)
    seen[mid] = True
    try:
        if fetcher is None:
            from gigamail.core import mail_router
            fetcher = lambda aid, m: mail_router.get_message(  # noqa: E731
                account_id=aid, message_id=str(m.get("id")), folder="inbox")
        full = fetcher(account_id, message) or {}
    except Exception:
        return message
    if not isinstance(full, dict) or not full:
        return message
    merged = dict(message)
    merged.update({k: v for k, v in full.items() if k in ("body", "body_text", "bodyPreview")})
    return merged


def run(account_id: int, mover=None, top: int = SCAN_TOP, fetcher=None) -> int:
    """Apply the filters to the newest inbox mails of one account. Returns
    how many were moved. `mover(account_id, message, action)` does the
    move; by default mail_router moves to the spam folder or the bin.
    When a filter is on the text, a mail listed without its body is read
    in full once (`fetcher(account_id, message)`), so the filter sees
    what the user saw."""
    filters = list_all(account_id)
    if not filters:
        return 0
    from gigamail.core import mail_router
    messages = mail_router.get_messages(account_id, folder="inbox", top=top)
    mover = mover or _move
    on_text = any(f.get("field") == "body" for f in filters)
    moved, counts = 0, {}
    for m in messages or []:
        f = matching(m, filters)
        if not f and on_text:
            f = matching(_with_text(account_id, m, fetcher), filters)
        if not f:
            continue
        try:
            if mover(account_id, m, f["action"]):
                moved += 1
                counts[f["id"]] = counts.get(f["id"], 0) + 1
        except Exception:
            continue
    _record_hits(counts)
    return moved


def hide_if_filtered(account_id: int, message: Dict[str, Any], mover=None) -> Optional[Dict[str, Any]]:
    """For whoever holds a message in full (the rules, before drafting):
    the filter it matches, after moving it where the filter says, or
    None. A rule must never answer a mail a filter was written for."""
    f = matching(message, list_all(account_id))
    if not f:
        return None
    try:
        if (mover or _move)(account_id, message, f["action"]):
            _record_hits({f["id"]: 1})
    except Exception:
        pass
    return f


def _move(account_id: int, message: Dict[str, Any], action: str) -> bool:
    from gigamail.core import mail_router
    target = "deleteditems" if action == "trash" else "junkemail"
    return bool(mail_router.move_to_folder(account_id, message_id=str(message.get("id")),
                                           folder_id=target, source_folder="inbox"))


def run_all(mover=None) -> int:
    """Every active account, for the watcher."""
    if not _load():
        return 0
    from gigamail.core import accounts as core_accounts
    total = 0
    for acc in core_accounts.get_accounts():
        try:
            total += run(int(acc["id"]), mover=mover)
        except Exception:
            continue
    return total
