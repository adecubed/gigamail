# OpenPGP Key Backup and Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gigamail pgp backup` writes the user's OpenPGP secret keys to a standard passphrase-protected file that GigaMail, GnuPG and Thunderbird import; `gigamail pgp restore` brings such a file back.

**Architecture:** A new module `core/pgp_backup.py` holds the OpenPGP packet handling (protect and unprotect secret-key packets, RFC 4880 section 5.5.3) and the export/import of a backup file with its self-check. `core/pgp.py` gains retired keys and the store operations that decide which key is active. `cli.py` gains a `pgp` command group behind `consent.require_human`. Nothing is exposed to the agent.

**Tech Stack:** Python 3.10+, `pysequoia` (reads keys, never writes protected ones), `cryptography` (AES-CFB, already a dependency), `hashlib`, SQLite, pytest, GnuPG 2.4 in tests only.

**Spec:** `specs/2026-11-25-pgp-key-backup-design.md` — read it first; this plan argues from it.

## Global Constraints

- Everything written into the repository is English; user-facing text is built in Italian and English and picked with `policy.user_lang()` (`cli._tr(it, en)`, `pgp.say(it, en)`).
- Invented data only: addresses on `example.com` (`mario.rossi@example.com`, `anna.bianchi@example.com`). No real names, addresses, key ids.
- No new dependency. `cryptography>=42` is the floor: import `CFB` from `cryptography.hazmat.decrepit.ciphers.modes` and fall back to `cryptography.hazmat.primitives.ciphers.modes` on `ImportError`.
- CI runs Python 3.10, 3.12 and 3.13 on Ubuntu and Windows: no `tomllib`, no 3.11-only syntax, no POSIX-only calls without a guard.
- The key store is opened only through `pgp._db()` (closes the file after every use).
- No passphrase or key material in logs, audit, error messages, or command-line arguments.
- No MCP tool, HTTP route or `remote_http` path may export or import a key.
- Run after every task: `.venv\Scripts\python.exe -m pytest -q tests/test_pgp.py tests/test_pgp_backup.py` and `.venv\Scripts\python.exe -m ruff check src tests extras`.
- **Do not commit or push.** The maintainer commits. Where a plan would say "commit", stop and leave the work in the tree; the last task hands over a commit summary and description.
- Backup format, exact values: S2K usage octet 254; cipher AES-256 (algorithm 9), CFB, random 16-byte IV per packet; S2K type 3 (iterated and salted), hash SHA-256 (algorithm 8), random 8-byte salt per packet, count octet `0xEE`; packets other than Secret-Key (tag 5) and Secret-Subkey (tag 7) copied byte for byte.
- Minimum passphrase length: 12 characters. Passphrases are encoded as UTF-8.

## Review Focus

Inputs the spec implies but does not list as tests. Each has a test in the task named.

1. **Old-format packet headers and long packets.** GnuPG exports use old-format headers, and an RSA-4096 key needs two- and five-octet lengths; restore must parse both. (Task 2)
2. **A passphrase with non-ASCII characters.** `"chiave-è-più-lunga"` must protect and unprotect identically in GigaMail, `pysequoia` and GnuPG (UTF-8). (Tasks 1 and 6)
3. **No keys yet.** A user who never sent encrypted mail runs `backup`: a clear message, no file, exit code 1, and no key generated as a side effect. (Task 5)
4. **The file as users really have it.** A binary (unarmored) key, an armored one with CRLF line endings, and one with text before the armor header all restore; an empty file and a file that is not a key are refused without a traceback. (Task 4)
5. **A prompt that cannot be answered.** Passphrase confirmation that does not match, Ctrl-C at the prompt, an output folder that does not exist or cannot be written: nothing is written, no temporary file is left, exit code 1. (Task 5)

---

## File Structure

