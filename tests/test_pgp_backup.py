"""Passphrase protection of OpenPGP secret keys (core/pgp_backup.py)."""
import base64
import email
import hashlib
import os
import re
import sqlite3
import time
from argparse import Namespace
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

pysequoia = pytest.importorskip("pysequoia")

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms  # noqa: E402

from gigamail import cli, policy  # noqa: E402
from gigamail.core import pgp, pgp_backup  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402

ME = "mario.rossi@example.com"
PASSPHRASE = "correct horse 42"


@pytest.fixture(autouse=True)
def _empty_store():
    path = db_path(pgp.DB_NAME)
    if path.exists():
        path.unlink()
    yield


@pytest.fixture()
def tsk():
    return pysequoia.Tsk.generate(user_id=f"<{ME}>")


def _opens(key, message, password=None):
    """True when `key` decrypts `message`; False on any refusal."""
    try:
        dec = key.decryptor(password) if password else key.decryptor()
        return pysequoia.decrypt(bytes=message, decryptor=dec).bytes == b"hello"
    except Exception:
        return False


def _to(cert):
    out = pysequoia.encrypt(bytes=b"hello", recipients=[cert])
    return out if isinstance(out, bytes) else str(out).encode()


def test_protect_keeps_the_fingerprint(tsk):
    locked = pysequoia.Tsk.from_bytes(pgp_backup.protect(bytes(tsk), PASSPHRASE))
    assert (locked.extract_certificate().fingerprint
            == tsk.extract_certificate().fingerprint)


def test_protected_key_opens_only_with_the_passphrase(tsk):
    message = _to(tsk.extract_certificate())
    locked = pysequoia.Tsk.from_bytes(pgp_backup.protect(bytes(tsk), PASSPHRASE))
    assert _opens(locked, message, PASSPHRASE)
    assert not _opens(locked, message, "wrong passphrase")
    assert not _opens(locked, message)


def test_protected_key_signs_with_the_passphrase(tsk):
    locked = pysequoia.Tsk.from_bytes(pgp_backup.protect(bytes(tsk), PASSPHRASE))
    assert pysequoia.sign(locked.signer(PASSPHRASE), b"hello")


def test_secret_material_is_not_in_the_protected_bytes(tsk):
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    for tag, body, _raw in pgp_backup.read_packets(bytes(tsk)):
        if tag in (5, 7):
            secret = body[pgp_backup.public_length(body) + 1:-2]
            assert secret[2:] not in locked


def test_only_secret_packets_change(tsk):
    before = list(pgp_backup.read_packets(bytes(tsk)))
    after = list(pgp_backup.read_packets(pgp_backup.protect(bytes(tsk), PASSPHRASE)))
    assert [t for t, _, _ in before] == [t for t, _, _ in after]
    for (tag, _b, raw_before), (_t, _b2, raw_after) in zip(before, after, strict=True):
        assert (raw_before == raw_after) == (tag not in (5, 7))


def test_each_packet_gets_its_own_salt_and_iv(tsk):
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    tails = [body[pgp_backup.public_length(body):][:29]
             for tag, body, _ in pgp_backup.read_packets(locked) if tag in (5, 7)]
    assert all(t[:4] == bytes([254, 9, 3, 8]) and t[12] == 0xEE for t in tails)
    assert len({t[4:12] for t in tails}) == len(tails)      # salts
    assert len({t[13:29] for t in tails}) == len(tails)     # IVs


def test_protecting_twice_is_refused(tsk):
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.protect(locked, PASSPHRASE)


def test_non_ascii_passphrase(tsk):
    phrase = "chiave-è-più-lunga"
    message = _to(tsk.extract_certificate())
    locked = pysequoia.Tsk.from_bytes(pgp_backup.protect(bytes(tsk), phrase))
    assert _opens(locked, message, phrase)


def test_version_6_key_is_refused():
    v6 = pysequoia.Tsk.generate(user_id=f"<{ME}>", profile=pysequoia.Profile.RFC9580)
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.protect(bytes(v6), PASSPHRASE)


def test_protect_refuses_a_public_key(tsk):
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.protect(bytes(tsk.extract_certificate()), PASSPHRASE)


def test_no_secret_packet_means_nothing_to_unlock(tsk):
    cert = bytes(tsk.extract_certificate())
    assert not pgp_backup.is_protected(cert)
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.unprotect(cert, None)


def _protect_with(tsk_bytes, passphrase, cipher, key_len, s2k_type, hash_algo):
    """Protect like another OpenPGP client would, with chosen parameters."""
    phrase = passphrase.encode("utf-8")
    out = []
    for tag, body, raw in pgp_backup.read_packets(tsk_bytes):
        if tag not in (5, 7):
            out.append(raw)
            continue
        cut = pgp_backup.public_length(body)
        secret = body[cut + 1:-2]
        salt, iv = os.urandom(8), os.urandom(16)
        key = pgp_backup.s2k_key(phrase, s2k_type, hash_algo, salt, 0xEE, key_len)
        enc = Cipher(algorithms.AES(key), pgp_backup.CFB(iv)).encryptor()
        sealed = enc.update(secret + hashlib.sha1(secret).digest()) + enc.finalize()
        spec = bytes([s2k_type, hash_algo])
        if s2k_type in (1, 3):
            spec += salt
        if s2k_type == 3:
            spec += bytes([0xEE])
        head = bytes([254, cipher]) + spec
        out.append(pgp_backup.write_packet(tag, body[:cut] + head + iv + sealed))
    return b"".join(out)


def _with_secret_tail(tsk_bytes, tail):
    """Replace what follows the public part of the first secret packet."""
    out, done = [], False
    for tag, body, raw in pgp_backup.read_packets(tsk_bytes):
        if tag in (5, 7) and not done:
            cut = pgp_backup.public_length(body)
            raw = pgp_backup.write_packet(tag, body[:cut] + tail + os.urandom(64))
            done = True
        out.append(raw)
    return b"".join(out)


def _old_format(tag, body, length_octets):
    kind = {1: 0, 2: 1, 4: 2}[length_octets]
    return (bytes([0x80 | tag << 2 | kind])
            + len(body).to_bytes(length_octets, "big") + body)


def test_protect_then_unprotect_returns_the_original(tsk):
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    assert pgp_backup.unprotect(locked, PASSPHRASE) == bytes(tsk)


def test_unprotect_wrong_passphrase(tsk):
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    with pytest.raises(pgp_backup.WrongPassphrase):
        pgp_backup.unprotect(locked, "wrong passphrase")


def test_unprotect_needs_a_passphrase(tsk):
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    assert pgp_backup.is_protected(locked)
    with pytest.raises(pgp_backup.PassphraseRequired):
        pgp_backup.unprotect(locked, None)


