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
def _db() -> Iterator[sqlite3.Connection]:
    """One transaction on the key store, and the file closed afterwards.

    `with sqlite3.connect(...)` only commits: the connection stays open
    until it is garbage collected, and on Windows an open file cannot be
    deleted or replaced."""
    conn = sqlite3.connect(str(db_path(DB_NAME)), timeout=10)
    try:
        with conn:
            _create_tables(conn)
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
    p = _lib()
    with _db() as conn:
        rows = conn.execute("SELECT address, secret_enc FROM own_keys").fetchall()
    return [(a, p.Tsk.from_bytes(_unprotect(s))) for a, s in rows]


def own_fingerprint(address: str) -> Optional[str]:
    tsk = own_key(address, create=False)
    return tsk.extract_certificate().fingerprint if tsk else None


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
        with _db() as conn:
            row = conn.execute("SELECT fingerprint, last_seen FROM peer_keys"
                               " WHERE address=?", (sender,)).fetchone()
            if row and row[1] > seen:
                return None
            if row and row[0] != cert.fingerprint:
                logger.warning("OpenPGP key of a correspondent changed")
            conn.execute(
                "INSERT OR REPLACE INTO peer_keys(address, keydata, fingerprint,"
                " prefer_encrypt, last_seen) VALUES (?,?,?,?,?)",
                (sender, keydata, cert.fingerprint,
                 attrs.get("prefer-encrypt", ""), seen))
        return sender
    return None


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
    """Store a correspondent's public key by hand (armored or binary).
    Only the public half is kept. Returns its fingerprint."""
    addr = normalize(address)
    cert = _lib().Cert.from_bytes(keydata)
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO peer_keys(address, keydata, fingerprint,"
            " prefer_encrypt, last_seen) VALUES (?,?,?,?,?)",
            (addr, bytes(cert), cert.fingerprint, "", time.time()))
    return cert.fingerprint


def missing_keys(recipients: Iterable[str]) -> List[str]:
    """Recipients we cannot encrypt for: no key known."""
    out = []
    for r in recipients:
        addr = normalize(r)
        if addr and peer_cert(addr) is None and own_key(addr, create=False) is None:
            out.append(addr)
    return out


def status(sender: str, recipients: Iterable[str]) -> Dict:
    """What the compose window needs before offering "Encrypt"."""
    recips = [normalize(r) for r in recipients if normalize(r)]
    if not available():
        return {"available": False, "can_encrypt": False, "missing": recips}
    missing = missing_keys(recips)
    return {"available": True, "can_encrypt": bool(recips) and not missing,
            "missing": missing, "own_fingerprint": own_fingerprint(sender)}


def _cert_for(address: str):
    cert = peer_cert(address)
    if cert is not None:
        return cert
    tsk = own_key(address, create=False)
    return tsk.extract_certificate() if tsk else None


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
           signer_matches_from, error}"""
    try:
        learn_autocrypt(msg)
    except Exception as e:
        logger.info("Autocrypt header not stored: %s", e)
    if not is_encrypted(msg):
        return msg, None
    info: Dict = {"encrypted": True, "decrypted": False, "signed": False,
                  "signature_valid": False, "signer": None,
                  "signer_matches_from": False, "error": None}
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
            # and the badge says so.
            if "signature verification failed" not in str(e).lower():
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
        signer = _address_of(fpr, keys)
        info["signer"] = signer
        # Against the From the reader is shown, which is the protected one
        # from inside the encryption: checked against the outer From, a
        # correspondent could sign a mail that names someone else as its
        # sender and still get "signed by" under that name.
        info["signer_matches_from"] = bool(
            signer and signer == normalize(str(opened.get("From", ""))))
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


def _all_peer_certs() -> list:
    p = _lib()
    with _db() as conn:
        rows = conn.execute("SELECT keydata FROM peer_keys").fetchall()
    return [p.Cert.from_bytes(r[0]) for r in rows]


def _address_of(fingerprint: str, keys) -> Optional[str]:
    with _db() as conn:
        row = conn.execute("SELECT address FROM peer_keys WHERE lower(fingerprint)=?",
                           (fingerprint,)).fetchone()
    if row:
        return row[0]
    for addr, tsk in keys:
        if tsk.extract_certificate().fingerprint.lower() == fingerprint:
            return addr
    return None


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