- Create `src/gigamail/core/pgp_backup.py` — packet reader/writer, `protect`, `unprotect`, `export_backup`, `import_backup`, self-check. Depends on `pgp.py`, not the other way round.
- Modify `src/gigamail/core/pgp.py` — `retired_keys` table, `_own_keys()` including retired keys, `list_own_keys`, `own_key_bytes`, `install_keys`.
- Modify `src/gigamail/cli.py` — `cmd_pgp_list`, `cmd_pgp_backup`, `cmd_pgp_restore`, and the `pgp` parser group next to the `zoom` group.
- Create `tests/test_pgp_backup.py` — everything that needs only `pysequoia`.
- Create `tests/test_pgp_backup_gnupg.py` — everything that runs `gpg`.
- Modify `.github/workflows/ci.yml` — GnuPG on the Ubuntu test job.
- Modify `SECURITY.md`, `README.md`, `CHANGELOG.md`.

---

### Task 1: Protect a secret key with a passphrase

**Files:**
- Create: `src/gigamail/core/pgp_backup.py`
- Test: `tests/test_pgp_backup.py`

**Interfaces:**
- Consumes: `pgp.PgpError(it, en)`.
- Produces:
  - `class BackupError(pgp.PgpError)`
  - `class UnsupportedKey(BackupError)` — a key or protection this code refuses.
  - `read_packets(data: bytes) -> Iterator[Tuple[int, bytes, bytes]]` — `(tag, body, raw)` for binary OpenPGP data, new- and old-format headers; raises `UnsupportedKey` on partial or indeterminate lengths.
  - `write_packet(tag: int, body: bytes) -> bytes` — new-format header.
  - `public_length(body: bytes) -> int` — length of the public part of a version 4 secret-key packet body, for algorithms 1, 2, 3, 18, 19, 22; `UnsupportedKey` otherwise (version 6, algorithms 25–28).
  - `s2k_key(passphrase: bytes, s2k_type: int, hash_algo: int, salt: bytes, count_octet: int, key_len: int) -> bytes`
  - `protect(tsk_bytes: bytes, passphrase: str) -> bytes` — binary in, binary out; raises `UnsupportedKey` if a secret packet is already protected.
  - `MIN_PASSPHRASE = 12`

- [ ] **Step 1: Write the failing tests**

```python
pysequoia = pytest.importorskip("pysequoia")
from gigamail.core import pgp_backup  # noqa: E402

ME = "mario.rossi@example.com"
PASSPHRASE = "correct horse 42"


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
    for (tag, _b, raw_before), (_t, _b2, raw_after) in zip(before, after):
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
```

- [ ] **Step 2: Run them, expect failure**

Run: `.venv\Scripts\python.exe -m pytest -q tests/test_pgp_backup.py`
Expected: collection error, `cannot import name 'pgp_backup'`.

- [ ] **Step 3: Implement the Task 1 interfaces in `pgp_backup.py`**

The algorithm, which the tests do not fully determine:

- Secret packet body = `public part` + `usage octet` + rest. Unprotected: usage 0, then the secret MPIs, then a two-octet checksum (sum of the MPI octets mod 65536). Verify that checksum before protecting.
- Protected body = `public part` + `bytes([254, 9, 3, 8])` + `salt(8)` + `bytes([0xEE])` + `iv(16)` + `AES-256-CFB(key, iv, secret MPIs + SHA-1(secret MPIs))`. Standard full-block CFB, not OpenPGP's resynchronising variant.
- S2K type 3: `count = (16 + (c & 15)) << ((c >> 4) + 6)`; hash `salt + passphrase` repeated until `max(count, len(salt + passphrase))` octets are consumed. Type 1 hashes `salt + passphrase` once, type 0 the passphrase alone. When the digest is shorter than `key_len`, concatenate further contexts, the n-th preloaded with n zero octets (RFC 4880 section 3.7.1.1).
- Public part: version octet 4, four octets of creation time, algorithm octet, then RSA `n, e` (two MPIs); EdDSA 22 and ECDSA 19 `OID (length-prefixed), MPI`; ECDH 18 `OID, MPI, KDF parameters (length-prefixed)`.