def test_unprotected_key_passes_through(tsk):
    assert not pgp_backup.is_protected(bytes(tsk))
    assert pgp_backup.unprotect(bytes(tsk), None) == bytes(tsk)


@pytest.mark.parametrize("cipher,key_len", [(7, 16), (8, 24), (9, 32)])
@pytest.mark.parametrize("s2k_type", [0, 1, 3])
@pytest.mark.parametrize("hash_algo", [2, 8, 10])
def test_unprotect_reads_other_clients_parameters(tsk, cipher, key_len,
                                                  s2k_type, hash_algo):
    locked = _protect_with(bytes(tsk), PASSPHRASE, cipher, key_len,
                           s2k_type, hash_algo)
    assert pgp_backup.unprotect(locked, PASSPHRASE) == bytes(tsk)
    # an independent reader agrees the passphrase is the right one
    key = pysequoia.Tsk.from_bytes(locked)
    assert _opens(key, _to(tsk.extract_certificate()), PASSPHRASE)


@pytest.mark.parametrize("tail", [
    bytes([253, 9, 2]),           # AEAD
    bytes([254, 9, 4]),           # Argon2
    bytes([254, 9, 101]),         # GnuPG stub
    bytes([255, 9, 3, 8]),        # checksum instead of SHA-1
    bytes([9]),                   # legacy: cipher octet as usage
    bytes([254, 3, 3, 8]),        # CAST5
    bytes([254, 9, 3, 1]),        # MD5
    bytes([254, 9, 3, 3]),        # RIPEMD-160
])
def test_unprotect_refuses_what_it_does_not_know(tsk, tail):
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.unprotect(_with_secret_tail(bytes(tsk), tail), PASSPHRASE)


def test_old_format_headers_and_long_lengths(tsk):
    """GnuPG writes old-format headers; a big key needs 2- and 4-octet
    lengths. Re-encode a protected key that way and read it back."""
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    packets = list(pgp_backup.read_packets(locked))
    sizes = []
    for i, (_tag, body, _raw) in enumerate(packets):
        n = (1, 2, 4)[i % 3]
        while len(body) >= 256 ** n and n < 4:
            n = 4 if n == 2 else 2
        sizes.append(n)
    assert {1, 2, 4} <= set(sizes)
    old = b"".join(_old_format(tag, body, n)
                   for (tag, body, _), n in zip(packets, sizes, strict=True))
    assert [t for t, _, _ in pgp_backup.read_packets(old)] == [
        t for t, _, _ in packets]
    # packets other than secret keys keep their old-format header byte for
    # byte, so compare what they carry rather than the raw bytes
    opened = pgp_backup.unprotect(old, PASSPHRASE)
    assert [(t, b) for t, b, _ in pgp_backup.read_packets(opened)] == [
        (t, b) for t, b, _ in pgp_backup.read_packets(bytes(tsk))]


def test_unsupported_primary_is_reported_before_a_passphrase_is_asked(tsk):
    """A protected subkey must not hide that the primary is unsupported."""
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    broken = _with_secret_tail(locked, bytes([253, 9, 2]))
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.unprotect(broken, None)


def test_unprotected_primary_with_protected_subkeys(tsk):
    """Some clients leave the primary key open and lock only the subkeys."""
    out = []
    for tag, body, raw in pgp_backup.read_packets(bytes(tsk)):
        if tag == pgp_backup.TAG_SECRET_SUBKEY:
            raw = pgp_backup.write_packet(
                tag, pgp_backup._protect_body(body, PASSPHRASE.encode()))
        out.append(raw)
    mixed = b"".join(out)
    assert pgp_backup.is_protected(mixed)
    assert pgp_backup.unprotect(mixed, PASSPHRASE) == bytes(tsk)


# ── retired keys in the store ───────────────────────────────────────

def _fpr(key):
    return key.extract_certificate().fingerprint


def _entry(key, addr=ME, may_be_active=True):
    return {"address": addr, "key": bytes(key), "may_be_active": may_be_active}


def _encrypted_mail_to(cert):
    inner = b"Content-Type: text/plain" + bytes([13, 10, 13, 10]) + b"hello"
    ciphertext = pysequoia.encrypt(bytes=inner, recipients=[cert])
    if not isinstance(ciphertext, bytes):
        ciphertext = str(ciphertext).encode()
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"], outer["Subject"] = (
        "anna.bianchi@example.com", ME, "...")
    outer.attach(MIMEApplication(b"Version: 1" + bytes([10]), "pgp-encrypted"))
    outer.attach(MIMEApplication(ciphertext, "octet-stream"))
    return email.message_from_bytes(outer.as_bytes())


def _keydata_fingerprint(header):
    keydata = re.search(r"keydata=(.*)", header).group(1)
    raw = base64.b64decode(re.sub(r"\s+", "", keydata))
    return pysequoia.Cert.from_bytes(raw).fingerprint


def _mail_signed_and_encrypted_by_me_to_me():
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = ME, ME, "Note to self"
    msg.attach(MIMEText("hello", "plain", "utf-8"))
    sent = pgp.encrypt_message(msg, ME, [ME])
    return email.message_from_bytes(sent.as_bytes())


def test_list_own_keys_never_creates_one():
    assert pgp.list_own_keys() == []
    assert pgp.own_key_bytes() == []
    assert pgp.own_key(ME, create=False) is None


def test_install_into_an_empty_store(tsk):
    out = pgp.install_keys([_entry(tsk)])
    assert [o["outcome"] for o in out] == ["active"]
    assert out[0]["fingerprint"] == _fpr(tsk)
    assert pgp.own_fingerprint(ME) == _fpr(tsk)


def test_install_over_an_interim_key_retires_it(tsk):
    interim = pgp.own_key(ME)                      # generated on first use
    pgp.install_keys([_entry(tsk)])
    states = {k["fingerprint"]: k["state"] for k in pgp.list_own_keys()}
    assert states == {_fpr(tsk): "active", _fpr(interim): "retired"}


def test_mail_to_the_interim_key_still_opens(tsk):
    interim = pgp.own_key(ME)
    mail = _encrypted_mail_to(interim.extract_certificate())
    pgp.install_keys([_entry(tsk)])
    _opened, info = pgp.open_message(mail, ME)
    assert info["decrypted"]


def test_retired_key_is_not_advertised_or_used_to_sign(tsk):
    interim = pgp.own_key(ME)
    pgp.install_keys([_entry(tsk)])
    header = pgp.autocrypt_header(ME)
    assert _keydata_fingerprint(header) == _fpr(tsk) != _fpr(interim)


