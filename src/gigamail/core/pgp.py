# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""End-to-end mail encryption with OpenPGP (RFC 3156 PGP/MIME + Autocrypt).

Every mail encrypted here gets its own random session key; that key travels
inside the mail, locked with the public key of each recipient (and of the
sender, so the copy in Sent stays readable). Only a holder of the matching
secret key can open it: the provider stores and relays ciphertext.

Keys:
  - own keys: one per sending address, generated the first time it is
    needed. The secret key is stored encrypted with the accounts' Fernet
    key (DPAPI-protected on Windows), never in clear on disk.
  - peer keys: learned from the `Autocrypt:` header of incoming mail (the
    header only counts when its `addr` is the mail's From). Every mail
    GigaMail sends over SMTP carries the sender's own header, so after one
    exchange both sides can encrypt without anyone handling keys.

Fail-closed: when encryption was asked for and cannot be done (no key for a
recipient, library missing), the caller gets PgpError and nothing is sent.
A mail asked to be encrypted never leaves in clear.

The store is a SQLite file in the data folder, opened only when a key is
read or written.
"""
from __future__ import annotations

import base64
import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from email import message_from_bytes
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, parsedate_to_datetime
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .data_paths import db_path

logger = logging.getLogger(__name__)

DB_NAME = ".pgp_keys.db"
# Outer Subject of an encrypted mail: the real one travels inside, encrypted
# (protected headers). "..." is what other OpenPGP clients use too.
HIDDEN_SUBJECT = "..."
# Headers copied into the encrypted part and read back from it.
_PROTECTED = ("Subject", "From", "To", "Cc", "Reply-To")


class PgpError(Exception):
    """Encryption was asked for and cannot be done: nothing must be sent.
    Carries the reason in both languages; str() is the English one."""

    def __init__(self, it: str, en: str):
        super().__init__(en)
        self.it, self.en = it, en

    def text(self) -> str:
        return say(self.it, self.en)


class KeyChangePending(PgpError):
    """A recipient's key changed and the user has not decided yet: nothing
    must be encrypted for them, so nothing is sent."""

    def __init__(self, addresses: List[str]):
        self.addresses = list(addresses)
        who = ", ".join(self.addresses)
        super().__init__(f"{who} ha una chiave nuova da accettare",
                         f"{who} has a new key waiting to be accepted")


def say(it: str, en: str) -> str:
    """User-facing text in the user's language."""
    from gigamail import policy
    return it if policy.user_lang() == "it" else en


def available() -> bool:
    try:
        import pysequoia  # noqa: F401
    except ImportError:
        return False
    return True


def _lib():
    try:
        import pysequoia
    except ImportError as e:
        raise PgpError("libreria OpenPGP (pysequoia) non installata",
                       "OpenPGP library (pysequoia) not installed") from e
    return pysequoia


def normalize(address: str) -> str:
    return parseaddr(str(address or ""))[1].strip().lower()


# ── store ───────────────────────────────────────────────────────────

@contextmanager
def _db(write: bool = False) -> Iterator[sqlite3.Connection]:
    """One transaction on the key store, and the file closed afterwards.

    `with sqlite3.connect(...)` only commits: the connection stays open
    until it is garbage collected, and on Windows an open file cannot be
    deleted or replaced.

    With `write`, the transaction starts before the first read (BEGIN
    IMMEDIATE), so a read-then-write sequence cannot interleave with another
    process doing the same: the busy timeout makes them take turns."""
    conn = sqlite3.connect(str(db_path(DB_NAME)), timeout=10)
    try:
        with conn:
            _create_tables(conn)
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
    finally:
        conn.close()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS own_keys (
        address TEXT PRIMARY KEY, secret_enc TEXT NOT NULL,
        fingerprint TEXT NOT NULL, created_at REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS peer_keys (
        address TEXT PRIMARY KEY, keydata BLOB NOT NULL,
        fingerprint TEXT NOT NULL, prefer_encrypt TEXT NOT NULL DEFAULT '',
        last_seen REAL NOT NULL)""")
    if "first_seen" not in {r[1] for r in conn.execute("PRAGMA table_info(peer_keys)")}:
        try:
            conn.execute("ALTER TABLE peer_keys ADD COLUMN"
                         " first_seen REAL NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            # Fine when another process added the column first; any other
            # failure leaves it missing, and must not be hidden.
            if "first_seen" not in {
                    r[1] for r in conn.execute("PRAGMA table_info(peer_keys)")}:
                raise
    # A key a correspondent started to use that the user has not accepted
    # ('pending'), refused ('refused'), or that used to be the accepted one
    # ('replaced': kept only to check signatures, never to encrypt).
    conn.execute("""CREATE TABLE IF NOT EXISTS held_peer_keys (
        address TEXT NOT NULL, fingerprint TEXT NOT NULL,
        keydata BLOB NOT NULL, prefer_encrypt TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL,
        first_seen REAL NOT NULL, last_seen REAL NOT NULL,
        decided_at REAL,
        told INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (address, fingerprint))""")
    # Keys that were active once: kept so mail written for them still opens.
    # Never used to sign, to encrypt or in the Autocrypt header.
    conn.execute("""CREATE TABLE IF NOT EXISTS retired_keys (
        address TEXT NOT NULL, fingerprint TEXT NOT NULL,
        secret_enc TEXT NOT NULL, created_at REAL NOT NULL,
        retired_at REAL NOT NULL, PRIMARY KEY (address, fingerprint))""")


def _protect(data: bytes) -> str:
    from .accounts import _encrypt
    return _encrypt(base64.b64encode(data).decode("ascii"))


def _unprotect(token: str) -> bytes:
    from .accounts import _decrypt
    return base64.b64decode(_decrypt(token))


# ── own keys ────────────────────────────────────────────────────────

def own_key(address: str, create: bool = True):
    """The secret key (pysequoia Tsk) of one of our addresses; generated and
    stored on first use when `create`. None when absent and not created."""
    addr = normalize(address)
    if not addr:
        raise PgpError("manca l'indirizzo del mittente", "no sender address")
    p = _lib()
    with _db() as conn:
        row = conn.execute("SELECT secret_enc FROM own_keys WHERE address=?",
                           (addr,)).fetchone()
        if row:
            return p.Tsk.from_bytes(_unprotect(row[0]))
        if not create:
            return None
        tsk = p.Tsk.generate(user_id=f"<{addr}>")
        conn.execute(
            "INSERT INTO own_keys(address, secret_enc, fingerprint, created_at)"
            " VALUES (?,?,?,?)",
            (addr, _protect(bytes(tsk)), tsk.extract_certificate().fingerprint,
             time.time()))
        logger.info("generated OpenPGP key for an own address")
        return tsk


def _own_keys() -> List[Tuple[str, object]]:
    """Every secret key of ours, for opening mail: the active ones first,
    then the retired ones. Signing and encrypting go through `own_key`."""
    p = _lib()
    with _db() as conn:
        rows = conn.execute("SELECT address, secret_enc FROM own_keys").fetchall()
        rows += conn.execute("SELECT address, secret_enc FROM retired_keys"
                             " ORDER BY address, created_at").fetchall()
    return [(a, p.Tsk.from_bytes(_unprotect(s))) for a, s in rows]


def own_fingerprint(address: str) -> Optional[str]:
    tsk = own_key(address, create=False)
    return tsk.extract_certificate().fingerprint if tsk else None


def _stored_keys(conn: sqlite3.Connection, address: Optional[str] = None):
    """(address, state, fingerprint, created_at, secret_enc) of every own
    key: by address, the active one first, then the retired by age."""
    where, args = ("WHERE address=?", (normalize(address),)) if address else ("", ())
    rows = [(a, "active", f, c, s) for a, s, f, c in conn.execute(
        f"SELECT address, secret_enc, fingerprint, created_at FROM own_keys {where}",
        args)]
    rows += [(a, "retired", f, c, s) for a, s, f, c in conn.execute(
        f"SELECT address, secret_enc, fingerprint, created_at FROM retired_keys {where}",
        args)]
    rank = {"active": 0, "retired": 1}
    return sorted(rows, key=lambda r: (r[0], rank[r[1]], r[3]))


def list_own_keys() -> List[Dict]:
    """The keys we hold, active and retired, without generating any."""
    with _db() as conn:
        rows = _stored_keys(conn)
    return [{"address": a, "fingerprint": f, "created_at": c, "state": st}
            for a, st, f, c, _s in rows]


def own_key_bytes(address: Optional[str] = None) -> List[Tuple[str, str, bytes]]:
    """(address, state, unprotected key bytes) of every key we hold, or of
    one address; for a backup. Never generates a key."""
    with _db() as conn:
        rows = _stored_keys(conn, address)
    return [(a, st, _unprotect(s)) for a, st, _f, _c, s in rows]


def _key_created_at(key: bytes) -> float:
    """When the key was made, read from its first (primary) key packet;
    now when that cannot be read."""
    try:
        from .pgp_backup import read_packets
        for tag, body, _raw in read_packets(key):
            if tag in (5, 6) and body[0] == 4:
                return float(int.from_bytes(body[1:5], "big"))
            break
    except Exception:
        pass
    return time.time()


def install_keys(entries: List[Dict]) -> List[Dict]:
    """Put restored keys into the store, in one transaction.

    entries: {"address", "key" (unprotected bytes), "may_be_active"}, in file
    order. Per address, the first entry becomes the active key when it may,
    and the key it displaces is retired, not deleted; every other new key is
    kept retired, for decrypting only. A key already held, active or
    retired, changes nothing. Returns {"address", "fingerprint", "outcome"}
    per entry, outcome "active", "retired" or "present"."""
    p = _lib()
    out: List[Dict] = []
    seen = set()
    with _db() as conn:
        for entry in entries:
            addr = normalize(entry["address"])
            raw = bytes(entry["key"])
            fpr = p.Tsk.from_bytes(raw).extract_certificate().fingerprint
            first = addr not in seen
            seen.add(addr)
            held = conn.execute(
                "SELECT 1 FROM own_keys WHERE address=? AND fingerprint=?"
                " UNION SELECT 1 FROM retired_keys WHERE address=? AND fingerprint=?",
                (addr, fpr, addr, fpr)).fetchone()
            if held:
                outcome = "present"
            else:
                created = _key_created_at(raw)
                if first and entry.get("may_be_active"):
                    displaced = conn.execute(
                        "SELECT secret_enc, fingerprint, created_at FROM own_keys"
                        " WHERE address=?", (addr,)).fetchone()
                    if displaced:
                        conn.execute(
                            "INSERT INTO retired_keys(address, fingerprint,"
                            " secret_enc, created_at, retired_at)"
                            " VALUES (?,?,?,?,?)",
                            (addr, displaced[1], displaced[0], displaced[2],
                             time.time()))
                    conn.execute(
                        "INSERT OR REPLACE INTO own_keys(address, secret_enc,"
                        " fingerprint, created_at) VALUES (?,?,?,?)",
                        (addr, _protect(raw), fpr, created))
                    outcome = "active"
                else:
                    conn.execute(
                        "INSERT INTO retired_keys(address, fingerprint,"
                        " secret_enc, created_at, retired_at)"
                        " VALUES (?,?,?,?,?)",
                        (addr, fpr, _protect(raw), created, time.time()))
                    outcome = "retired"
            out.append({"address": addr, "fingerprint": fpr, "outcome": outcome})
    return out


def autocrypt_header(address: str) -> str:
    """Value of the `Autocrypt:` header for mail sent from `address`.
    keydata is base64 of the binary public key, broken with spaces so the
    header can be folded under the 998-character line limit (Autocrypt
    ignores whitespace in keydata)."""
    addr = normalize(address)
    cert = own_key(addr).extract_certificate()
    b64 = base64.b64encode(bytes(cert)).decode("ascii")
    chunks = " ".join(b64[i:i + 72] for i in range(0, len(b64), 72))
    return f"addr={addr}; prefer-encrypt=mutual; keydata={chunks}"


# ── peer keys ───────────────────────────────────────────────────────

def _parse_autocrypt(value: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for item in str(value or "").split(";"):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        attrs[k.strip().lower()] = v.strip()
    return attrs


def learn_autocrypt(msg: Message) -> Optional[str]:
    """Store the sender's key from an incoming mail's Autocrypt header.
    Returns the address learned, or None. The header only counts when its
    `addr` is the From address; a newer mail replaces an older key, an
    older mail never replaces a newer one."""
    if not available():
        return None
    sender = normalize(str(msg.get("From", "")))
    if not sender:
        return None
    for value in msg.get_all("Autocrypt") or []:
        attrs = _parse_autocrypt(str(value))
        # Unknown critical attributes make the header invalid (Autocrypt 1.1).
        known = {"addr", "prefer-encrypt", "keydata"}
        if any(k not in known and not k.startswith("_") for k in attrs):
            continue
        if normalize(attrs.get("addr", "")) != sender or not attrs.get("keydata"):
            continue
        try:
            keydata = base64.b64decode(re.sub(r"\s+", "", attrs["keydata"]))
            cert = _lib().Cert.from_bytes(keydata)
        except Exception as e:
            logger.info("unreadable Autocrypt key: %s", e)
            continue
        # bytes(cert) is the public half only, whatever the header carried.
        keydata = bytes(cert)
        seen = _mail_time(msg)
        prefer = attrs.get("prefer-encrypt", "")
        fpr = cert.fingerprint
        stored, tell = _store_peer_key(sender, keydata, fpr, seen, prefer)
        if tell:
            _tell_arrival(sender, fpr)
        return stored
    return None


def _store_peer_key(sender: str, keydata: bytes, fpr: str, seen: float,
                    prefer: str) -> Tuple[Optional[str], bool]:
    """One Autocrypt key against the store, in one write transaction.
    Returns (what learn_autocrypt returns, whether the key is a pending one
    the user may have to be told about)."""
    with _db(write=True) as conn:
        # One of our own addresses is not a correspondent.
        if conn.execute("SELECT 1 FROM own_keys WHERE address=?",
                        (sender,)).fetchone():
            return None, False
        row = conn.execute(
            "SELECT fingerprint, last_seen FROM peer_keys WHERE address=?",
            (sender,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO peer_keys(address, keydata, fingerprint,"
                " prefer_encrypt, last_seen, first_seen) VALUES (?,?,?,?,?,?)",
                (sender, keydata, fpr, prefer, seen, seen))
            return sender, False
        if row[1] > seen:
            return None, False
        if row[0].lower() == fpr.lower():
            conn.execute(
                "UPDATE peer_keys SET keydata=?, prefer_encrypt=?,"
                " last_seen=? WHERE address=?",
                (keydata, prefer, seen, sender))
            return sender, False
        # Another key than the accepted one: it waits for the user.
        held = conn.execute(
            "SELECT state, decided_at FROM held_peer_keys"
            " WHERE address=? AND lower(fingerprint)=?",
            (sender, fpr.lower())).fetchone()
        if held and held[0] == "replaced" and held[1] is not None and seen <= held[1]:
            # A mail written before the user accepted the other key: reading it
            # again must not undo that decision.
            return None, False
        if held and held[0] in ("pending", "refused"):
            conn.execute(
                "UPDATE held_peer_keys SET last_seen=max(last_seen, ?)"
                " WHERE address=? AND lower(fingerprint)=?",
                (seen, sender, fpr.lower()))
            # A pending row never told (an older version stored it) is told now.
            return None, held[0] == "pending"
        other = conn.execute(
            "SELECT last_seen FROM held_peer_keys"
            " WHERE address=? AND state='pending'", (sender,)).fetchone()
        if other and other[0] >= seen:
            return None, False  # a newer (or as new) pending key is already waiting
        conn.execute("DELETE FROM held_peer_keys"
                     " WHERE address=? AND state='pending'", (sender,))
        if held:  # a 'replaced' key coming back
            conn.execute(
                "UPDATE held_peer_keys SET keydata=?, prefer_encrypt=?,"
                " state='pending', first_seen=?, last_seen=max(last_seen, ?),"
                " decided_at=NULL, told=0"
                " WHERE address=? AND lower(fingerprint)=?",
                (keydata, prefer, seen, seen, sender, fpr.lower()))
        else:
            conn.execute(
                "INSERT INTO held_peer_keys(address, fingerprint, keydata,"
                " prefer_encrypt, state, first_seen, last_seen)"
                " VALUES (?,?,?,?,'pending',?,?)",
                (sender, fpr, keydata, prefer, seen, seen))
        logger.warning("OpenPGP key of a correspondent changed: waiting")
        return None, True


# Bits of held_peer_keys.told: which notices were sent for that key.
TOLD_ARRIVAL = 1
TOLD_STOPPED_SEND = 2


def _claim_notice(address: str, fingerprint: Optional[str], bit: int) -> bool:
    """Set `bit` of `told` on a pending row, in a write transaction of its own
    that is committed when this returns. True for the one caller whose
    UPDATE changed the row: only that caller sends the notice, which makes it
    once per key across processes. `fingerprint` None means the pending row of
    the address, whichever key it is."""
    sql = ("UPDATE held_peer_keys SET told = told | ?"
           " WHERE address=? AND state='pending' AND told & ? = 0")
    args: list = [bit, address, bit]
    if fingerprint is not None:
        sql += " AND lower(fingerprint)=?"
        args.append(fingerprint.lower())
    with _db(write=True) as conn:
        return conn.execute(sql, args).rowcount == 1


def _send_notice(it: str, en: str) -> None:
    try:
        from gigamail import policy
        policy.notify_plain(say(it, en))
    except Exception as e:
        logger.info("could not tell the user about a key change: %s", e)


def _tell_arrival(address: str, fingerprint: str) -> None:
    """The first notice: a correspondent has a new key waiting. Never raises:
    reading mail goes on whatever happens to the notice. The bit is set first,
    so a notice that fails is not retried."""
    try:
        if not _claim_notice(address, fingerprint, TOLD_ARRIVAL):
            return
    except Exception as e:
        logger.info("could not record a key change notice: %s", e)
        return
    _send_notice(
        f"GigaMail: {address} ha una chiave di cifratura nuova. Finché non decidi, "
        "le mail cifrate per questo indirizzo non partono. "
        "Apri GigaMail sul PC per vederla.",
        f"GigaMail: {address} has a new encryption key. Until you decide, "
        "encrypted mail to this address is not sent. "
        "Open GigaMail on the PC to see it.")


def note_blocked_send(addresses: Iterable[str]) -> None:
    """A send stopped because of a pending key: tell the user, once per key,
    for each address that has one. Never raises."""
    seen = set()
    for raw in addresses or []:
        try:
            addr = normalize(raw)
            if not addr or addr in seen:
                continue
            seen.add(addr)
            if not _claim_notice(addr, None, TOLD_STOPPED_SEND):
                continue
        except Exception as e:
            logger.info("could not record a stopped send notice: %s", e)
            continue
        _send_notice(
            f"GigaMail: una mail cifrata per {addr} non è partita: ha una chiave "
            "nuova da accettare. Apri GigaMail sul PC.",
            f"GigaMail: an encrypted mail to {addr} was not sent: there is a new "
            "key to accept. Open GigaMail on the PC.")


def _key_dict(fingerprint: str, first_seen: float, last_seen: float) -> Dict:
    return {"fingerprint": fingerprint,
            "first_seen": first_seen or last_seen, "last_seen": last_seen}


def _info(conn: sqlite3.Connection, address: str) -> Dict:
    if conn.execute("SELECT 1 FROM own_keys WHERE address=?",
                    (address,)).fetchone():
        return {"address": address, "known": None, "held": None}
    row = conn.execute(
        "SELECT fingerprint, first_seen, last_seen FROM peer_keys"
        " WHERE address=?", (address,)).fetchone()
    held = conn.execute(
        "SELECT fingerprint, first_seen, last_seen, state FROM held_peer_keys"
        " WHERE address=? AND state='pending'", (address,)).fetchone()
    if held is None:
        held = conn.execute(
            "SELECT fingerprint, first_seen, last_seen, state FROM held_peer_keys"
            " WHERE address=? AND state='refused'"
            " ORDER BY decided_at DESC, last_seen DESC LIMIT 1",
            (address,)).fetchone()
    return {"address": address,
            "known": _key_dict(*row) if row else None,
            "held": ({**_key_dict(*held[:3]), "state": held[3]}
                     if held else None)}


def peer_key_info(address: str) -> Dict:
    """What is known about a correspondent's key: the accepted one, and the
    pending one (or else the most recently refused one)."""
    addr = normalize(address)
    with _db() as conn:
        return _info(conn, addr)


def _reported(infos: List[Dict]) -> List[Dict]:
    """Without the entries that have nothing to show: an own address, whose
    rows an older version may have left in the store."""
    return [i for i in infos if i["known"] is not None or i["held"] is not None]


def pending_changes() -> List[Dict]:
    """`peer_key_info` of every address with a key waiting for a decision."""
    with _db() as conn:
        addrs = [r[0] for r in conn.execute(
            "SELECT address FROM held_peer_keys WHERE state='pending'"
            " ORDER BY address")]
        return _reported([_info(conn, a) for a in addrs])


def list_peer_keys() -> List[Dict]:
    """`peer_key_info` of every address that has an accepted key."""
    with _db() as conn:
        addrs = [r[0] for r in conn.execute(
            "SELECT address FROM peer_keys ORDER BY address")]
        return _reported([_info(conn, a) for a in addrs])


def _mail_time(msg: Message) -> float:
    """When the mail was sent, never later than now: a Date in the future
    (a wrong clock, or written on purpose) would keep every later mail
    from updating that correspondent's key."""
    now = time.time()
    try:
        return min(parsedate_to_datetime(str(msg.get("Date", ""))).timestamp(), now)
    except Exception:
        return now


def peer_cert(address: str):
    addr = normalize(address)
    if not addr:
        return None
    with _db() as conn:
        row = conn.execute("SELECT keydata FROM peer_keys WHERE address=?",
                           (addr,)).fetchone()
    return _lib().Cert.from_bytes(row[0]) if row else None


def import_peer_key(address: str, keydata: bytes) -> str:
    """Store a correspondent's public key by hand (armored or binary), as the
    accepted one. Only the public half is kept. Returns its fingerprint."""
    addr = normalize(address)
    cert = _lib().Cert.from_bytes(keydata)
    fpr = cert.fingerprint
    now = time.time()
    with _db(write=True) as conn:
        row = conn.execute(
            "SELECT fingerprint, first_seen, last_seen FROM peer_keys"
            " WHERE address=?", (addr,)).fetchone()
        first = now
        if row and row[0].lower() == fpr.lower():
            first = row[1] or row[2]  # the same key: known since then
        conn.execute(
            "INSERT OR REPLACE INTO peer_keys(address, keydata, fingerprint,"
            " prefer_encrypt, last_seen, first_seen) VALUES (?,?,?,?,?,?)",
            (addr, bytes(cert), fpr, "", now, first))
        conn.execute("DELETE FROM held_peer_keys"
                     " WHERE address=? AND lower(fingerprint)=?",
                     (addr, fpr.lower()))
    return fpr


def missing_keys(recipients: Iterable[str]) -> List[str]:
    """Recipients we cannot encrypt for: no key known."""
    out = []
    for r in recipients:
        addr = normalize(r)
        if addr and own_key(addr, create=False) is None and peer_cert(addr) is None:
            out.append(addr)
    return out


def held_changes(recipients: Iterable[str]) -> List[str]:
    """The recipients whose key has a change waiting for the user's decision:
    normalized, each once, in the order given. An address of ours never has
    one."""
    addrs = list(dict.fromkeys(a for a in map(normalize, recipients) if a))
    if not addrs:
        return []
    with _db() as conn:
        return [a for a in addrs
                if (_info(conn, a)["held"] or {}).get("state") == "pending"]


def status(sender: str, recipients: Iterable[str]) -> Dict:
    """What the compose window needs before offering "Encrypt"."""
    recips = [normalize(r) for r in recipients if normalize(r)]
    if not available():
        return {"available": False, "can_encrypt": False, "missing": recips,
                "pending": [], "peers": []}
    missing = missing_keys(recips)
    pending, peers = [], []
    with _db() as conn:
        for a in dict.fromkeys(recips):
            info = _info(conn, a)
            known, held = info["known"], info["held"]
            if held and held["state"] == "pending":
                pending.append({
                    "address": a, "known": known,
                    "held": {"fingerprint": held["fingerprint"],
                             "first_seen": held["first_seen"]}})
            if known:
                peers.append({"address": a, "fingerprint": known["fingerprint"]})
    return {"available": True,
            "can_encrypt": bool(recips) and not missing and not pending,
            "missing": missing, "pending": pending, "peers": peers,
            "own_fingerprint": own_fingerprint(sender)}


def decide_change(address: str, fingerprint: str, accept: bool) -> Dict:
    """The user's decision about a key held for `address`: accept it (it
    becomes the key in use; the one it replaces is kept to check signatures
    only) or keep the old one (the held key is marked refused). One
    transaction. `fingerprint` must be the held key the person was shown,
    pending or refused: another one is an error, so a key that arrived in
    between is never accepted unseen. Returns {address, outcome, accepted,
    other}: `accepted` is the key now in use, `other` the one that lost."""
    addr = normalize(address)
    want = "".join(str(fingerprint or "").split()).lower()
    now = time.time()
    with _db(write=True) as conn:
        held = conn.execute(
            "SELECT fingerprint, keydata, prefer_encrypt, first_seen, last_seen"
            " FROM held_peer_keys WHERE address=? AND lower(fingerprint)=?"
            " AND state IN ('pending', 'refused')", (addr, want)).fetchone()
        if held is None or not want:
            raise PgpError(
                "Questa non è più la chiave in attesa: riapri e ricontrolla.",
                "This is no longer the key that is waiting: open it again"
                " and check.")
        known = conn.execute(
            "SELECT fingerprint, keydata, prefer_encrypt, first_seen, last_seen"
            " FROM peer_keys WHERE address=?", (addr,)).fetchone()
        if not accept:
            conn.execute(
                "UPDATE held_peer_keys SET state='refused', decided_at=?"
                " WHERE address=? AND fingerprint=?", (now, addr, held[0]))
            return {"address": addr, "outcome": "kept",
                    "accepted": known[0] if known else "", "other": held[0]}
        if known:
            conn.execute(
                "INSERT OR REPLACE INTO held_peer_keys(address, fingerprint,"
                " keydata, prefer_encrypt, state, first_seen, last_seen,"
                " decided_at) VALUES (?,?,?,?,'replaced',?,?,?)",
                (addr, known[0], known[1], known[2],
                 known[3] or known[4], known[4], now))
        conn.execute(
            "INSERT OR REPLACE INTO peer_keys(address, keydata, fingerprint,"
            " prefer_encrypt, last_seen, first_seen) VALUES (?,?,?,?,?,?)",
            (addr, held[1], held[0], held[2], held[4], held[3]))
        conn.execute("DELETE FROM held_peer_keys WHERE address=?"
                     " AND fingerprint=? AND state IN ('pending', 'refused')",
                     (addr, held[0]))
        return {"address": addr, "outcome": "accepted", "accepted": held[0],
                "other": known[0] if known else ""}


def _cert_for(address: str):
    # An address of ours is encrypted for with our own key, whatever a
    # peer_keys row may hold.
    tsk = own_key(address, create=False)
    if tsk is not None:
        return tsk.extract_certificate()
    return peer_cert(address)


# ── encrypt ─────────────────────────────────────────────────────────

def encrypt_message(msg: Message, sender: str, recipients: Iterable[str]) -> Message:
    """`msg` (headers + body + attachments) turned into an RFC 3156
    multipart/encrypted mail, signed by `sender` and encrypted for every
    recipient and for the sender. Raises PgpError when a key is missing:
    then nothing must be sent."""
    p = _lib()
    recips = [normalize(r) for r in recipients if normalize(r)]
    if not recips:
        raise PgpError("nessun destinatario", "no recipients")
    missing = missing_keys(recips)
    if missing:
        who = ", ".join(missing)
        raise PgpError(f"nessuna chiave di cifratura per {who}",
                       f"no encryption key for {who}")
    waiting = held_changes(recips)
    if waiting:
        raise KeyChangePending(waiting)
    tsk = own_key(sender)
    certs = [_cert_for(r) for r in recips]
    fingerprints = set()
    unique = []
    for c in certs + [tsk.extract_certificate()]:
        if c.fingerprint not in fingerprints:
            fingerprints.add(c.fingerprint)
            unique.append(c)

    inner = _inner_part(msg)
    ciphertext = p.encrypt(bytes=inner.as_bytes(), recipients=unique,
                           signer=tsk.signer())

    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    for k, v in msg.items():
        if k.lower() in ("content-type", "mime-version",
                         "content-transfer-encoding", "subject"):
            continue
        outer[k] = v
    outer["Subject"] = HIDDEN_SUBJECT
    control = MIMEApplication(b"Version: 1\n", "pgp-encrypted",
                              _encoder=_noop_encoder)
    control["Content-Description"] = "PGP/MIME version identification"
    outer.attach(control)
    data = MIMEApplication(ciphertext, "octet-stream", _encoder=_noop_encoder,
                           name="encrypted.asc")
    data["Content-Description"] = "OpenPGP encrypted message"
    data["Content-Disposition"] = 'inline; filename="encrypted.asc"'
    outer.attach(data)
    outer.preamble = "This is an OpenPGP/MIME encrypted message (RFC 4880 and 3156)"
    return outer


def _noop_encoder(part) -> None:
    # Armored ciphertext and the version line are 7-bit text already.
    part["Content-Transfer-Encoding"] = "7bit"


def _inner_part(msg: Message) -> Message:
    if msg.is_multipart():
        inner = MIMEMultipart(msg.get_content_subtype() or "mixed")
        for part in msg.get_payload():
            inner.attach(part)
    else:
        inner = MIMEMultipart("mixed")
        inner.attach(msg)
    inner.set_param("protected-headers", "v1")
    for h in _PROTECTED:
        if msg.get(h):
            inner[h] = msg[h]
    return inner


# ── decrypt ─────────────────────────────────────────────────────────

def is_encrypted(msg: Message) -> bool:
    return (msg.get_content_type() == "multipart/encrypted"
            and str(msg.get_param("protocol") or "").lower()
            == "application/pgp-encrypted")


def _ciphertext(msg: Message) -> Optional[bytes]:
    parts = msg.get_payload()
    if not isinstance(parts, list):
        return None
    for part in parts:
        if part.get_content_type() == "application/octet-stream":
            return part.get_payload(decode=True)
    return None


def open_message(msg: Message, account_address: str = "") -> Tuple[Message, Optional[Dict]]:
    """For an encrypted mail: the decrypted inner message (with the
    protected Subject restored on top) and what we know about it. For a
    clear mail: the same message and None. The sender's Autocrypt key is
    learned in both cases.

    info: {encrypted, decrypted, signed, signature_valid, signer,
           signer_matches_from, signer_fingerprint, signer_key, error}
    signer_key says whose key signed: 'own', 'accepted', or a held one
    ('pending', 'refused', 'replaced'); None when unsigned or unknown."""
    try:
        learn_autocrypt(msg)
    except Exception as e:
        logger.info("Autocrypt header not stored: %s", e)
    if not is_encrypted(msg):
        return msg, None
    info: Dict = {"encrypted": True, "decrypted": False, "signed": False,
                  "signature_valid": False, "signer": None,
                  "signer_matches_from": False, "signer_fingerprint": None,
                  "signer_key": None, "error": None}
    if not available():
        info["error"] = "OpenPGP library not installed"
        return msg, info
    data = _ciphertext(msg)
    if not data:
        info["error"] = "no encrypted part"
        return msg, info
    p = _lib()
    keys = _own_keys()
    own = normalize(account_address)
    keys.sort(key=lambda k: k[0] != own)   # the account's own key first
    peer_certs = _all_peer_certs()

    def store(_ids):
        return peer_certs + [k.extract_certificate() for _, k in keys]

    decrypted = None
    for _addr, tsk in keys:
        try:
            decrypted = p.decrypt(bytes=data, decryptor=tsk.decryptor(), store=store)
            break
        except Exception as e:
            # With a store, the library refuses a mail it opened but whose
            # signature it cannot check: unsigned, or signed by a key we
            # have not met (a platform that sends no Autocrypt header). The
            # mail is ours to read; it opens without a verified signature,
            # and the badge says so. A message with no signature at all
            # (most mail from other OpenPGP programs) is refused with
            # "Unexpected message structure" instead.
            reason = str(e).lower()
            if ("signature verification failed" not in reason
                    and "unexpected message structure" not in reason):
                continue
            try:
                decrypted = p.decrypt(bytes=data, decryptor=tsk.decryptor())
                break
            except Exception:
                continue
    if decrypted is None:
        info["error"] = "no key of ours can open this mail"
        return msg, info
    inner = message_from_bytes(decrypted.bytes)
    info["decrypted"] = True
    opened = _restore_headers(msg, inner)
    sigs = list(decrypted.valid_sigs or [])
    if sigs:
        info["signed"] = info["signature_valid"] = True
        fpr = str(sigs[0].certificate).lower()
        # Against the From the reader is shown, which is the protected one
        # from inside the encryption: checked against the outer From, a
        # correspondent could sign a mail that names someone else as its
        # sender and still get "signed by" under that name.
        # The fingerprint is kept even when no table knows it yet: the
        # archive can resolve it once the key is learned.
        info["signer_fingerprint"] = fpr
        info["signer"], info["signer_key"] = _signer_of(fpr)
        info["signer_matches_from"] = _matches_from(
            info["signer"], info["signer_key"], str(opened.get("From", "")))
    return opened, info


def open_raw(raw: bytes, account_address: str = "") -> Tuple[bytes, Optional[Dict]]:
    """open_message for callers that parse the bytes themselves (archive,
    attachments): the decrypted message as bytes, or `raw` unchanged when
    it is not encrypted or cannot be opened."""
    try:
        inner, info = open_message(message_from_bytes(raw), account_address)
    except Exception as e:
        logger.warning("encrypted mail not opened: %s", e)
        return raw, None
    if info and info.get("decrypted"):
        return inner.as_bytes(), info
    return raw, info


def _certs_of(keydatas, what: str) -> list:
    """The certificates in these key bytes; one that does not parse is
    skipped, so one damaged key cannot stop all reading."""
    p = _lib()
    certs = []
    for keydata in keydatas:
        try:
            certs.append(p.Cert.from_bytes(keydata))
        except Exception as e:
            logger.warning("a %s key in the store cannot be read, skipped: %s", what, e)
    return certs


def _all_peer_certs() -> list:
    """Every correspondent key that can verify a signature: the accepted
    ones and the held ones of any state."""
    with _db() as conn:
        accepted = [r[0] for r in conn.execute("SELECT keydata FROM peer_keys")]
        held = [r[0] for r in conn.execute("SELECT keydata FROM held_peer_keys")]
    return _certs_of(accepted, "peer") + _certs_of(held, "held")


_HELD_RANK = {"pending": 0, "refused": 1, "replaced": 2}


def _signer_of(fingerprint: str) -> Tuple[Optional[str], Optional[str]]:
    """(address, signer_key) of the key with this fingerprint: our own keys
    first, then the accepted ones, then the held ones. (None, None) when we
    do not know it."""
    fpr = str(fingerprint or "").lower()
    with _db() as conn:
        for addr, _state, f, _c, _s in _stored_keys(conn):
            if str(f).lower() == fpr:
                return addr, "own"
        row = conn.execute("SELECT address FROM peer_keys WHERE lower(fingerprint)=?",
                           (fpr,)).fetchone()
        if row:
            return row[0], "accepted"
        rows = conn.execute(
            "SELECT address, state FROM held_peer_keys WHERE lower(fingerprint)=?"
            " ORDER BY last_seen DESC", (fpr,)).fetchall()
    rows.sort(key=lambda r: _HELD_RANK.get(r[1], 9))
    return (rows[0][0], rows[0][1]) if rows else (None, None)


def _matches_from(signer, kind, from_address: str) -> bool:
    return bool(kind in ("own", "accepted") and signer
                and signer == normalize(from_address))


def resolve_signer(info, from_address: str):
    """`info` with signer, signer_key and signer_matches_from worked out from
    the key store as it is now, for info that carries a `signer_fingerprint`
    the store knows; anything else comes back unchanged (a mail kept
    decrypted keeps what it said when its key is no longer in the store).
    Only our own and the accepted keys can match the From: a key the user has
    not accepted never shows as "signed by". Never raises."""
    try:
        if not isinstance(info, dict) or not info.get("signer_fingerprint"):
            return info
        if not db_path(DB_NAME).exists():
            return info   # nothing to look in, and reading must not create it
        signer, kind = _signer_of(info["signer_fingerprint"])
        if kind is None:
            return info
        return {**info, "signer": signer, "signer_key": kind,
                "signer_matches_from": _matches_from(signer, kind, from_address)}
    except Exception as e:
        logger.info("signer not resolved: %s", e)
        return info


def key_change_for(address: str) -> Optional[Dict]:
    """{address, fingerprint} when the address has a key waiting for the
    user's decision, else None. Never creates the key store. An address of
    ours never has one."""
    addr = normalize(address)
    if not addr or not db_path(DB_NAME).exists():
        return None
    with _db() as conn:
        if conn.execute("SELECT 1 FROM own_keys WHERE address=?",
                        (addr,)).fetchone():
            return None
        row = conn.execute(
            "SELECT fingerprint FROM held_peer_keys WHERE address=? AND state='pending'",
            (addr,)).fetchone()
    return {"address": addr, "fingerprint": row[0]} if row else None


def _restore_headers(outer: Message, inner: Message) -> Message:
    """The decrypted message as the rest of GigaMail reads it: outer
    transport headers, protected headers from inside winning."""
    for k, v in outer.items():
        lk = k.lower()
        if lk.startswith("content-") or lk == "mime-version":
            continue
        if k in _PROTECTED and inner.get(k):
            continue
        if inner.get(k) is None:
            inner[k] = v
    if inner.get("Subject") is None:
        inner["Subject"] = outer.get("Subject", "")
    return inner

