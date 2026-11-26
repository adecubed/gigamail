# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Passphrase protection of OpenPGP secret keys, for the key backup.

A backup file must open in any OpenPGP program, so the secret key is not
wrapped in a private format: every secret-key packet is protected the
standard way (RFC 4880 section 5.5.3, S2K usage 254, AES-256 in CFB mode,
iterated and salted SHA-256 string-to-key) and every other packet is copied
byte for byte, so the fingerprint cannot change.

This module holds the packet layer, `protect`, `unprotect` and
`is_protected`, and on top of them `export_backup` and `import_backup`, which
write and read the backup file. Only version 4 keys with RSA, ECDH, ECDSA or
EdDSA material are handled; anything else is refused rather than guessed at.
"""
import base64
import datetime
import hashlib
import hmac
import os
import re
import secrets
from email.utils import parseaddr
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except ImportError:  # cryptography < 43
    from cryptography.hazmat.primitives.ciphers.modes import CFB

from . import pgp

MIN_PASSPHRASE = 12

TAG_SECRET_KEY = 5
TAG_SECRET_SUBKEY = 7

_AES256 = 9
_S2K_ITERATED = 3
_HASH_SHA256 = 8
_COUNT_OCTET = 0xEE
_USAGE_SHA1 = 254

_HASHES = {1: "md5", 2: "sha1", 8: "sha256", 9: "sha384", 10: "sha512",
           11: "sha224"}
_RSA = (1, 2, 3)
# Algorithms whose secret is a run of MPIs, and how many (RSA: d, p, q, u;
# ECDH, ECDSA, EdDSA: one).
_MPI_SECRET = {1: 4, 2: 4, 3: 4, 18: 1, 19: 1, 22: 1}
_AES_KEY_LEN = {7: 16, 8: 24, 9: 32}
_READ_HASHES = (2, 8, 10)  # SHA-1, SHA-256, SHA-512


class BackupError(pgp.PgpError):
    """The key backup cannot be made or read."""


class UnsupportedKey(BackupError):
    """A key or a protection this code refuses."""


class WrongPassphrase(BackupError):
    """The passphrase does not open the key."""


class PassphraseRequired(BackupError):
    """The key is protected and no passphrase was given."""


def _refuse(it: str, en: str) -> UnsupportedKey:
    return UnsupportedKey(it, en)


def _damaged() -> UnsupportedKey:
    return _refuse("Dati OpenPGP danneggiati o troncati.",
                   "Damaged or truncated OpenPGP data.")


def read_packets(data: bytes) -> Iterator[Tuple[int, bytes, bytes]]:
    """Yield (tag, body, raw) for each packet of binary OpenPGP data.

    Old- and new-format headers are understood. Partial and indeterminate
    lengths are refused: no key packet uses them."""
    pos, end = 0, len(data)
    while pos < end:
        first = data[pos]
        if not first & 0x80:
            raise _damaged()
        start, pos = pos, pos + 1
        try:
            if first & 0x40:  # new format
                tag = first & 0x3F
                octet = data[pos]
                if octet < 192:
                    length, pos = octet, pos + 1
                elif octet < 224:
                    length = ((octet - 192) << 8) + data[pos + 1] + 192
                    pos += 2
                elif octet == 255:
                    length = int.from_bytes(data[pos + 1:pos + 5], "big")
                    pos += 5
                else:
                    raise _refuse("Lunghezza parziale non supportata.",
                                  "Partial packet lengths are not supported.")
            else:  # old format
                tag = (first >> 2) & 0x0F
                kind = first & 3
                if kind == 3:
                    raise _refuse("Lunghezza indeterminata non supportata.",
                                  "Indeterminate packet lengths are not "
                                  "supported.")
                size = (1, 2, 4)[kind]
                length = int.from_bytes(data[pos:pos + size], "big")
                pos += size
        except IndexError:
            raise _damaged() from None
        if pos + length > end:
            raise _damaged()
        yield tag, data[pos:pos + length], data[start:pos + length]
        pos += length


def write_packet(tag: int, body: bytes) -> bytes:
    """One packet with a new-format header."""
    n = len(body)
    if n < 192:
        length = bytes([n])
    elif n < 8384:
        length = bytes([((n - 192) >> 8) + 192, (n - 192) & 0xFF])
    else:
        length = b"\xff" + n.to_bytes(4, "big")
    return bytes([0xC0 | tag]) + length + body


def _mpi(body: bytes, pos: int) -> int:
    """Position after the MPI that starts at `pos`."""
    if pos + 2 > len(body):
        raise _damaged()
    pos += 2 + (int.from_bytes(body[pos:pos + 2], "big") + 7) // 8
    if pos > len(body):
        raise _damaged()
    return pos


def _counted(body: bytes, pos: int) -> int:
    """Position after the length-prefixed field that starts at `pos`."""
    if pos >= len(body) or body[pos] in (0, 255):
        raise _damaged()
    pos += 1 + body[pos]
    if pos > len(body):
        raise _damaged()
    return pos


def public_length(body: bytes) -> int:
    """Length of the public part of a version 4 secret-key packet body."""
    if not body or body[0] != 4:
        raise _refuse("Solo le chiavi OpenPGP versione 4 sono supportate.",
                      "Only version 4 OpenPGP keys are supported.")
    if len(body) < 6:
        raise _damaged()
    algo = body[5]
    pos = 6
    if algo in _RSA:
        pos = _mpi(body, _mpi(body, pos))
    elif algo in (19, 22):
        pos = _mpi(body, _counted(body, pos))
    elif algo == 18:
        pos = _counted(body, _mpi(body, _counted(body, pos)))
    else:
        raise _refuse(f"Algoritmo di chiave {algo} non supportato.",
                      f"Key algorithm {algo} is not supported.")
    return pos


def s2k_key(passphrase: bytes, s2k_type: int, hash_algo: int, salt: bytes,
            count_octet: int, key_len: int) -> bytes:
    """Derive a key from a passphrase (RFC 4880 section 3.7)."""
    name = _HASHES.get(hash_algo)
    if name is None or s2k_type not in (0, 1, 3):
        raise _refuse("Protezione della chiave non supportata.",
                      "Unsupported key protection.")
    material = passphrase if s2k_type == 0 else salt + passphrase
    if s2k_type == 3:
        count = (16 + (count_octet & 15)) << ((count_octet >> 4) + 6)
        total = max(count, len(material))
    else:
        total = len(material)
    reps, rest = divmod(total, len(material)) if material else (0, 0)
    stream = material * reps + material[:rest]
    out = b""
    while len(out) < key_len:
        h = hashlib.new(name)
        h.update(b"\0" * (len(out) // h.digest_size))
        h.update(stream)
        out += h.digest()
    return out[:key_len]


def _is_secret(tag: int) -> bool:
    return tag in (TAG_SECRET_KEY, TAG_SECRET_SUBKEY)


def _split_secret(body: bytes) -> Tuple[int, int]:
    """(length of the public part, usage octet) of a secret packet body."""
    cut = public_length(body)
    if cut >= len(body):
        raise _damaged()
    return cut, body[cut]


def _protect_body(body: bytes, passphrase: bytes) -> bytes:
    cut, usage = _split_secret(body)
    if usage != 0:
        raise _refuse("La chiave segreta è già protetta.",
                      "The secret key is already protected.")
    rest = body[cut + 1:]
    secret, checksum = rest[:-2], rest[-2:]
    if len(rest) < 2 or sum(secret) % 65536 != int.from_bytes(checksum, "big"):
        raise _damaged()
    salt, iv = os.urandom(8), os.urandom(16)
    key = s2k_key(passphrase, _S2K_ITERATED, _HASH_SHA256, salt,
                  _COUNT_OCTET, 32)
    enc = Cipher(algorithms.AES(key), CFB(iv)).encryptor()
    sealed = enc.update(secret + hashlib.sha1(secret).digest()) + enc.finalize()
    head = bytes([_USAGE_SHA1, _AES256, _S2K_ITERATED, _HASH_SHA256])
    return body[:cut] + head + salt + bytes([_COUNT_OCTET]) + iv + sealed


def _protection(body: bytes) -> Optional[tuple]:
    """How a secret packet body is locked: None when it is not, else
    (cut, cipher, s2k_type, hash_algo, salt, count_octet, iv, sealed).
    Raises UnsupportedKey for anything this code does not read."""
    cut, usage = _split_secret(body)
    if usage == 0:
        return None
    unsupported = _refuse("Protezione della chiave non supportata.",
                          "Unsupported key protection.")
    if usage != _USAGE_SHA1:  # 253 AEAD, 255 checksum, or a bare cipher octet
        raise unsupported
    head = body[cut + 1:cut + 4]
    if len(head) < 3:
        raise _damaged()
    cipher, s2k_type, hash_algo = head
    if (cipher not in _AES_KEY_LEN or s2k_type not in (0, 1, 3)
            or hash_algo not in _READ_HASHES):
        raise unsupported
    pos = cut + 4
    salt_len = 0 if s2k_type == 0 else 8
    salt = body[pos:pos + salt_len]
    pos += salt_len
    count_octet = 0
    if s2k_type == 3:
        count_octet = body[pos] if pos < len(body) else 0
        pos += 1
    iv, sealed = body[pos:pos + 16], body[pos + 16:]
    if len(iv) < 16 or len(sealed) < 20:
        raise _damaged()
    return cut, cipher, s2k_type, hash_algo, salt, count_octet, iv, sealed


def _normal_mpis(algo: int, secret: bytes) -> bytes:
    """The secret MPIs with the bit counts RFC 4880 asks for. GnuPG writes
    an Ed25519 or Curve25519 secret with a count one above the real one
    (256 for a value of 255 bits); the library refuses such an MPI once the
    key is unprotected. Only algorithms whose secret is made of MPIs are
    touched (others, such as the raw octet strings of RFC 9580, come back
    as they are), and so is anything that does not parse exactly."""
    if algo not in _MPI_SECRET:
        return secret
    out = b""
    pos = 0
    for _ in range(_MPI_SECRET[algo]):
        if pos + 2 > len(secret):
            return secret
        end = pos + 2 + (int.from_bytes(secret[pos:pos + 2], "big") + 7) // 8
        if end > len(secret):
            return secret
        value = secret[pos + 2:end].lstrip(bytes(1))
        bits = len(value) * 8 - (8 - value[0].bit_length()) if value else 0
        out += bits.to_bytes(2, "big") + value
        pos = end
    return out if pos == len(secret) else secret


def _open_body(body: bytes, params: tuple, passphrase: bytes) -> bytes:
    cut, cipher, s2k_type, hash_algo, salt, count_octet, iv, sealed = params
    key = s2k_key(passphrase, s2k_type, hash_algo, salt, count_octet,
                  _AES_KEY_LEN[cipher])
    dec = Cipher(algorithms.AES(key), CFB(iv)).decryptor()
    plain = dec.update(sealed) + dec.finalize()
    secret, digest = plain[:-20], plain[-20:]
    if not hmac.compare_digest(hashlib.sha1(secret).digest(), digest):
        raise WrongPassphrase("Passphrase errata.", "Wrong passphrase.")
    secret = _normal_mpis(body[5], secret)
    checksum = (sum(secret) % 65536).to_bytes(2, "big")
    return body[:cut] + b"\0" + secret + checksum


def _secret_packets(data: bytes) -> list:
    found = [(tag, body, raw) for tag, body, raw in read_packets(data)
             if _is_secret(tag)]
    if not found:
        raise _refuse("Nessuna chiave segreta trovata.",
                      "No secret key found.")
    return found


def is_protected(key_bytes: bytes) -> bool:
    """True when any secret packet carries a passphrase protection."""
    return any(_split_secret(body)[1] != 0
               for tag, body, _raw in read_packets(key_bytes)
               if _is_secret(tag))


def protect(tsk_bytes: bytes, passphrase: str) -> bytes:
    """Lock every secret packet of a binary key with `passphrase`.

    Other packets are copied unchanged. Raises UnsupportedKey when there is
    no secret packet, when one is already protected or when it is not a
    version 4 key we understand."""
    _secret_packets(tsk_bytes)
    phrase = passphrase.encode("utf-8")
    return b"".join(
        write_packet(tag, _protect_body(body, phrase)) if _is_secret(tag)
        else raw for tag, body, raw in read_packets(tsk_bytes))


def unprotect(key_bytes: bytes, passphrase: Optional[str]) -> bytes:
    """Remove the passphrase from every secret packet of a binary key.

    Unprotected packets are returned as they are (rewritten with a new-format
    header only when a packet changes); other packets are copied unchanged.
    Raises PassphraseRequired, WrongPassphrase or UnsupportedKey."""
    _secret_packets(key_bytes)
    phrase = None if passphrase is None else passphrase.encode("utf-8")
    packets = [(tag, body, raw, _protection(body) if _is_secret(tag) else None)
               for tag, body, raw in read_packets(key_bytes)]
    # every packet is checked before any passphrase is asked for, so an
    # unsupported protection is reported as such
    if phrase is None and any(params for *_rest, params in packets):
        raise PassphraseRequired(
            "La chiave è protetta da una passphrase: serve per aprirla.",
            "The key is protected by a passphrase, which is needed to open it.")
    out = []
    for tag, body, raw, params in packets:
        if params:
            raw = write_packet(tag, _open_body(body, params, phrase))
        elif _is_secret(tag):
            raw = _normal_open(tag, body, raw)
        out.append(raw)
    return b"".join(out)


def _normal_open(tag: int, body: bytes, raw: bytes) -> bytes:
    """An unprotected secret packet with the bit counts of `_normal_mpis`
    (GnuPG's inflated count is written unprotected too). The packet comes
    back as it is when nothing changes or its checksum is wrong."""
    cut = public_length(body)
    secret, checksum = body[cut + 1:-2], body[-2:]
    if (len(body) < cut + 3 or body[cut] != 0
            or sum(secret) % 65536 != int.from_bytes(checksum, "big")):
        return raw
    normal = _normal_mpis(body[5], secret)
    if normal == secret:
        return raw
    return write_packet(tag, body[:cut + 1] + normal
                        + (sum(normal) % 65536).to_bytes(2, "big"))


# ── the backup file ─────────────────────────────────────────────────

_PROBE = b"hello"
_ARMOR = re.compile(rb"-----BEGIN PGP [A-Z ]+-----\r?\n(.*?)-----END PGP",
                    re.S)


def _dearmor(data: bytes) -> bytes:
    """The binary packets of ASCII-armored data; binary data is returned as
    it is. Text outside the armor is ignored."""
    blocks = _ARMOR.findall(data)
    if not blocks:
        return data
    out = b""
    for block in blocks:
        lines = block.decode("ascii", "replace").splitlines()
        if "" in lines:  # armor headers end at the first empty line
            lines = lines[lines.index("") + 1:]
        payload = "".join(ln.strip() for ln in lines if not ln.startswith("="))
        out += base64.b64decode(payload)
    return out


def _as_bytes(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode("ascii")


def _encrypted_to(p, cert) -> bytes:
    return _as_bytes(p.encrypt(bytes=_PROBE, recipients=[cert]))


def _opens(p, key, message: bytes, passphrase: Optional[str] = None) -> bool:
    """True when `key` decrypts `message`; False on any refusal."""
    try:
        dec = key.decryptor(passphrase) if passphrase else key.decryptor()
        return p.decrypt(bytes=message, decryptor=dec).bytes == _PROBE
    except Exception:
        return False


def _signs(p, key) -> bool:
    try:
        return bool(p.sign(key.signer(), _PROBE))
    except Exception:
        return False


def _secret_material(plain_key: bytes) -> List[bytes]:
    """The secret numbers of every secret packet of an unprotected key."""
    out = []
    for tag, body, _raw in read_packets(plain_key):
        if _is_secret(tag):
            # after the usage octet, without the checksum; [2:] drops the
            # length header of the first MPI, which says nothing secret
            out.append(body[public_length(body) + 1:-2][2:])
    return out


def _check_failed(it: str, en: str) -> BackupError:
    return BackupError("Il controllo del file di backup non è riuscito: " + it,
                       "The backup file failed its check: " + en)


def _contents(data: bytes) -> list:
    """(tag, body) of each packet: what a key holds, whatever the header
    format (a key restored from GnuPG is stored with its old-format
    headers, and `unprotect` writes new-format ones)."""
    return [(tag, body) for tag, body, _raw in read_packets(data)]


def _keys_in(packets: bytes) -> List[bytes]:
    """The binary packets of a key file cut into keys, one per primary key
    packet."""
    keys: List[bytes] = []
    for tag, _body, raw in read_packets(packets):
        if tag == TAG_SECRET_KEY or not keys:
            keys.append(b"")
        keys[-1] += raw
    return keys


def _check_protection(written: bytes, plain: bytes, passphrase: str) -> None:
    """Every secret packet of the written key opens with the passphrase, to
    exactly what `plain` holds, and not without it."""
    # Looked at packet by packet: one locked subkey is enough for the key
    # as a whole to ask for a passphrase.
    if any(_is_secret(tag) and _protection(body) is None
           for tag, body, _raw in read_packets(written)):
        raise _check_failed("una parte segreta della chiave non è protetta.",
                            "a secret part of the key is not protected.")
    try:
        opened = _contents(unprotect(written, passphrase))
    except BackupError:
        opened = None
    if opened != _contents(plain):
        raise _check_failed("la passphrase non apre la chiave.",
                            "the passphrase does not open the key.")
    try:
        unprotect(written, None)
    except PassphraseRequired:
        return
    except BackupError:
        pass
    raise _check_failed("la chiave si apre senza passphrase.",
                        "the key opens without a passphrase.")


def _self_check(p, path: Path, plain_keys: List[bytes],
                passphrase: str) -> None:
    """Read the written file back and prove it is the protected backup of
    exactly these keys. Raises BackupError."""
    data = path.read_bytes()
    try:
        parts = p.Tsk.split_bytes(data)
    except Exception:
        raise _check_failed("il file non si legge.",
                            "the file cannot be read.") from None
    packets = _dearmor(data)
    if packets == data:  # not armored: the search below would prove nothing
        raise _check_failed("il file non è in formato ASCII.",
                            "the file is not ASCII-armored.")
    written = _keys_in(packets)
    if len(parts) != len(plain_keys) or len(written) != len(plain_keys):
        raise _check_failed("numero di chiavi diverso.",
                            "the number of keys differs.")
    for part, key, plain in zip(parts, written, plain_keys, strict=True):
        original = p.Tsk.from_bytes(plain)
        cert = part.extract_certificate()
        if cert.fingerprint != original.extract_certificate().fingerprint:
            raise _check_failed("l'impronta è cambiata.",
                                "the fingerprint changed.")
        # Every packet, primary key included, on the bytes of the file: the
        # library probe below only proves the encryption subkey is locked.
        _check_protection(key, plain, passphrase)
        try:
            # Not for an expired or revoked key, which the library refuses
            # to decrypt with, nor for one with no usable encryption subkey.
            message = None if _lapsed(cert) else _encrypted_to(p, cert)
        except Exception:
            message = None
        if message is not None:
            if not _opens(p, part, message, passphrase):
                raise _check_failed("la passphrase non apre la chiave.",
                                    "the passphrase does not open the key.")
            if _opens(p, part, message):
                raise _check_failed("la chiave si apre senza passphrase.",
                                    "the key opens without a passphrase.")
        if any(secret in packets for secret in _secret_material(plain)):
            raise _check_failed("il materiale segreto è in chiaro.",
                                "the secret material is in the clear.")


def export_backup(path: Path, passphrase: str, address: Optional[str] = None,
                  force: bool = False) -> List[Dict]:
    """Write every own key (or those of one address) to `path`, protected by
    `passphrase`, as one ASCII-armored private key block.

    The file is written beside its destination, checked, and only then moved
    into place: a failure leaves no file and an existing `path` untouched.
    Returns {"address", "fingerprint", "state"} per key written. Raises
    BackupError."""
    p = pgp._lib()
    path = Path(path)
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(
            f"La passphrase deve avere almeno {MIN_PASSPHRASE} caratteri.",
            f"The passphrase must have at least {MIN_PASSPHRASE} characters.")
    if path.exists() and not force:
        raise BackupError("Il file esiste già: usa --force per sovrascriverlo.",
                          "The file already exists: use --force to overwrite it.")
    keys = pgp.own_key_bytes(address)
    if not keys:
        raise BackupError("Nessuna chiave da salvare.", "There is no key to back up.")
    armored = _as_bytes(p.armor(
        b"".join(protect(raw, passphrase) for _a, _s, raw in keys),
        p.ArmorKind.SecretKey))
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        try:
            with os.fdopen(os.open(temp, flags, 0o600), "wb") as f:
                f.write(armored)
            try:
                _self_check(p, temp, [raw for _a, _s, raw in keys], passphrase)
            except (BackupError, OSError):
                raise
            except Exception:
                raise _check_failed("errore imprevisto.",
                                    "unexpected error.") from None
            os.replace(temp, path)
        except BaseException:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass  # the error that brought us here is the one to report
            raise
    except OSError as e:
        raise BackupError("Impossibile scrivere il file di backup: "
                          + (e.strerror or "errore"),
                          "Cannot write the backup file: "
                          + (e.strerror or "error")) from None
    return [{"address": a, "state": s,
             "fingerprint": p.Tsk.from_bytes(raw).extract_certificate().fingerprint}
            for a, s, raw in keys]


def _addresses(cert, configured: set) -> List[str]:
    """Our addresses a key is for: its user IDs that are configured accounts,
    else the address of its first user ID."""
    found = []
    for uid in cert.user_ids:
        addr = pgp.normalize(parseaddr(str(uid))[1])
        # "No Address" parses to "no": only a real address counts
        if "@" in addr and addr not in found:
            found.append(addr)
    ours = [a for a in found if a in configured]
    return ours or found[:1]


def _has_secret(raw: bytes) -> bool:
    try:
        return any(_is_secret(tag) for tag, _b, _r in read_packets(raw))
    except UnsupportedKey:
        return True  # damaged: let `unprotect` say so


def _lapsed(cert) -> str:
    """Why a certificate is revoked or expired, in the user's language;
    empty when it is neither."""
    if cert.is_revoked:
        return pgp.say("la chiave è revocata", "the key is revoked")
    expiry = cert.expiration
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=datetime.timezone.utc)
    if expiry is not None and expiry <= datetime.datetime.now(
            datetime.timezone.utc):
        return pgp.say("la chiave è scaduta", "the key has expired")
    return ""


def _vet(p, plain: bytes, fingerprint: str) -> Tuple[bool, str]:
    """Whether an unprotected key may become the active one, and why not.
    Raises UnsupportedKey when it cannot be used even for decrypting."""
    try:
        key = p.Tsk.from_bytes(plain)
        cert = key.extract_certificate()
    except Exception:
        raise _refuse("Chiave non leggibile.", "The key cannot be read.") from None
    if cert.fingerprint != fingerprint:
        raise _refuse("L'impronta non corrisponde.",
                      "The fingerprint does not match.")
    reason = _lapsed(cert)
    # An expired key cannot decrypt in the library, and a revoked one may not:
    # for those the integrity check of `unprotect` is all there is.
    if not reason:
        try:
            message = _encrypted_to(p, cert)
        except Exception:
            raise _refuse("La chiave non ha una sottochiave di cifratura "
                          "utilizzabile.",
                          "The key has no usable encryption subkey.") from None
        if not _opens(p, key, message):
            raise _refuse("La chiave non decifra un messaggio di prova.",
                          "The key does not decrypt a test message.")
    if not reason and not _signs(p, key):
        reason = pgp.say("la chiave non può firmare",
                         "the key cannot sign")
    return not reason, reason


def import_backup(path: Path, passphrase: Optional[str] = None) -> List[Dict]:
    """Restore the keys of a backup file (armored or binary).

    Every key is opened and checked before anything is stored, and what
    passes goes to the store in one call. Returns {"address", "fingerprint",
    "outcome", "reason"} per key and address, outcome "active", "retired",
    "present" or "refused". Raises PassphraseRequired or WrongPassphrase
    (nothing is stored) and BackupError when the file holds no secret key."""
    p = pgp._lib()
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise BackupError("Impossibile leggere il file: " + (e.strerror or "errore"),
                          "Cannot read the file: " + (e.strerror or "error")
                          ) from None
    try:
        try:
            parts = [(part, bytes(part)) for part in p.Tsk.split_bytes(data)]
        except Exception:
            # The library refuses an unprotected primary key whose secret
            # carries an inflated bit count (see `_normal_mpis`): try again
            # with the counts set right. Only then: a file refused for any
            # other reason stays refused.
            packets = _dearmor(data)
            fixed = b"".join(_normal_open(tag, body, raw) if _is_secret(tag) else raw
                             for tag, body, raw in read_packets(packets))
            if fixed == packets:
                raise
            parts = [(part, bytes(part)) for part in p.Tsk.split_bytes(fixed)]
    except Exception:
        raise BackupError("Il file non è una chiave OpenPGP.",
                          "The file is not an OpenPGP key.") from None
    parts = [(part, raw) for part, raw in parts if _has_secret(raw)]
    if not parts:
        raise BackupError("Nessuna chiave segreta nel file.",
                          "There is no secret key in the file.")
    from . import accounts
    configured = {pgp.normalize(a.get("email", ""))
                  for a in accounts.get_accounts()}

    results: List[Optional[Dict]] = []
    entries: List[Dict] = []
    slots: List[int] = []  # index in `results` of each entry
    for part, raw in parts:
        cert = part.extract_certificate()
        fpr = cert.fingerprint
        addresses = _addresses(cert, configured)
        try:
            plain = unprotect(raw, passphrase)
            if not addresses:
                raise _refuse("La chiave non ha un indirizzo.",
                              "The key has no address.")
            may_be_active, why = _vet(p, plain, fpr)
        except UnsupportedKey as e:
            results.append({"address": addresses[0] if addresses else "",
                            "fingerprint": fpr,
                            "outcome": "refused", "reason": e.text()})
            continue
        for addr in addresses:
            slots.append(len(results))
            results.append({"address": addr, "fingerprint": fpr,
                            "outcome": "", "reason": why})
            entries.append({"address": addr, "key": plain,
                            "may_be_active": may_be_active})
    if entries:
        for slot, done in zip(slots, pgp.install_keys(entries), strict=True):
            result = results[slot]
            result["outcome"] = done["outcome"]
            if done["outcome"] == "active":
                result["reason"] = ""
            elif done["outcome"] == "present":
                result["reason"] = pgp.say("già presente", "already held")
            elif not result["reason"]:
                result["reason"] = pgp.say(
                    "un'altra chiave per questo indirizzo viene prima",
                    "another key for this address comes first")
    return results