def test_installing_the_same_file_twice_changes_nothing(tsk):
    pgp.install_keys([_entry(tsk)])
    before = pgp.list_own_keys()
    assert [o["outcome"] for o in pgp.install_keys([_entry(tsk)])] == ["present"]
    assert pgp.list_own_keys() == before


def test_a_key_already_retired_is_not_promoted(tsk):
    interim = pgp.own_key(ME)
    pgp.install_keys([_entry(tsk)])
    out = pgp.install_keys([_entry(interim)])
    assert out[0]["outcome"] == "present"
    assert pgp.own_fingerprint(ME) == _fpr(tsk)


def test_first_key_in_the_file_is_the_active_one(tsk):
    second = pysequoia.Tsk.generate(user_id=f"<{ME}>")
    out = pgp.install_keys([_entry(tsk), _entry(second)])
    assert [o["outcome"] for o in out] == ["active", "retired"]


def test_a_decrypt_only_key_never_becomes_active(tsk):
    current = pgp.own_key(ME)
    out = pgp.install_keys([_entry(tsk, may_be_active=False)])
    assert out[0]["outcome"] == "retired"
    assert pgp.own_fingerprint(ME) == _fpr(current)


def test_own_key_bytes_lists_active_first(tsk):
    pgp.own_key(ME)
    pgp.install_keys([_entry(tsk)])
    assert [(a, s) for a, s, _ in pgp.own_key_bytes()] == [(ME, "active"),
                                                          (ME, "retired")]
    assert pgp.own_key_bytes()[0][2] == bytes(tsk)
    assert pgp.own_key_bytes("anna.bianchi@example.com") == []


def test_mail_signed_by_a_retired_key_still_shows_signed_by(tsk):
    pgp.own_key(ME)
    mail = _mail_signed_and_encrypted_by_me_to_me()
    pgp.install_keys([_entry(tsk)])
    _opened, info = pgp.open_message(mail, ME)
    assert info["signature_valid"] and info["signer"] == ME


def test_install_stops_whole_on_bad_bytes_and_stores_nothing(tsk):
    entries = [_entry(tsk), {"address": "anna.bianchi@example.com",
                             "key": b"garbage", "may_be_active": True}]
    with pytest.raises(RuntimeError):
        pgp.install_keys(entries)
    assert pgp.list_own_keys() == []


def test_a_store_made_before_retired_keys_existed_still_works(tsk):
    interim = pysequoia.Tsk.generate(user_id=f"<{ME}>")
    conn = sqlite3.connect(str(db_path(pgp.DB_NAME)))
    with conn:
        conn.execute("""CREATE TABLE own_keys (
            address TEXT PRIMARY KEY, secret_enc TEXT NOT NULL,
            fingerprint TEXT NOT NULL, created_at REAL NOT NULL)""")
        conn.execute("INSERT INTO own_keys VALUES (?,?,?,?)",
                     (ME, pgp._protect(bytes(interim)), _fpr(interim), 1.0))
    conn.close()
    assert [k["state"] for k in pgp.list_own_keys()] == ["active"]
    pgp.install_keys([_entry(tsk)])
    assert {k["fingerprint"]: k["state"] for k in pgp.list_own_keys()} == {
        _fpr(tsk): "active", _fpr(interim): "retired"}


def test_one_call_with_two_addresses_gives_each_its_active_key(tsk):
    other = "anna.bianchi@example.com"
    second = pysequoia.Tsk.generate(user_id=f"<{other}>")
    out = pgp.install_keys([_entry(tsk), _entry(second, addr=other)])
    assert [o["outcome"] for o in out] == ["active", "active"]
    assert pgp.own_fingerprint(ME) == _fpr(tsk)
    assert pgp.own_fingerprint(other) == _fpr(second)


def test_the_same_key_twice_in_one_call(tsk):
    out = pgp.install_keys([_entry(tsk), _entry(tsk)])
    assert [o["outcome"] for o in out] == ["active", "present"]


def test_first_entry_present_then_a_new_key_is_retired(tsk):
    pgp.install_keys([_entry(tsk)])
    second = pysequoia.Tsk.generate(user_id=f"<{ME}>")
    out = pgp.install_keys([_entry(tsk), _entry(second)])
    assert [o["outcome"] for o in out] == ["present", "retired"]
    assert pgp.own_fingerprint(ME) == _fpr(tsk)


# ── writing and reading the backup file ─────────────────────────────

def test_backup_and_restore_across_two_installations(tmp_path):
    """Encrypt in A, back up, restore into an empty B: the mail opens in B."""
    pgp.own_key(ME)
    mail = _mail_signed_and_encrypted_by_me_to_me()
    backup = tmp_path / "backup.asc"
    written = pgp_backup.export_backup(backup, PASSPHRASE)
    assert [w["state"] for w in written] == ["active"]

    db_path(pgp.DB_NAME).unlink()                  # installation B
    assert not pgp.open_message(mail, ME)[1]["decrypted"]
    out = pgp_backup.import_backup(backup, PASSPHRASE)
    assert [o["outcome"] for o in out] == ["active"]
    assert pgp.open_message(mail, ME)[1]["decrypted"]


def test_backup_file_is_a_protected_standard_key(tmp_path):
    key = pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    text = backup.read_text("ascii")
    assert text.startswith("-----BEGIN PGP PRIVATE KEY BLOCK-----")
    loaded = pysequoia.Tsk.from_bytes(backup.read_bytes())
    assert _fpr(loaded) == _fpr(key)
    assert not _opens(loaded, _to(key.extract_certificate()))
    assert _opens(loaded, _to(key.extract_certificate()), PASSPHRASE)


def test_active_and_retired_keys_come_back_the_same(tmp_path, tsk):
    pgp.own_key(ME)
    pgp.install_keys([_entry(tsk)])
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    before = [(k["fingerprint"], k["state"]) for k in pgp.list_own_keys()]
    db_path(pgp.DB_NAME).unlink()
    pgp_backup.import_backup(backup, PASSPHRASE)
    assert [(k["fingerprint"], k["state"]) for k in pgp.list_own_keys()] == before


def test_backup_of_one_address_only(tmp_path):
    pgp.own_key(ME)
    pgp.own_key("anna.bianchi@example.com")
    backup = tmp_path / "backup.asc"
    out = pgp_backup.export_backup(backup, PASSPHRASE, address=ME)
    assert [o["address"] for o in out] == [ME]


def test_export_refusals(tmp_path):
    backup = tmp_path / "backup.asc"
    with pytest.raises(pgp_backup.BackupError):        # nothing to back up
        pgp_backup.export_backup(backup, PASSPHRASE)
    assert pgp.list_own_keys() == []                   # and none was created
    pgp.own_key(ME)
    with pytest.raises(pgp_backup.BackupError):        # short passphrase
        pgp_backup.export_backup(backup, "short")
    backup.write_text("keep me")
    with pytest.raises(pgp_backup.BackupError):        # exists, no force
        pgp_backup.export_backup(backup, PASSPHRASE)
    assert backup.read_text() == "keep me"
    pgp_backup.export_backup(backup, PASSPHRASE, force=True)
    assert list(tmp_path.iterdir()) == [backup]        # no temporary file left


