# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Is the archive up to date, account by account?

The agent and the search answer from the archive. When one account stops
syncing (a changed password, a server that refuses the login) the archive
of that account stops growing, and a question such as "what arrived from
this sender since yesterday?" gets "nothing" with full confidence. Before
this, the only trace was a line in the watcher log.

Three readers:
  status()        one row per account, for the Automations view;
  warning_for()   one line for the agent, added to a search result;
  alerts_due()    what the watcher must tell the user (behind, back).
"""
import time
from typing import Any, Dict, List, Optional, Tuple

# An account counts as behind once its last good sync is older than this.
# The watcher syncs every minute or two: a few hours is a real failure,
# not a slow server or a PC that slept for an hour.
STALE_SECONDS = 6 * 3600
# The user is told only once the failures have lasted this long: after a
# weekend with the PC off the last good sync is days old, and the first
# tick can fail just because the network is not up yet.
FAILING_SECONDS = 3600


def _accounts() -> List[Dict[str, Any]]:
    from . import accounts as core_accounts
    return [a for a in core_accounts.get_accounts() if a.get("type") != "demo"]


def _behind(row: Optional[Dict[str, Any]], now: float) -> bool:
    if not row:
        return False    # never synced here: not a failure, just no archive
    since = row["last_ok_at"] or row["error_since"]
    return bool(since) and now - since > STALE_SECONDS


def status(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """One row per configured account: messages archived, last good sync,
    the current error, and whether the account is behind."""
    from . import archivio
    now = time.time() if now is None else now
    st = archivio.store()
    rows = st.sync_rows()
    counts = st.count_by_account()
    out = []
    for a in _accounts():
        aid = int(a["id"])
        r = rows.get(aid)
        out.append({
            "account_id": aid,
            "name": a.get("name") or "",
            "email": a.get("email") or "",
            "messages": counts.get(aid, 0),
            "last_ok_at": (r or {}).get("last_ok_at") or None,
            "last_attempt_at": (r or {}).get("last_attempt_at") or None,
            "error": (r or {}).get("error") or "",
            "error_since": (r or {}).get("error_since") or None,
            "behind": _behind(r, now),
        })
    return out


def _ago(seconds: float) -> str:
    hours = int(seconds // 3600)
    if hours < 48:
        return f"{hours} hours"
    return f"{hours // 24} days"


def warning_for(account_id: Optional[int],
                now: Optional[float] = None) -> Optional[str]:
    """A line for the agent when this account's archive is behind, None
    when it is up to date (or was never synced on this PC)."""
    from . import archivio
    if account_id is None:
        return None
    now = time.time() if now is None else now
    try:
        r = archivio.store().sync_rows().get(int(account_id))
    except Exception:
        return None
    if not _behind(r, now):
        return None
    if r["last_ok_at"]:
        text = (f"The archive of this account was last updated "
                f"{_ago(now - r['last_ok_at'])} ago")
    else:
        text = "The archive of this account has never been updated"
    if r["error"]:
        text += f"; the last sync failed: {r['error']}"
    else:
        text += " (the watcher may not be running)"
    return (text + ". Mail that arrived since then may be missing from the "
            "archive results: say so to the user instead of concluding that "
            "nothing arrived.")


def alerts_due(now: Optional[float] = None) -> List[Tuple[Dict[str, Any], str]]:
    """(account row, "behind" | "back") for each account the user must
    hear about, marked as told. Behind: the syncs have been failing for
    FAILING_SECONDS and the last good one is older than STALE_SECONDS;
    said once per run of failures. Back: an account the user was told
    about synced again."""
    from . import archivio
    now = time.time() if now is None else now
    st = archivio.store()
    rows = st.sync_rows()
    due = []
    for row in status(now):
        r = rows.get(row["account_id"])
        if not r:
            continue
        failing = r["error"] and now - r["error_since"] >= FAILING_SECONDS
        if failing and row["behind"] and not r["alerted_at"]:
            st.sync_alerted(row["account_id"], now)
            due.append((row, "behind"))
        elif not r["error"] and r["alerted_at"]:
            st.sync_alerted(row["account_id"], 0)
            due.append((row, "back"))
    return due
