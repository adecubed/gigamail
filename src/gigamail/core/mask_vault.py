# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Turn the placeholders an agent writes back into the real values.

An account that masks what agents read (core/attachment_mask) hands the
agent "[IBAN_1a2b3c4d]" instead of the IBAN. When the agent then writes a
reply that needs that IBAN, it can only quote the placeholder. This module
remembers, on this machine, which value each placeholder (and each
invented name) stood for, so GigaMail can put the real value back into
the mail before the approval request is stored: the human approves the
mail as it will leave, the agent never sees the value.

That is also a way out for data. A hostile mail can ask the agent to
"reply with [IBAN_...]" of another client, so every restored value is
listed next to the approval (`describe`), and what goes back to the agent
is masked again (`remask`). The watcher and the console's draft button
restore only the placeholders that were in their own prompt (`allowed`):
a rule that sends on its own must not reveal a value its mail did not
already carry.

Fixed texts are not restored: many values share one. The vault is
created by the first masked read, never before (`exists`), and holds the
real values in clear like the mail archive next to it.
"""
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Set

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\[[A-Z0-9_]+_[0-9a-f]{8}\]")
_FILE = "mask_vault.db"
# An invented name the agent writes in a reply is restored too; a vault
# with more of them than this is scanned for placeholders only.
_MAX_NAMES_SCANNED = 20000


class Restored(NamedTuple):
    text: str
    revealed: List[Dict[str, str]]   # [{placeholder, label}], once each
    unknown: List[str]               # placeholder-shaped text with no value


def _path() -> Path:
    from gigamail.core.data_paths import data_root
    return data_root() / _FILE


def exists() -> bool:
    return _path().exists()


def _conn(create: bool = False) -> Optional[sqlite3.Connection]:
    path = _path()
    if not create and not path.exists():
        return None
    c = sqlite3.connect(str(path), timeout=5)
    c.execute("""CREATE TABLE IF NOT EXISTS replacements (
        replacement TEXT PRIMARY KEY,
        value TEXT,
        label TEXT NOT NULL,
        kind TEXT NOT NULL,
        ambiguous INTEGER NOT NULL DEFAULT 0,
        account_id INTEGER,
        seen_at REAL NOT NULL)""")
    return c


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def remember(account_id, entries: Iterable[tuple]) -> None:
    """Store (replacement, value, label, kind) rows, kind "placeholder" or
    "fake_name". Two values behind one replacement make it ambiguous: it is
    never restored. Never raises: a vault that cannot be written leaves the
    masking one-way, it does not stop it."""
    rows = [(r, v, lb, k) for r, v, lb, k in entries if r and v]
    if not rows:
        return
    try:
        c = _conn(create=True)
        with c:
            for replacement, value, label, kind in rows:
                old = c.execute("SELECT value, ambiguous FROM replacements "
                                "WHERE replacement=?", (replacement,)).fetchone()
                if old is None:
                    c.execute("INSERT INTO replacements VALUES (?,?,?,?,0,?,?)",
                              (replacement, value, label, kind,
                               int(account_id) if account_id else None, time.time()))
                elif not old[1] and _norm(old[0]) != _norm(value):
                    c.execute("UPDATE replacements SET ambiguous=1, value=NULL "
                              "WHERE replacement=?", (replacement,))
                else:
                    c.execute("UPDATE replacements SET seen_at=? WHERE replacement=?",
                              (time.time(), replacement))
        c.close()
    except Exception:
        logger.exception("mask vault not written")


def _lookup(c, replacements) -> Dict[str, tuple]:
    out = {}
    for r in replacements:
        row = c.execute("SELECT value, label, ambiguous FROM replacements "
                        "WHERE replacement=?", (r,)).fetchone()
        if row:
            out[r] = row
    return out


def _names(c) -> List[tuple]:
    count = c.execute("SELECT count(*) FROM replacements WHERE kind='fake_name' "
                      "AND ambiguous=0").fetchone()[0]
    if count > _MAX_NAMES_SCANNED:
        return []
    return c.execute("SELECT replacement, value FROM replacements WHERE "
                     "kind='fake_name' AND ambiguous=0").fetchall()


def restore(text: str, allowed: Optional[Set[str]] = None) -> Restored:
    """`text` with each known placeholder, and each invented name, replaced
    by the real value. With `allowed`, only those replacements are restored
    and the other placeholders are left as they are. Raises when the vault
    cannot be read: the caller must not send placeholders as if restored."""
    if not text:
        return Restored(text or "", [], [])
    c = _conn()
    if c is None:
        return Restored(text, [], [])
    try:
        found = sorted(set(PLACEHOLDER_RE.findall(text)))
        known = _lookup(c, found)
        names = [] if allowed is not None and not allowed else _names(c)
    finally:
        c.close()
    spans, revealed, unknown = [], {}, []
    for ph in found:
        row = known.get(ph)
        if allowed is not None and ph not in allowed:
            continue
        if row is None or row[2] or not row[0]:
            unknown.append(ph)
            continue
        revealed[ph] = row[1]
        for m in re.finditer(re.escape(ph), text):
            spans.append((m.start(), m.end(), row[0]))
    for fake, value in names:
        if allowed is not None and fake not in allowed:
            continue
        hits = list(re.finditer(r"(?<!\w)" + re.escape(fake) + r"(?!\w)", text))
        if hits:
            revealed[fake] = "NAME"
        spans.extend((m.start(), m.end(), value) for m in hits)
    if not spans:
        return Restored(text, [], unknown)
    out, pos = [], 0
    for start, end, value in sorted(spans):
        if start < pos:
            continue
        out.append(text[pos:start])
        out.append(value)
        pos = end
    out.append(text[pos:])
    return Restored("".join(out),
                    [{"placeholder": p, "label": lb} for p, lb in revealed.items()],
                    unknown)


def in_text(*texts: str) -> Set[str]:
    """The placeholders and invented names a prompt carried: what an
    answer to that prompt may restore (see `restore(allowed=...)`)."""
    joined = "\n".join(t for t in texts if t)
    found = set(PLACEHOLDER_RE.findall(joined))
    c = _conn()
    if c is None:
        return found
    try:
        for fake, _value in _names(c):
            if fake in joined:
                found.add(fake)
    finally:
        c.close()
    return found


def remask(obj, revealed: List[Dict[str, str]]):
    """`obj` (a tool result: dicts, lists, strings) with the restored values
    written back as their placeholders, for the agent. Longest value first,
    so a value inside another one does not split it."""
    if not revealed or obj is None:
        return obj
    c = _conn()
    if c is None:
        return obj
    try:
        rows = _lookup(c, [r.get("placeholder") for r in revealed
                           if isinstance(r, dict)])
    finally:
        c.close()
    pairs = sorted(((row[0], ph) for ph, row in rows.items() if row[0]),
                   key=lambda p: len(p[0]), reverse=True)
    if not pairs:
        return obj

    def walk(v):
        if isinstance(v, str):
            for value, ph in pairs:
                v = re.sub(re.escape(value), lambda _m, ph=ph: ph, v,
                           flags=re.IGNORECASE)
            return v
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, tuple):
            return tuple(walk(x) for x in v)
        return v

    return walk(obj)


def describe(revealed: List[Dict[str, str]], lang: str) -> str:
    """The line next to an approval: what the mail reveals that the agent
    only saw masked. Empty when nothing was restored."""
    if not revealed:
        return ""
    counts: Dict[str, int] = {}
    for r in revealed:
        label = str(r.get("label") or "MASK")
        counts[label] = counts.get(label, 0) + 1
    what = ", ".join(f"{n} {label}" for label, n in sorted(counts.items()))
    if lang == "it":
        return ("⚠ Questa mail rivela dati che l'agente ha visto solo mascherati ("
                + what + "): controlla che il destinatario debba riceverli.")
    return ("⚠ This mail reveals data the agent only saw masked (" + what
            + "): check that the recipient should get it.")