def test_failed_self_check_leaves_no_file(tmp_path, monkeypatch):
    pgp.own_key(ME)
    monkeypatch.setattr(pgp_backup, "protect", lambda data, _p: data)  # not protected
    with pytest.raises(pgp_backup.BackupError):
        pgp_backup.export_backup(tmp_path / "backup.asc", PASSPHRASE)
    assert list(tmp_path.iterdir()) == []


def test_failed_self_check_keeps_the_file_that_was_there(tmp_path, monkeypatch):
    pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    backup.write_text("keep me")
    monkeypatch.setattr(pgp_backup, "protect", lambda data, _p: data)
    with pytest.raises(pgp_backup.BackupError):
        pgp_backup.export_backup(backup, PASSPHRASE, force=True)
    assert list(tmp_path.iterdir()) == [backup]
    assert backup.read_text() == "keep me"


def test_wrong_passphrase_stores_nothing(tmp_path):
    pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    db_path(pgp.DB_NAME).unlink()
    with pytest.raises(pgp_backup.WrongPassphrase):
        pgp_backup.import_backup(backup, "wrong passphrase")
    with pytest.raises(pgp_backup.PassphraseRequired):
        pgp_backup.import_backup(backup)
    assert pgp.list_own_keys() == []


def test_key_with_two_addresses_goes_to_each_configured_one(tmp_path, monkeypatch):
    other = "mario@example.com"
    key = pysequoia.Tsk.generate(user_ids=[f"<{ME}>", f"<{other}>",
                                           "<not.configured@example.com>"])
    monkeypatch.setattr("gigamail.core.accounts.get_accounts",
                        lambda: [{"email": ME}, {"email": other}])
    path = tmp_path / "key.pgp"
    path.write_bytes(bytes(key))
    out = pgp_backup.import_backup(path)
    assert sorted(o["address"] for o in out) == sorted([ME, other])


def test_key_for_an_unknown_address_uses_its_first_user_id(tmp_path, monkeypatch):
    key = pysequoia.Tsk.generate(user_id="<carla.neri@example.com>")
    monkeypatch.setattr("gigamail.core.accounts.get_accounts", lambda: [])
    path = tmp_path / "key.pgp"
    path.write_bytes(bytes(key))
    assert pgp_backup.import_backup(path)[0]["address"] == "carla.neri@example.com"


def test_expired_key_is_kept_for_decryption_only(tmp_path):
    current = pgp.own_key(ME)
    expired = pysequoia.Tsk.generate(user_id=f"<{ME}>", validity_seconds=1)
    time.sleep(2)
    path = tmp_path / "key.pgp"
    path.write_bytes(bytes(expired))
    out = pgp_backup.import_backup(path)
    assert out[0]["outcome"] == "retired" and out[0]["reason"]
    assert pgp.own_fingerprint(ME) == _fpr(current)


@pytest.mark.parametrize("shape", ["binary", "crlf", "text_before_armor"])
def test_file_shapes_users_really_have(tmp_path, tsk, shape):
    armored = pysequoia.armor(pgp_backup.protect(bytes(tsk), PASSPHRASE),
                              pysequoia.ArmorKind.SecretKey)
    armored = armored if isinstance(armored, bytes) else str(armored).encode()
    data = {"binary": pgp_backup.protect(bytes(tsk), PASSPHRASE),
            "crlf": armored.replace(b"\n", b"\r\n"),
            "text_before_armor": b"My key backup\n\n" + armored}[shape]
    path = tmp_path / "key"
    path.write_bytes(data)
    assert pgp_backup.import_backup(path, PASSPHRASE)[0]["outcome"] == "active"


@pytest.mark.parametrize("content", [b"", b"not a key at all", None])
def test_files_that_are_not_a_secret_key(tmp_path, tsk, content):
    path = tmp_path / "key"
    path.write_bytes(bytes(tsk.extract_certificate()) if content is None else content)
    with pytest.raises(pgp_backup.BackupError):        # public key only, empty, junk
        pgp_backup.import_backup(path)
    assert pgp.list_own_keys() == []


def test_one_refused_key_does_not_stop_the_others(tmp_path, tsk):
    v6 = pysequoia.Tsk.generate(user_id=f"<{ME}>", profile=pysequoia.Profile.RFC9580)
    path = tmp_path / "keys.pgp"
    path.write_bytes(bytes(v6) + pgp_backup.protect(bytes(tsk), PASSPHRASE))
    out = pgp_backup.import_backup(path, PASSPHRASE)
    assert sorted(o["outcome"] for o in out) == ["active", "refused"]


def _expired_key():
    key = pysequoia.Tsk.generate(user_id=f"<{ME}>", validity_seconds=1)
    time.sleep(2)
    return key


def _revoked_key():
    key = pysequoia.Tsk.generate(user_id=f"<{ME}>")
    sig = key.extract_certificate().revoke(key.certifier())
    return pysequoia.Tsk.from_bytes(bytes(key) + bytes(sig))


@pytest.mark.parametrize("make", [_expired_key, _revoked_key])
def test_a_store_holding_a_lapsed_key_can_still_be_backed_up(tmp_path, make):
    """Expired and revoked keys are kept retired, so they must survive a
    backup and a restore too."""
    pgp.own_key(ME)
    lapsed = make()
    path = tmp_path / "lapsed.pgp"
    path.write_bytes(bytes(lapsed))
    assert pgp_backup.import_backup(path)[0]["outcome"] == "retired"
    before = [(k["fingerprint"], k["state"]) for k in pgp.list_own_keys()]
    backup = tmp_path / "backup.asc"
    written = pgp_backup.export_backup(backup, PASSPHRASE)
    assert sorted(w["state"] for w in written) == ["active", "retired"]
    db_path(pgp.DB_NAME).unlink()
    pgp_backup.import_backup(backup, PASSPHRASE)
    assert [(k["fingerprint"], k["state"]) for k in pgp.list_own_keys()] == before
    assert _fpr(lapsed) in [k["fingerprint"] for k in pgp.list_own_keys()]



# ---------------------------------------------------------------------------
# Task 5: the `gigamail pgp` commands
# ---------------------------------------------------------------------------