- [ ] **Step 4: Run the tests and ruff**

Expected: all Task 1 tests pass; `ruff check` clean.

---

### Task 2: Remove the passphrase (keys from GigaMail, GnuPG, Thunderbird)

**Files:**
- Modify: `src/gigamail/core/pgp_backup.py`
- Test: `tests/test_pgp_backup.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `class WrongPassphrase(BackupError)`
  - `class PassphraseRequired(BackupError)`
  - `is_protected(key_bytes: bytes) -> bool` — any secret packet with usage other than 0.
  - `unprotect(key_bytes: bytes, passphrase: Optional[str]) -> bytes` — binary in, binary out. Unprotected input is returned unchanged. Raises `PassphraseRequired` when protected and `passphrase` is `None`, `WrongPassphrase` when the SHA-1 check fails, `UnsupportedKey` for: usage 255 or a cipher octet used directly as usage, usage 253 (AEAD), S2K type 4 (Argon2), S2K types 100–110 (GnuPG 101 stubs), ciphers other than AES-128/192/256 (7, 8, 9), hashes other than SHA-1/SHA-256/SHA-512 (2, 8, 10).

- [ ] **Step 1: Write the failing tests**

```python
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
])
def test_unprotect_refuses_what_it_does_not_know(tsk, tail):
    with pytest.raises(pgp_backup.UnsupportedKey):
        pgp_backup.unprotect(_with_secret_tail(bytes(tsk), tail), PASSPHRASE)


def test_old_format_headers_and_long_lengths(tsk):
    """GnuPG writes old-format headers; a big key needs 2- and 5-octet
    lengths. Re-encode a protected key that way and read it back."""
    locked = pgp_backup.protect(bytes(tsk), PASSPHRASE)
    old = b"".join(_old_format(tag, body, length_octets=n)
                   for (tag, body, _), n in zip(pgp_backup.read_packets(locked),
                                                [2, 1, 4, 2, 2, 2, 2, 2, 2]))
    assert pgp_backup.unprotect(old, PASSPHRASE) == bytes(tsk)
```

Test helpers to write in the test file (not in the product): `_protect_with(...)` builds a protected key with the given parameters from `pgp_backup.s2k_key`, `read_packets`, `write_packet` and `public_length`; `_with_secret_tail(tsk_bytes, tail)` replaces what follows the public part of the first secret packet with `tail + 64 random octets`; `_old_format(tag, body, length_octets)` writes an old-format header (`0x80 | tag << 2 | length-type`). Only tags below 16 exist in a key, so old format always applies; `zip` stops at the shorter list.

`test_unprotect_reads_other_clients_parameters`: if `pysequoia` rejects a combination as policy (it may refuse S2K type 0), keep the round-trip assertion and guard the independent-reader line for that combination with a comment naming it.

- [ ] **Step 2: Run them, expect failure** (`AttributeError: unprotect`).

- [ ] **Step 3: Implement `is_protected` and `unprotect`**

Unprotected body is rebuilt as `public part + 0x00 + secret MPIs + checksum`, so that a GigaMail key round-trips byte for byte. IV length is the cipher's block size (16 for all three AES sizes). Compare the SHA-1 with `hmac.compare_digest`.

- [ ] **Step 4: Run the tests and ruff.** Expected: pass, clean.

---

### Task 3: Retired keys in the store

**Files:**
- Modify: `src/gigamail/core/pgp.py` (`_create_tables` at line 111, `_own_keys` at line 157, new functions after `own_fingerprint`)
- Test: `tests/test_pgp_backup.py`

**Interfaces:**
- Produces, in `pgp.py`:
  - table `retired_keys(address TEXT NOT NULL, fingerprint TEXT NOT NULL, secret_enc TEXT NOT NULL, created_at REAL NOT NULL, retired_at REAL NOT NULL, PRIMARY KEY (address, fingerprint))`, created in `_create_tables`.
  - `_own_keys() -> List[Tuple[str, Tsk]]` — active keys first, then retired ones.
  - `list_own_keys() -> List[Dict]` — `{"address", "fingerprint", "created_at", "state"}` with `state` `"active"` or `"retired"`, ordered by address, active first, then by `created_at`. Never generates a key; an absent store gives `[]`.
  - `own_key_bytes(address: Optional[str] = None) -> List[Tuple[str, str, bytes]]` — `(address, state, unprotected key bytes)` in the same order.
  - `install_keys(entries: List[Dict]) -> List[Dict]` — each entry `{"address": str, "key": bytes (unprotected), "may_be_active": bool}`, in file order. One transaction. Returns one `{"address", "fingerprint", "outcome"}` per entry, `outcome` one of `"active"`, `"retired"`, `"present"`.

Rules for `install_keys`, per address (spec, "Which key becomes active on restore"):
- an entry whose `(address, fingerprint)` is already in `own_keys` or `retired_keys` → `"present"`, nothing changes;
- otherwise, the first entry in the list for that address, if `may_be_active`, becomes the active key; the row it displaces in `own_keys` moves to `retired_keys` with `retired_at = now` → `"active"`;
- every other new entry goes to `retired_keys` → `"retired"`.

- [ ] **Step 1: Write the failing tests**

```python
from gigamail.core import pgp  # noqa: E402
from gigamail.core.data_paths import db_path  # noqa: E402


