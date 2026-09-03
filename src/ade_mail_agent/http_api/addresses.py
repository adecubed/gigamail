"""Rubrica locale (autocomplete destinatari) e memoria degli indirizzi visti."""
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter

from ade_mail_agent.core import (
    mail_router,
)
from ade_mail_agent.core.data_paths import data_root as _data_root

from .common import _active_id

ADDR_DB = os.path.join(str(_data_root()), ".addresses.db")

router = APIRouter()


# ── RUBRICA ──────────────────────────────────────────────────────────

def _init_addr_db():
    with sqlite3.connect(ADDR_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS addresses (
                email TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                count INTEGER DEFAULT 0,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _save_address(email_addr: str, name: str = "") -> None:
    email_addr = (email_addr or "").strip().lower()
    if not email_addr or "@" not in email_addr:
        return
    with sqlite3.connect(ADDR_DB) as conn:
        conn.execute("""
            INSERT INTO addresses (email, name, count, last_used)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE addresses.name END,
                count = addresses.count + 1,
                last_used = CURRENT_TIMESTAMP
        """, (email_addr, name or ""))


def _remember_message_addresses(messages) -> None:
    if not isinstance(messages, list):
        return
    for msg in messages:
        try:
            addr = ((msg or {}).get("from") or {}).get("emailAddress") or {}
            _save_address(addr.get("address") or "", addr.get("name") or "")
        except Exception:
            pass


_init_addr_db()


# ── RUBRICA / AUTOCOMPLETE ───────────────────────────────────────────

@router.get("/addresses")
def get_addresses(q: str = ""):
    with sqlite3.connect(ADDR_DB) as conn:
        conn.row_factory = sqlite3.Row
        if q:
            like = f"%{q.strip()}%"
            rows = conn.execute(
                "SELECT email, name, count FROM addresses "
                "WHERE email LIKE ? OR name LIKE ? "
                "ORDER BY count DESC, last_used DESC LIMIT 12",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT email, name, count FROM addresses "
                "ORDER BY count DESC, last_used DESC LIMIT 20"
            ).fetchall()
        return [dict(r) for r in rows]


@router.get("/addresses/search")
def search_addresses(q: str = "", account_id: Optional[int] = None):
    q = (q or "").strip()
    if not q:
        return []
    local = get_addresses(q)
    if len(local) >= 5:
        return local
    try:
        aid = account_id or _active_id()
        seen = {r["email"] for r in local}
        for msg in (mail_router.search_messages(aid, query=q, top=30) or []):
            addr = ((msg or {}).get("from") or {}).get("emailAddress") or {}
            email_addr = str(addr.get("address") or "").strip().lower()
            name = str(addr.get("name") or "").strip()
            if email_addr and email_addr not in seen and (
                q.lower() in email_addr or q.lower() in name.lower()
            ):
                seen.add(email_addr)
                local.append({"email": email_addr, "name": name, "count": 0})
                _save_address(email_addr, name)
    except Exception:
        pass
    return local[:12]