@pytest.fixture()
def allow_consent(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")


class _Asked:
    count = 0


@pytest.fixture()
def answers(monkeypatch):
    """Replace getpass.getpass with a queue of answers; `.count` is the
    number of prompts shown."""
    def install(queue):
        queue = list(queue)
        asked = _Asked()
        asked.count = 0

        def fake(_prompt=""):
            asked.count += 1
            if not queue:
                raise EOFError
            return queue.pop(0)
        monkeypatch.setattr("getpass.getpass", fake)
        return asked
    return install


@pytest.fixture()
def audit_lines():
    def read():
        path = policy._audit_path()
        return path.read_text(encoding="utf-8") if path.exists() else ""
    return read


def _mcp_tool_names():
    import asyncio

    from gigamail.server import mcp
    loop = asyncio.new_event_loop()
    try:
        tools = loop.run_until_complete(mcp.list_tools())
    finally:
        loop.close()
    return [t.name for t in tools]


def _http_route_paths():
    from gigamail.http_api import app
    return [getattr(r, "path", "") for r in app.routes]


def test_backup_without_verification_writes_nothing(tmp_path, capsys):
    pgp.own_key(ME)
    out = tmp_path / "backup.asc"
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 1
    assert not out.exists()


def test_backup_with_verification(tmp_path, allow_consent, answers, capsys):
    key = pgp.own_key(ME)
    answers([PASSPHRASE, PASSPHRASE])
    out = tmp_path / "backup.asc"
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 0
    printed = capsys.readouterr().out
    assert _fpr(key) in printed and str(out) in printed
    assert PASSPHRASE not in printed


def test_backup_with_no_keys_asks_nothing(tmp_path, allow_consent, answers):
    asked = answers([])
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(tmp_path / "b.asc"),
                                        force=False)) == 1
    assert asked.count == 0 and pgp.list_own_keys() == []


@pytest.mark.parametrize("typed", [
    [PASSPHRASE, "something else 99"],      # confirmation does not match
    ["short", "short"],                     # under 12 characters
])
def test_backup_refuses_a_bad_passphrase(tmp_path, allow_consent, answers, typed):
    pgp.own_key(ME)
    answers(typed)
    out = tmp_path / "backup.asc"
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 1
    assert list(tmp_path.iterdir()) == []


def test_backup_cancelled_at_the_prompt(tmp_path, allow_consent, monkeypatch):
    pgp.own_key(ME)

    def interrupt(_prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("getpass.getpass", interrupt)
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(tmp_path / "b.asc"),
                                        force=False)) == 1
    assert list(tmp_path.iterdir()) == []


def test_backup_into_a_missing_folder(tmp_path, allow_consent, answers):
    pgp.own_key(ME)
    answers([PASSPHRASE, PASSPHRASE])
    out = tmp_path / "no-such-folder" / "backup.asc"
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 1


def test_backup_does_not_overwrite_without_force(tmp_path, allow_consent, answers):
    pgp.own_key(ME)
    out = tmp_path / "backup.asc"
    out.write_text("keep me")
    answers([PASSPHRASE, PASSPHRASE])
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 1
    assert out.read_text() == "keep me"


def test_restore_round_trip_through_the_cli(tmp_path, allow_consent, answers, capsys):
    key = pgp.own_key(ME)
    out = tmp_path / "backup.asc"
    answers([PASSPHRASE, PASSPHRASE])
    cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False))
    db_path(pgp.DB_NAME).unlink()
    answers([PASSPHRASE])
    assert cli.cmd_pgp_restore(Namespace(file=str(out))) == 0
    assert pgp.own_fingerprint(ME) == _fpr(key)


def test_restore_without_verification_changes_nothing(tmp_path, tsk):
    path = tmp_path / "key.pgp"
    path.write_bytes(bytes(tsk))
    assert cli.cmd_pgp_restore(Namespace(file=str(path))) == 1
    assert pgp.list_own_keys() == []


def test_restore_wrong_passphrase(tmp_path, allow_consent, answers, tsk):
    path = tmp_path / "key.pgp"
    path.write_bytes(pgp_backup.protect(bytes(tsk), PASSPHRASE))
    answers(["wrong passphrase"])
    assert cli.cmd_pgp_restore(Namespace(file=str(path))) == 1
    assert pgp.list_own_keys() == []


def test_list_shows_state_and_needs_no_verification(tsk, capsys):
    interim = pgp.own_key(ME)
    pgp.install_keys([_entry(tsk)])
    assert cli.cmd_pgp_list(Namespace()) == 0
    printed = capsys.readouterr().out
    assert _fpr(tsk) in printed and _fpr(interim) in printed


def test_list_with_no_keys(capsys):
    assert cli.cmd_pgp_list(Namespace()) == 0
    assert capsys.readouterr().out.strip()


def test_passphrase_never_reaches_logs_or_audit(tmp_path, allow_consent, answers,
                                                caplog, audit_lines):
    pgp.own_key(ME)
    answers([PASSPHRASE, PASSPHRASE])
    with caplog.at_level("DEBUG"):
        cli.cmd_pgp_backup(Namespace(address=None, out=str(tmp_path / "b.asc"),
                                     force=False))
    assert PASSPHRASE not in caplog.text
    assert PASSPHRASE not in audit_lines()
    assert "pgp_backup" in audit_lines()


# Names and source strings that would give the agent a way to a secret key.
# Allow-list: exact names that match on purpose (none today).
_KEY_WORDS = ("key", "pgp")
_EXPORT_WORDS = ("backup", "export", "restore", "import", "secret")
_FORBIDDEN_SOURCE = ("pgp_backup", "own_key_bytes", "export_backup",
                     "import_backup", "install_keys", "_own_keys", "secret_enc")
_ALLOWED_NAMES: set = set()


def _key_exporting_names(names):
    return [n for n in names if n not in _ALLOWED_NAMES
            and any(k in n.lower() for k in _KEY_WORDS)
            and any(w in n.lower() for w in _EXPORT_WORDS)]


def _forbidden_in(source):
    # whole identifiers: zoom.py's "zoom_client_secret_enc" is another name
    return [w for w in _FORBIDDEN_SOURCE
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])",
                         source)]


# The only modules that may touch the key store's secrets: the store itself,
# the backup, and the commands the user types at the PC.
_ALLOWED_MODULES = {"cli.py", "core/pgp.py", "core/pgp_backup.py"}


def _package_sources():
    """(path relative to src/gigamail, source) of every module of the package."""
    from pathlib import Path

    import gigamail
    root = Path(gigamail.__file__).parent
    return [(f.relative_to(root).as_posix(), f.read_text(encoding="utf-8"))
            for f in sorted(root.rglob("*.py"))]