@pytest.fixture(autouse=True)
def _empty_store():
    path = db_path(pgp.DB_NAME)
    if path.exists():
        path.unlink()
    yield


def _fpr(key):
    return key.extract_certificate().fingerprint


def _entry(key, addr=ME, may_be_active=True):
    return {"address": addr, "key": bytes(key), "may_be_active": may_be_active}


def test_list_own_keys_never_creates_one():
    assert pgp.list_own_keys() == []
    assert pgp.own_key(ME, create=False) is None


def test_install_into_an_empty_store(tsk):
    out = pgp.install_keys([_entry(tsk)])
    assert [o["outcome"] for o in out] == ["active"]
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
    interim = pgp.own_key(ME)
    pgp.install_keys([_entry(tsk)])
    assert [(a, s) for a, s, _ in pgp.own_key_bytes()] == [(ME, "active"),
                                                          (ME, "retired")]
    assert pgp.own_key_bytes()[0][2] == bytes(tsk)
    assert pgp.own_key_bytes("anna.bianchi@example.com") == []


def test_mail_signed_by_a_retired_key_still_shows_signed_by(tsk):
    interim = pgp.own_key(ME)
    mail = _mail_signed_and_encrypted_by_me_to_me()   # via pgp.encrypt_message
    pgp.install_keys([_entry(tsk)])
    _opened, info = pgp.open_message(mail, ME)
    assert info["signature_valid"] and info["signer"] == ME
