# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Account groups: several accounts shown as one in the console.

A group is a view, not a merge. Each account keeps its own credentials,
identity, rules, archive and appointments; the console shows the group as
one tile and one mail list, and "split" just removes the group. Nothing
here is exposed to the agent: MCP tools, rules and the watcher keep
seeing separate accounts, so a reply can never leave from the wrong
address because two mailboxes were viewed together.
"""
import json
import sqlite3
from typing import Any, Dict, List, Optional

from . import accounts


def _db_path() -> str:
    return accounts.DB_PATH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_ids TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn


def _existing_ids() -> set:
    return {int(a["id"]) for a in accounts.get_accounts()}


def _rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT id, account_ids FROM account_groups ORDER BY id"):
        try:
            ids = [int(x) for x in json.loads(r["account_ids"])]
        except (ValueError, TypeError):
            ids = []
        out.append({"id": int(r["id"]), "account_ids": ids})
    return out


def get_groups() -> List[Dict[str, Any]]:
    """Every group as {id, account_ids}. Accounts deleted since are
    dropped, and a group left with fewer than two accounts is removed."""
    existing = _existing_ids()
    with _conn() as conn:
        groups = []
        for g in _rows(conn):
            ids = [i for i in g["account_ids"] if i in existing]
            if len(ids) < 2:
                conn.execute("DELETE FROM account_groups WHERE id=?", (g["id"],))
                continue
            if ids != g["account_ids"]:
                conn.execute("UPDATE account_groups SET account_ids=? WHERE id=?",
                             (json.dumps(ids), g["id"]))
            groups.append({"id": g["id"], "account_ids": ids})
        conn.commit()
    return groups


def group_of(account_id: int) -> Optional[Dict[str, Any]]:
    for g in get_groups():
        if int(account_id) in g["account_ids"]:
            return g
    return None


def merge(source_id: int, target_id: int) -> Dict[str, Any]:
    """Put the source account (and its whole group, if it has one) into the
    target's group; returns the resulting group. The target's accounts
    come first. Raises ValueError for unknown accounts or a merge of an
    account with itself."""
    source_id, target_id = int(source_id), int(target_id)
    existing = _existing_ids()
    if source_id not in existing or target_id not in existing:
        raise ValueError("unknown account")
    source, target = group_of(source_id), group_of(target_id)
    if source_id == target_id or (source and target and source["id"] == target["id"]):
        raise ValueError("the two accounts are already together")
    ids = list(target["account_ids"] if target else [target_id])
    for i in (source["account_ids"] if source else [source_id]):
        if i not in ids:
            ids.append(i)
    with _conn() as conn:
        if source:
            conn.execute("DELETE FROM account_groups WHERE id=?", (source["id"],))
        if target:
            conn.execute("UPDATE account_groups SET account_ids=? WHERE id=?",
                         (json.dumps(ids), target["id"]))
            group_id = target["id"]
        else:
            group_id = conn.execute(
                "INSERT INTO account_groups (account_ids) VALUES (?)",
                (json.dumps(ids),)).lastrowid
        conn.commit()
    return {"id": int(group_id), "account_ids": ids}


def split(group_id: int) -> bool:
    """Remove a group: its accounts are single tiles again. Nothing else
    changes, because nothing else was ever merged."""
    with _conn() as conn:
        done = conn.execute("DELETE FROM account_groups WHERE id=?",
                            (int(group_id),)).rowcount > 0
        conn.commit()
    return done