def test_the_agent_has_no_way_to_a_secret_key():
    """No MCP tool, HTTP route or module other than the allowed ones exports
    or imports a key."""
    names = _mcp_tool_names() + _http_route_paths()
    assert names, "the lists must not be empty, or this test proves nothing"
    assert _key_exporting_names(names) == []
    sources = _package_sources()
    found = {path for path, _source in sources}
    assert _ALLOWED_MODULES <= found, "the allow-list names a missing file"
    assert {"server.py", "remote_http.py", "http_api/__init__.py"} <= found
    assert len(found) > 20
    for path, source in sources:
        if path not in _ALLOWED_MODULES:
            assert _forbidden_in(source) == [], path


def test_the_agent_check_is_not_vacuous():
    assert _key_exporting_names(["send_mail", "export_key", "/keys/export",
                                 "backup_keys", "pgp_restore", "/files/export"]) == [
        "export_key", "/keys/export", "backup_keys", "pgp_restore"]
    assert _forbidden_in("x = pgp.own_key_bytes(a)") == ["own_key_bytes"]
    assert _forbidden_in("from .core import pgp_backup") == ["pgp_backup"]
    assert _forbidden_in("def f(): return 1") == []
    assert _forbidden_in('get_setting("zoom_client_secret_enc")') == []
    assert any(_forbidden_in(source) for path, source in _package_sources()
               if path in _ALLOWED_MODULES)


def test_backup_refuses_an_existing_file_before_any_prompt(tmp_path, allow_consent,
                                                           answers, monkeypatch):
    from gigamail import consent
    pgp.own_key(ME)
    out = tmp_path / "backup.asc"
    out.write_text("keep me")
    asked = answers([PASSPHRASE, PASSPHRASE])

    def never(_reason):
        raise AssertionError("verification asked")
    monkeypatch.setattr(consent, "require_human", never)
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 1
    assert asked.count == 0 and out.read_text() == "keep me"


def test_backup_stops_at_a_short_passphrase_after_one_prompt(tmp_path, allow_consent,
                                                             answers):
    pgp.own_key(ME)
    asked = answers(["short", "short"])
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(tmp_path / "b.asc"),
                                        force=False)) == 1
    assert asked.count == 1 and list(tmp_path.iterdir()) == []


def _inflate_one_curve_secret(raw_key, only_tag=None):
    """`raw_key` with the bit count of one ECDH/EdDSA secret raised to 256,
    as GnuPG writes it, or None when no packet of the key is eligible: a
    32-byte value below 0x80 (so the true count is under 256), in a packet
    of `only_tag` when given."""
    out, done = [], False
    for tag, body, raw in pgp_backup.read_packets(raw_key):
        if (tag in (5, 7) and not done and body[5] in (18, 22)
                and only_tag in (None, tag)):
            cut = pgp_backup.public_length(body)
            secret = body[cut + 1:-2]
            if len(secret) == 34 and 0 < secret[2] < 0x80:
                secret = (256).to_bytes(2, "big") + secret[2:]
                body = body[:cut + 1] + secret + (
                    sum(secret) % 65536).to_bytes(2, "big")
                raw = pgp_backup.write_packet(tag, body)
                done = True
        out.append(raw)
    return b"".join(out) if done else None


def _bit_counts(raw_key):
    return [int.from_bytes(b[pgp_backup.public_length(b) + 1:][:2], "big")
            for t, b, _ in pgp_backup.read_packets(raw_key) if t in (5, 7)]


def test_a_secret_with_an_inflated_bit_count_is_normalised():
    # An eligible packet always exists in practice (a Curve25519 scalar is
    # 255 bits); the loop only makes that independent of luck.
    for _ in range(20):
        key = pysequoia.Tsk.generate(user_id=f"<{ME}>")
        inflated = _inflate_one_curve_secret(bytes(key))
        if inflated is not None:
            break
    assert inflated is not None, "no eligible packet in 20 keys"
    assert inflated != bytes(key)
    locked = _protect_with(inflated, PASSPHRASE, 9, 32, 3, 8)
    plain = pgp_backup.unprotect(locked, PASSPHRASE)
    assert _bit_counts(plain) == _bit_counts(bytes(key))
    assert _opens(pysequoia.Tsk.from_bytes(plain), _to(key.extract_certificate()))


def test_normal_mpis_fixes_the_bit_count_of_a_curve_secret():
    value = bytes([0x42]) + bytes(31)
    assert (pgp_backup._normal_mpis(22, (256).to_bytes(2, "big") + value)
            == (255).to_bytes(2, "big") + value)


@pytest.mark.parametrize("algo", [25, 26, 27, 28, 17, 16, 99])
def test_normal_mpis_leaves_other_algorithms_alone(algo):
    """RFC 9580 secrets are raw octet strings, not MPIs: they must come back
    exactly as they went in, even when they look like an MPI."""
    secret = (256).to_bytes(2, "big") + bytes([0x42]) + bytes(31)
    assert pgp_backup._normal_mpis(algo, secret) == secret
    assert pgp_backup._normal_mpis(algo, bytes(32)) == bytes(32)


# A key and an unsigned message made by GnuPG, for a test that needs no gpg.
# The key is a throwaway with no passphrase and an invented address. Made
# with GnuPG 2.4 (OCB preferences left out, so the message is the classic
# MDC-protected kind):
#   gpg --default-preference-list "AES256 AES192 AES SHA512 SHA384 SHA256 ZLIB ZIP Uncompressed" \
#       --passphrase "" --pinentry-mode loopback \
#       --quick-generate-key unsigned.fixture@example.com rsa2048 cert,sign never
#   gpg --passphrase "" --pinentry-mode loopback --quick-add-key <fingerprint> rsa2048 encr never
#   gpg --armor --export-secret-keys unsigned.fixture@example.com
#   printf 'Content-Type: text/plain; charset=utf-8\r\n\r\nUnsigned hello' | \
#       gpg --trust-model always -r unsigned.fixture@example.com -a -e
UNSIGNED_FIXTURE_ADDRESS = "unsigned.fixture@example.com"
# NOT A REAL KEY: A THROWAWAY TEST FIXTURE THAT PROTECTS NOTHING.
UNSIGNED_FIXTURE_KEY = """-----BEGIN PGP PRIVATE KEY BLOCK-----

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
g+E5wHmcM293Y0XVtcUpJ946H/IKBXIXaIOp
=vkVX
-----END PGP PRIVATE KEY BLOCK-----
"""
UNSIGNED_FIXTURE_MESSAGE = """-----BEGIN PGP MESSAGE-----

hQEMA1967iQhQgfPAQgA2WQJuTkHuNrfwmcHz4S3RfJni3zyBBZk1DsTkAzVz0bS
UPLcX+fmkDCQq7OLVubn8Ye7lZWGYrGgHFv/PJUZpdILgMRouyIwa3iZkmThYwTu
J/UYYAwygn6Wg6LFDA4uuRfcTETASpfUuYg6wAzzg/kCTdYw/mxCoV9tGDX8xO9K
668kcDz5XCBlsfSb9Um/0iGvwtMTMNmRieox3mzcuWCtHvHsDicaUWH4Cp8wvdMe
Y1F8VUex1SPuJkVdvnapijieThbf4V7rpYS3lX7wbOMkueYLbf9UuoyQRzBLNmDl
ZmglhRqzmFx0mDPmgbaKr9n5gAqW8IsLB8PeajL1vdJ0ATNJRecKOnrRPxpZuLPN
xsdr+rxtw1flEWxaKDn07QT8aMf8BSOY6+UHzIVn19lXagAvBm+7jbryfnKq9juS
yYP/8h+7g9ftVuuqI7TQBnREkoRpOatyIJHWNdcCWf6L8yC7i3nL4rJ4a2WpKHKe
sWn/mz4=
=IPyc
-----END PGP MESSAGE-----
"""