```

Helpers in the test file: `_encrypted_mail_to(cert)` builds a `multipart/encrypted` mail as `tests/test_pgp.py` does; `_keydata_fingerprint(header)` parses the `keydata` of an Autocrypt header value with `pysequoia.Cert.from_bytes`; `_mail_signed_and_encrypted_by_me_to_me()` calls `pgp.encrypt_message(msg, ME, [ME])` and re-parses the bytes.

- [ ] **Step 2: Run them, expect failure** (`AttributeError: install_keys`).

- [ ] **Step 3: Implement.** `_address_of` (line 478) receives `keys` from `_own_keys()`, so the "signed by" test passes once retired keys are in that list; check it rather than changing `_address_of`.

- [ ] **Step 4: Run `tests/test_pgp.py tests/test_pgp_backup.py` and ruff.** Expected: pass (the 35 existing PGP tests included), clean.

---

### Task 4: Write and read a backup file

**Files:**
- Modify: `src/gigamail/core/pgp_backup.py`
- Test: `tests/test_pgp_backup.py`

**Interfaces:**
- Consumes: Tasks 1–3; `accounts.get_accounts() -> List[Dict]` (each has `"email"`).
- Produces:
  - `export_backup(path: Path, passphrase: str, address: Optional[str] = None, force: bool = False) -> List[Dict]` — returns `{"address", "fingerprint", "state"}` per key written. Raises `BackupError` when: there is no key to write; `path` exists and not `force`; the passphrase is shorter than `MIN_PASSPHRASE`; the self-check fails.
  - `import_backup(path: Path, passphrase: Optional[str] = None) -> List[Dict]` — returns `{"address", "fingerprint", "outcome", "reason"}` per key and address, `outcome` one of `"active"`, `"retired"`, `"present"`, `"refused"`. Raises `PassphraseRequired`, `WrongPassphrase` (nothing stored in either case), `BackupError` for a file with no secret key in it.

Behaviour the tests pin:
- The file is one ASCII-armored `PGP PRIVATE KEY BLOCK` (`pysequoia.armor(data, pysequoia.ArmorKind.SecretKey)`), keys in the order of `pgp.own_key_bytes(address)`.
- Write to a temporary file in the same folder (owner-only `0o600` via `os.open` on POSIX), run the self-check on it, then `os.replace` into place. On any failure delete the temporary file and leave an existing `path` untouched.
- Self-check, per key, on the bytes read back: fingerprint equals the store's; a test message encrypted to the certificate decrypts with the passphrase and does not without it; the unprotected secret MPIs do not occur in the file's decoded bytes.
- Reading: accept armored or binary input; split into keys with `pysequoia.Tsk.split_bytes`. For each key: `unprotect`; addresses = every address in `cert.user_ids` that is a configured account, or, when none is, the address of the first user ID; no address at all → `"refused"`. Must decrypt a test message to its own certificate, else `"refused"`. `may_be_active` = it signs a test message, is not revoked (`cert.is_revoked`) and is not expired (`cert.expiration`). A key `unprotect` refuses with `UnsupportedKey` is `"refused"` with the reason; the other keys in the file are still processed. All accepted entries go to `pgp.install_keys` in one call.

- [ ] **Step 1: Write the failing tests**

```python
def test_backup_and_restore_across_two_installations(tmp_path, monkeypatch):
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
    interim = pgp.own_key(ME)
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
```

If `pysequoia.Tsk.split_bytes` does not accept the "text before armor" shape or a stream that mixes a version 6 and a version 4 key, find the armor block or split at tag-5 packets with `read_packets` first; the tests stay as written.

- [ ] **Step 2: Run them, expect failure** (`AttributeError: export_backup`).
- [ ] **Step 3: Implement `export_backup`, `import_backup` and the self-check.**
- [ ] **Step 4: Run both PGP test files and ruff.** Expected: pass, clean.

---

### Task 5: The `gigamail pgp` commands

**Files:**
- Modify: `src/gigamail/cli.py` (commands near `cmd_extensions_enable`, line 1495; parser group after the `zoom` group, line 1896)
- Test: `tests/test_pgp_backup.py`

**Interfaces:**
- Consumes: `pgp.list_own_keys`, `pgp_backup.export_backup`, `pgp_backup.import_backup`, `consent.require_human(reason) -> bool` (raises `consent.ConsentUnavailable`), `policy.audit(tool, args, outcome, detail="")`, `cli._tr(it, en)`.
- Produces: `cmd_pgp_list(args) -> int`, `cmd_pgp_backup(args) -> int` (`args.address`, `args.out`, `args.force`), `cmd_pgp_restore(args) -> int` (`args.file`).

Decisions:
- `gigamail pgp list` — one line per key: address, fingerprint, creation date (`YYYY-MM-DD`), state. No verification. No keys → a line saying so, exit 0.
- `gigamail pgp backup [--address A] [--out FILE] [--force]` — order: refuse early when there is no key (exit 1, before any prompt); `require_human(_tr("GigaMail: copia di sicurezza della chiave di cifratura", "GigaMail: back up the encryption key"))`; passphrase twice with `getpass.getpass`; `export_backup`. Default `--out`: `gigamail-key-backup-YYYY-MM-DD.asc` in the current folder. Prints the absolute path, the fingerprints, and that the passphrase cannot be recovered.
- `gigamail pgp restore FILE` — `require_human(...)` first; `import_backup(path)`; on `PassphraseRequired` ask once with `getpass` and call again; prints one line per key with its outcome and reason.
- Exit codes: 0 done; 1 refused, failed, cancelled (`KeyboardInterrupt` and `EOFError` at a prompt included), verification not passed; 2 `ConsentUnavailable`.
- Audit: `policy.audit("pgp_backup", {"file": <file name only>, "fingerprints": [...]}, "ok")` and `policy.audit("pgp_restore", {...}, "ok")`; failures with outcome `"error"` and the reason. Never the passphrase.

- [ ] **Step 1: Write the failing tests**

Tests drive `cli.cmd_pgp_*` with `argparse.Namespace`, patch `getpass.getpass` with a list of answers, and switch verification with the environment the suite already uses: the default is `GIGAMAIL_CONSENT_BACKEND=deny`; to allow, `monkeypatch.setenv("GIGAMAIL_CONSENT_BACKEND", "allow")` and `monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")`.