def test_an_unsigned_mail_made_by_gnupg_opens():
    """Mail from other OpenPGP programs is often encrypted and not signed:
    it opens, with no verified signature. (The library refuses such a
    message once a store of keys is given.)"""
    key = pgp_backup._dearmor(UNSIGNED_FIXTURE_KEY.encode())
    out = pgp.install_keys([{"address": UNSIGNED_FIXTURE_ADDRESS, "key": key,
                             "may_be_active": True}])
    assert [o["outcome"] for o in out] == ["active"]
    outer = MIMEMultipart("encrypted", protocol="application/pgp-encrypted")
    outer["From"], outer["To"] = "anna.bianchi@example.com", UNSIGNED_FIXTURE_ADDRESS
    outer.attach(MIMEApplication(b"Version: 1" + bytes([10]), "pgp-encrypted"))
    outer.attach(MIMEApplication(UNSIGNED_FIXTURE_MESSAGE.encode(), "octet-stream"))
    mail = email.message_from_bytes(outer.as_bytes())
    inner, info = pgp.open_message(mail, UNSIGNED_FIXTURE_ADDRESS)
    assert info["decrypted"], info["error"]
    assert info["signed"] is False
    assert info["signature_valid"] is False
    assert info["signer"] is None
    assert "Unsigned hello" in inner.get_payload()


# ── final review fixes ──────────────────────────────────────────────

def _without_subkey(key_bytes, algo):
    """The key without its subkey of `algo` and that subkey's binding
    signature: 18 drops the encryption subkey, 22 the signing one."""
    out, skipping = [], False
    for tag, body, raw in pgp_backup.read_packets(key_bytes):
        if tag == pgp_backup.TAG_SECRET_SUBKEY:
            skipping = body[5] == algo
        elif tag != 2:
            skipping = False
        if not skipping:
            out.append(raw)
    return b"".join(out)


OTHER = "anna.bianchi@example.com"


def _sign_only_key(addr=OTHER):
    return _without_subkey(bytes(pysequoia.Tsk.generate(user_id=f"<{addr}>")), 18)


def test_a_key_that_cannot_decrypt_is_refused_and_the_others_restored(tmp_path, tsk):
    path = tmp_path / "keys.pgp"
    path.write_bytes(pgp_backup.protect(_sign_only_key(), PASSPHRASE)
                     + pgp_backup.protect(bytes(tsk), PASSPHRASE))
    out = pgp_backup.import_backup(path, PASSPHRASE)
    by_address = {o["address"]: o for o in out}
    assert by_address[OTHER]["outcome"] == "refused"
    assert by_address[OTHER]["reason"]
    assert by_address[ME]["outcome"] == "active"
    assert [k["address"] for k in pgp.list_own_keys()] == [ME]


def test_restore_command_reports_a_key_that_cannot_decrypt(tmp_path, allow_consent,
                                                           answers, capsys, tsk,
                                                           monkeypatch, audit_lines):
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    path = tmp_path / "keys.pgp"
    path.write_bytes(_sign_only_key() + bytes(tsk))
    answers([])
    assert cli.cmd_pgp_restore(Namespace(file=str(path))) == 0
    printed = capsys.readouterr().out
    assert OTHER in printed and "refused" in printed
    assert pgp.own_fingerprint(ME) == _fpr(tsk)
    assert "pgp_restore" in audit_lines()


def test_backup_with_a_key_that_cannot_decrypt_in_the_store(tmp_path):
    pgp.own_key(ME)
    pgp.install_keys([{"address": OTHER, "key": _sign_only_key(),
                       "may_be_active": True}])
    backup = tmp_path / "backup.asc"
    written = pgp_backup.export_backup(backup, PASSPHRASE)
    assert sorted(w["address"] for w in written) == sorted([ME, OTHER])
    assert backup.exists()


def test_an_unexpected_error_in_the_self_check_is_a_failed_check(tmp_path,
                                                                 monkeypatch):
    pgp.own_key(ME)

    def boom(_plain):
        raise RuntimeError("library failure")
    monkeypatch.setattr(pgp_backup, "_secret_material", boom)
    with pytest.raises(pgp_backup.BackupError):
        pgp_backup.export_backup(tmp_path / "backup.asc", PASSPHRASE)
    assert list(tmp_path.iterdir()) == []


def test_a_user_id_without_an_address_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("gigamail.core.accounts.get_accounts", lambda: [])
    path = tmp_path / "key.pgp"
    path.write_bytes(bytes(pysequoia.Tsk.generate(user_id="No Address")))
    out = pgp_backup.import_backup(path)
    assert [o["outcome"] for o in out] == ["refused"]
    assert pgp.list_own_keys() == []


def _inflated_key(tag):
    for _ in range(40):
        key = pysequoia.Tsk.generate(user_id=f"<{ME}>")
        inflated = _inflate_one_curve_secret(bytes(key), tag)
        if inflated is not None:
            return key, inflated
    raise AssertionError("no eligible packet in 40 keys")


@pytest.mark.parametrize("tag", [pgp_backup.TAG_SECRET_KEY,
                                 pgp_backup.TAG_SECRET_SUBKEY])
def test_an_unprotected_secret_with_an_inflated_bit_count_is_restored(tmp_path, tag):
    """GnuPG's bit count on an unprotected Ed25519/Curve25519 secret. The
    library refuses to read the file at all when it is on the primary key."""
    key, inflated = _inflated_key(tag)
    assert _bit_counts(pgp_backup.unprotect(inflated, None)) == _bit_counts(bytes(key))
    path = tmp_path / "key.pgp"
    path.write_bytes(inflated)
    assert [o["outcome"] for o in pgp_backup.import_backup(path)] == ["active"]
    assert pgp.own_fingerprint(ME) == _fpr(key)


def _protect_primary_with(passphrase):
    """A `protect` that locks the primary key with another passphrase and
    the subkeys with the right one."""
    real = pgp_backup._protect_body

    def fake(tsk_bytes, right):
        out = []
        for tag, body, raw in pgp_backup.read_packets(tsk_bytes):
            if tag in (5, 7):
                phrase = passphrase if tag == pgp_backup.TAG_SECRET_KEY else right
                raw = pgp_backup.write_packet(tag, real(body, phrase.encode("utf-8")))
            out.append(raw)
        return b"".join(out)
    return fake


def test_self_check_opens_every_packet_with_the_passphrase(tmp_path, monkeypatch):
    """The library probe only uses the encryption subkey: a primary key
    locked with another passphrase must fail the check too."""
    pgp.own_key(ME)
    monkeypatch.setattr(pgp_backup, "protect", _protect_primary_with("another one 77"))
    with pytest.raises(pgp_backup.BackupError):
        pgp_backup.export_backup(tmp_path / "backup.asc", PASSPHRASE)
    assert list(tmp_path.iterdir()) == []


def test_check_protection_wants_every_secret_packet_locked(tsk):
    """An unprotected primary key next to subkeys locked with the right
    passphrase: opening it still asks for a passphrase, so only a look at
    each packet tells that one of them is in the clear."""
    half = b"".join(
        pgp_backup.write_packet(tag, pgp_backup._protect_body(
            body, PASSPHRASE.encode("utf-8")))
        if tag == pgp_backup.TAG_SECRET_SUBKEY else raw
        for tag, body, raw in pgp_backup.read_packets(bytes(tsk)))
    assert pgp_backup.unprotect(half, PASSPHRASE) == bytes(tsk)
    with pytest.raises(pgp_backup.BackupError, match="not protected"):
        pgp_backup._check_protection(half, bytes(tsk), PASSPHRASE)
    whole = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    pgp_backup._check_protection(whole, bytes(tsk), PASSPHRASE)   # no error


def test_armor_the_library_refuses_is_not_read_another_way(tmp_path, tsk):
    """The second reading of a file exists for one case, a bit count to set
    right. A file the library refuses for any other reason stays refused."""
    armored = pysequoia.armor(bytes(tsk), pysequoia.ArmorKind.SecretKey)
    armored = armored if isinstance(armored, bytes) else str(armored).encode()
    lines = armored.split(b"\n")
    body = next(i for i, line in enumerate(lines) if len(line) == 64)
    lines[body] = lines[body][:20] + b"!!~~" + lines[body][20:]
    spoiled = b"\n".join(lines)
    try:
        pysequoia.Tsk.split_bytes(spoiled)
        refused = False
    except Exception:
        refused = True
    assert refused, "the library reads this file: the test proves nothing"
    path = tmp_path / "key.asc"
    path.write_bytes(spoiled)
    with pytest.raises(pgp_backup.BackupError):
        pgp_backup.import_backup(path)
    assert pgp.list_own_keys() == []


def test_self_check_fails_when_the_armor_is_not_read(tmp_path, monkeypatch):
    pgp.own_key(ME)
    monkeypatch.setattr(pgp_backup, "_dearmor", lambda data: data)
    with pytest.raises(pgp_backup.BackupError):
        pgp_backup.export_backup(tmp_path / "backup.asc", PASSPHRASE)
    assert list(tmp_path.iterdir()) == []


def test_backup_of_a_key_stored_with_old_format_headers(tmp_path, tsk):
    """GnuPG writes old-format headers and a restored key is stored as it
    came; backing it up must not fail the check."""
    old = b"".join(_old_format(tag, body, 2)
                   for tag, body, _raw in pgp_backup.read_packets(bytes(tsk)))
    pgp.install_keys([{"address": ME, "key": old, "may_be_active": True}])
    written = pgp_backup.export_backup(tmp_path / "backup.asc", PASSPHRASE)
    assert [w["fingerprint"] for w in written] == [_fpr(tsk)]


def test_a_failed_cleanup_does_not_hide_the_failed_check(tmp_path, monkeypatch):
    pgp.own_key(ME)
    monkeypatch.setattr(pgp_backup, "protect", lambda data, _p: data)

    def stuck(self, missing_ok=False):
        raise PermissionError(13, "in use")
    monkeypatch.setattr(pgp_backup.Path, "unlink", stuck)
    with pytest.raises(pgp_backup.BackupError) as raised:
        pgp_backup.export_backup(tmp_path / "backup.asc", PASSPHRASE)
    assert "failed its check" in str(raised.value)


def test_a_key_without_a_signing_subkey_is_retired(tmp_path):
    current = pgp.own_key(ME)
    key = pysequoia.Tsk.generate(user_id=f"<{ME}>")
    path = tmp_path / "key.pgp"
    path.write_bytes(_without_subkey(bytes(key), 22))
    out = pgp_backup.import_backup(path)
    assert out[0]["outcome"] == "retired" and out[0]["reason"]
    assert pgp.own_fingerprint(ME) == _fpr(current)


def _no_consent(monkeypatch):
    from gigamail import consent

    def unavailable(_reason):
        raise consent.ConsentUnavailable("no backend")
    monkeypatch.setattr(consent, "require_human", unavailable)


def test_backup_without_a_consent_backend_returns_2(tmp_path, monkeypatch, answers):
    pgp.own_key(ME)
    _no_consent(monkeypatch)
    asked = answers([PASSPHRASE, PASSPHRASE])
    out = tmp_path / "backup.asc"
    assert cli.cmd_pgp_backup(Namespace(address=None, out=str(out), force=False)) == 2
    assert asked.count == 0 and not out.exists()


@pytest.mark.parametrize("lang,words", [
    ("en", ["passphrase-protected file", "only the keys of this address",
            "overwrite the file"]),
    ("it", ["protetto da passphrase", "solo le chiavi di questo indirizzo",
            "sovrascrive il file"]),
])
def test_pgp_help_follows_the_user_language(monkeypatch, capsys, lang, words):
    monkeypatch.setenv("GIGAMAIL_LANG", lang)
    with pytest.raises(SystemExit):
        cli.main(["pgp", "backup", "--help"])
    printed = " ".join(capsys.readouterr().out.split())
    with pytest.raises(SystemExit):
        cli.main(["pgp", "--help"])
    printed += " " + " ".join(capsys.readouterr().out.split())
    for word in words:
        assert word in printed


def test_restore_without_a_consent_backend_returns_2(tmp_path, monkeypatch, tsk):
    _no_consent(monkeypatch)
    path = tmp_path / "key.pgp"
    path.write_bytes(bytes(tsk))
    assert cli.cmd_pgp_restore(Namespace(file=str(path))) == 2
    assert pgp.list_own_keys() == []