```python
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


def test_the_agent_has_no_way_to_a_secret_key():
    """No MCP tool and no HTTP route exports or imports a key."""
    names = _mcp_tool_names() + _http_route_paths()
    assert names, "the lists must not be empty, or this test proves nothing"
    assert not [n for n in names if "pgp" in n.lower() and
                any(w in n.lower() for w in ("backup", "export", "restore",
                                             "import", "secret"))]
    for module in ("gigamail.server", "gigamail.remote_http", "gigamail.http_api"):
        assert "pgp_backup" not in _source_of(module)
```

Fixtures and helpers in the test file: `allow_consent` (the two `setenv` above); `answers(list)` patches `getpass.getpass` to pop from the list and returns an object whose `.count` is the number of calls; `audit_lines()` returns the text of the audit log (find where `policy.audit` writes and read that file); `_mcp_tool_names()` the way `tests/test_toolmap.py` and `gigamail.gen_toolmap` enumerate tools; `_http_route_paths()` from the FastAPI app's `routes`; `_source_of(module)` concatenates the source files of a module or package.

- [ ] **Step 2: Run them, expect failure** (`AttributeError: cmd_pgp_backup`).
- [ ] **Step 3: Implement the three commands and the parser group.**
- [ ] **Step 4: Run** `.venv\Scripts\python.exe -m gigamail.cli pgp list` (or the `gigamail` entry point) in the test environment and both PGP test files, plus ruff. Expected: the command prints the "no keys" line; tests pass; clean.

---

### Task 6: GnuPG interoperability, in CI

**Files:**
- Create: `tests/test_pgp_backup_gnupg.py`
- Modify: `.github/workflows/ci.yml` (the test job, around lines 37–49)

**Interfaces:**
- Consumes: `pgp_backup.export_backup`, `pgp_backup.import_backup`, `pgp.encrypt_message`, `pgp.open_message`.
- Produces: environment variable `GIGAMAIL_REQUIRE_GNUPG=1` — when set, a missing or unusable `gpg` fails these tests instead of skipping them.

Decisions:
- A `gnupg` fixture: `shutil.which("gpg")`; a fresh home directory with a short path (the agent's socket path has a length limit: use `tempfile.mkdtemp(prefix="gm")` under the system temp folder, not pytest's long `tmp_path`); `GNUPGHOME` set per call through `env=`; `gpgconf --kill all` and removal of the folder at teardown. A helper `gpg(*args, input=None) -> CompletedProcess` always adds `--batch --no-tty`.
- Skip reason when absent: `"GnuPG not installed"`; when `GIGAMAIL_REQUIRE_GNUPG=1`, `pytest.fail` with the same text.
- Passphrases reach `gpg` with `--pinentry-mode loopback --passphrase-fd 0`, never on the command line. Between a right-passphrase and a wrong-passphrase attempt run `gpgconf --kill gpg-agent`, or the agent's cache answers for the wrong one.

- [ ] **Step 1: Write the tests**

```python
def test_gnupg_imports_the_backup_and_needs_the_passphrase(gnupg, tmp_path):
    key = pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    assert gnupg.gpg("--import", str(backup)).returncode == 0
    assert _fpr(key).upper() in gnupg.gpg("--list-secret-keys", "--with-colons").stdout.upper()

    cipher = gnupg.gpg("--trust-model", "always", "-r", ME, "-a", "-e",
                       input=b"hello").stdout
    assert gnupg.decrypt(cipher, PASSPHRASE).stdout == b"hello"
    gnupg.forget_passphrases()
    assert gnupg.decrypt(cipher, "wrong passphrase").returncode != 0


def test_gnupg_signs_with_the_backup(gnupg, tmp_path):
    pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    gnupg.gpg("--import", str(backup))
    assert b"BEGIN PGP SIGNED MESSAGE" in gnupg.clearsign(b"hello", ME, PASSPHRASE).stdout


def test_gnupg_non_ascii_passphrase(gnupg, tmp_path):
    phrase = "chiave-è-più-lunga"
    pgp.own_key(ME)
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, phrase)
    gnupg.gpg("--import", str(backup))
    cipher = gnupg.gpg("--trust-model", "always", "-r", ME, "-a", "-e",
                       input=b"hello").stdout
    assert gnupg.decrypt(cipher, phrase).stdout == b"hello"


@pytest.mark.parametrize("algo", ["ed25519", "rsa3072"])
def test_a_key_exported_by_gnupg_is_restored(gnupg, tmp_path, algo):
    """Generated and exported by GnuPG with a passphrase; GigaMail restores
    it and opens a mail GnuPG encrypted to it."""
    gnupg.generate(ME, algo, PASSPHRASE)
    exported = tmp_path / "from-gnupg.asc"
    exported.write_bytes(gnupg.export_secret(ME, PASSPHRASE))
    out = pgp_backup.import_backup(exported, PASSPHRASE)
    assert [o["outcome"] for o in out] == ["active"]
    mail = _pgp_mime(gnupg.gpg("--trust-model", "always", "-r", ME, "-a", "-e",
                               input=_inner_mime("hello")).stdout)
    assert pgp.open_message(mail, ME)[1]["decrypted"]


def test_mail_between_two_gigamail_keys_is_not_readable_by_gnupg_2_4(gnupg, tmp_path):
    """Documents a declared limit (SECURITY.md): with only GigaMail keys as
    recipients the library uses the newest packet format. If this test
    starts failing because GnuPG reads the mail, the limit is gone: update
    SECURITY.md and turn the assertion around."""
    pgp.own_key(ME)
    peer = pysequoia.Tsk.generate(user_id="<anna.bianchi@example.com>")
    pgp.import_peer_key("anna.bianchi@example.com", bytes(peer.extract_certificate()))
    mail = pgp.encrypt_message(_clear_mail(), ME, ["anna.bianchi@example.com"])
    backup = tmp_path / "backup.asc"
    pgp_backup.export_backup(backup, PASSPHRASE)
    gnupg.gpg("--import", str(backup))
    result = gnupg.decrypt(pgp._ciphertext(mail), PASSPHRASE)
    if gnupg.version >= (2, 5):
        pytest.skip("measured on GnuPG 2.4 only")
    assert result.returncode != 0
    assert pgp.open_message(mail, ME)[1]["decrypted"]      # GigaMail reads it
```

`rsa3072` is the Review Focus case for long packets and old-format headers on a real export. If this GnuPG cannot generate one of the algorithms in batch mode, skip that parameter with the reason; do not drop the test.

- [ ] **Step 2: Run them locally.** Run: `.venv\Scripts\python.exe -m pytest -q -rs tests/test_pgp_backup_gnupg.py`. Expected on a machine with GnuPG 2.4: all pass. They exercise code from Tasks 1–4, so a failure here is a bug there: fix it in the owning module and add the unit test that would have caught it to `tests/test_pgp_backup.py`.

- [ ] **Step 3: Make CI run them.** In the Ubuntu leg of the test matrix add, before `pytest -q`, a step that runs `gpg --version || sudo apt-get install -y gnupg` and sets `GIGAMAIL_REQUIRE_GNUPG=1` for the test step (`if: matrix.os == 'ubuntu-latest'`). The Windows leg keeps skipping when `gpg` is absent.

- [ ] **Step 4: Run with the variable set** (`GIGAMAIL_REQUIRE_GNUPG=1`) locally and ruff. Expected: pass, clean.

---

### Task 7: Documentation, full verification, hand-over

**Files:**
- Modify: `SECURITY.md` (OpenPGP section; the sentence at lines 887–888), `README.md` (the "Encrypted mail" entries in the English, Italian and Chinese sections, lines 97, 459, 786), `CHANGELOG.md` (`## Unreleased`)

- [ ] **Step 1: `SECURITY.md`.** Replace "There is no export or backup of the key yet." with a "Key backup" bullet stating: `gigamail pgp backup` writes the keys to a standard OpenPGP file protected by a passphrase the user chooses (at least 12 characters; AES-256, iterated and salted SHA-256); it needs the OS verification and is not reachable by the agent; the passphrase cannot be recovered; the protection is as strong as the passphrase, since the standard key derivation is not memory-hard; the file is as sensitive as the key; `restore` keeps a replaced key for decryption only. Add under "What it does not protect" the mail-format limit as measured by Task 6's last test: mail between two GigaMail users is not readable by GnuPG 2.4 even with the key; Thunderbird not verified. Say "checked with GnuPG 2.4"; do not say anything was checked with Thunderbird.

- [ ] **Step 2: `README.md`.** One sentence added to each of the three "Encrypted mail" entries: the key can be backed up to a passphrase-protected file and restored (`gigamail pgp backup`, `gigamail pgp restore`). English, Italian and Chinese, matching the surrounding text.

- [ ] **Step 3: `CHANGELOG.md`.** An entry under `## Unreleased`, in the style of the entries there: what the user can now do, that it needs the verification at the PC, the limit with GnuPG 2.4.

- [ ] **Step 4: Full verification.**

Run: `.venv\Scripts\python.exe -m pytest -q` — expected: no failures; report the real counts.
Run: `.venv\Scripts\python.exe -m ruff check src tests extras` — expected: `All checks passed!`
Run: `.venv\Scripts\python.exe -m gigamail.gen_toolmap --check` — expected: no change (no tool was added).
Run: `git diff --stat` and grep the diff and the new files for anything that is not invented data: addresses not on `example.com`, names, key ids or fingerprints copied from a real key.
Run: `git fetch` and `git status -sb` — if the branch is behind `origin/main`, say so in the hand-over.

- [ ] **Step 5: Hand over.** Do not commit. Give the maintainer a commit summary (imperative, one line, English) and a description, the test and lint results as run, and the one thing left to do by hand: import a backup into Thunderbird, read a mail and send a signed one, before the documentation may mention Thunderbird as checked.
