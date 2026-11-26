# OpenPGP key backup and restore — design

Date: 2026-11-25. Status: approved by the maintainer on 2026-11-25.

## Intent

A user who turns on "Encrypt (beta)" gets an OpenPGP secret key per sending
address, stored in `.pgp_keys.db` and encrypted with the accounts key. The
accounts key is tied to the machine (DPAPI, Keychain, Secret Service), so
copying the data folder is not a backup. When the machine is lost, every
encrypted mail left on the server becomes unreadable: the mail never opened
and also the mail already opened, because the decrypted copies lived in the
local archive, which is lost too. `SECURITY.md` declares "no export or backup
of the key yet".

This change lets the user put a copy of the key in a file, protected by a
password, and bring it back: into GigaMail on another installation, and into
other OpenPGP clients (GnuPG, Thunderbird).

## Goals

- `backup`: write the user's own secret keys to one file, in the standard
  OpenPGP format for a secret key protected by a passphrase, which GnuPG and
  Thunderbird import directly, asking for the passphrase.
- `restore`: read such a file back into GigaMail, so mail encrypted to that
  key opens again. It also reads a passphrase-protected or unprotected secret
  key exported by GnuPG or Thunderbird.
- The file opens outside GigaMail, and automated tests prove it with GnuPG.
- Exporting and replacing a secret key happen only at the PC, after the OS
  verification (`consent.require_human`).

## Non-goals (this change)

- A console (Electron) button. This change is the core and the CLI. The
  console screen is a follow-up; it will call the same core functions.
- Automatic or scheduled backup, or sending the backup to the user's mailbox.
- Key rotation, revocation, expiry, showing fingerprints of correspondents.
- Changing how keys are generated or how mail is encrypted (see "Known
  limit: mail format").
- Autocrypt Setup Message.

## Anti-goals

- The agent must never reach the secret key: no MCP tool, no HTTP route, no
  `remote_http` path exports or imports a key. A test pins this.
- A file that looks protected and is not. Every backup is checked before the
  command reports success (see "Self-check").
- A password or key material in logs, in the audit trail, in an error
  message or on the command line (`ps` shows arguments).
- A restore that loses a key: the key it replaces is kept for decryption.

## Constraints

- `pysequoia` (the OpenPGP library in use) reads passphrase-protected secret
  keys (`Tsk.decryptor(password)`, `Tsk.signer(password)`) but has no API to
  write one, or to return the unprotected key. The protect and unprotect
  steps are therefore written here, on top of `cryptography` (already a
  dependency). No new dependency.
- Repository rules in `CLAUDE.md`: English in the repository, user-facing
  text in both languages picked with `policy.user_lang()`, invented data on
  `example.com`, tests for every behaviour change, `ruff` clean, an entry
  under `## Unreleased` in `CHANGELOG.md`.
- CI runs the Python versions listed in `.github/workflows/ci.yml` (3.10,
  3.12 and 3.13 today) on Ubuntu and Windows.
- `cryptography>=42` is the declared floor, and the Intel Mac build pins
  48.0.1. CFB mode moved to `cryptography.hazmat.decrepit.ciphers.modes` in
  recent releases and is announced for removal from the old location: import
  from the new location and fall back to the old one.
- The key store must be closed after every use (Windows cannot delete an
  open file): keep using `pgp._db()`.

## Approaches considered

1. **A password-encrypted OpenPGP message that contains the plain secret
   key.** Needs no hand-written cryptography (`pysequoia.encrypt(passwords=)`).
   GnuPG opens it with `gpg -d file | gpg --import`; Thunderbird cannot import
   it by itself.
2. **The standard secret key with the passphrase on the key itself**
   (RFC 4880 section 5.5.3). GnuPG and Thunderbird import the file directly
   and ask for the passphrase. The library cannot write it: about a hundred
   lines of packet handling and key derivation are ours.
3. **Approach 1 plus an explicit unprotected export for Thunderbird.** Cheap,
   but leaves a plain secret key on disk until the user deletes it.

**Chosen: 2**, by the maintainer: it is the only one where the file a user
hands to Thunderbird is never unprotected. The risk of hand-written
cryptography is held down by two independent readers of the format,
`pysequoia` and GnuPG, both used in the tests.

A throwaway spike on 2026-11-25 confirmed approach 2 on a key generated the
way GigaMail generates them (v4, EdDSA primary and signing subkey, ECDH
encryption subkey): `pysequoia` and GnuPG 2.4.8 both imported the protected
key, decrypted and signed with the right passphrase, and refused a wrong one;
the secret numbers were not present in the protected file; the fingerprint
was unchanged. The spike is not product code and is not in the repository.

## Design

### Format of the backup file

One ASCII-armored `PGP PRIVATE KEY BLOCK` holding the selected keys one after
the other (a keyring). In every Secret-Key and Secret-Subkey packet the
secret material is protected as:

- string-to-key usage octet 254 (SHA-1 integrity check; the form GnuPG 2.4
  and Thunderbird read; AEAD and Argon2 protection are not readable by
  GnuPG 2.4 and are not used);
- cipher AES-256 in CFB mode, fresh random 16-byte IV per packet;
- iterated and salted S2K with SHA-256, fresh random 8-byte salt per packet,
  count octet `0xEE` (31,457,280 bytes hashed);
- every other packet (user IDs, signatures, public parts) copied byte for
  byte, so fingerprints and self-signatures do not change.

Only version 4 keys with these public-key algorithms are handled: RSA (1, 2,
3), ECDH (18), ECDSA (19), EdDSA legacy (22). Anything else (version 6 keys,
algorithms 25–28, an already protected key on the way out) is refused with a
clear error rather than guessed at.

### Unprotecting on restore

GigaMail stores its keys unprotected inside the Fernet envelope:
`pgp.open_message` calls `tsk.decryptor()` and `pgp.encrypt_message` calls
`tsk.signer()`, both with no password. So `restore`
removes the passphrase before storing, then stores as today (`pgp._protect`).

Accepted on the way in: usage 254; ciphers AES-128, AES-192, AES-256;
S2K simple, salted, and iterated-and-salted, with SHA-1, SHA-256 or SHA-512
(with the multi-context derivation when the hash is shorter than the key);
and unprotected keys (usage 0). The SHA-1 check decides whether the
passphrase was right. Refused with a clear error: usage 255 and plain
checksums with encryption, AEAD (253), Argon2, GnuPG's private S2K 101
(smart-card stubs and keys with the secret part removed), anything unknown.

### Where the code goes

- New module `src/gigamail/core/pgp_backup.py`: packet reading and writing,
  `protect(tsk_bytes, passphrase) -> bytes`,
  `unprotect(tsk_bytes, passphrase) -> bytes`, `export_backup(...)`,
  `import_backup(...)`. `pgp.py` stays about mail.
- `pgp.py`: the store gains retired keys (below) and small helpers the
  backup needs (list own keys with fingerprint and creation time, install a
  key for an address).
- `cli.py`: a `pgp` command group.

### Retired keys

Today `own_keys` has one row per address. A new installation generates a new
key on first use, so a later restore meets an existing key for the same
address. Mail received in between was encrypted to that interim key and must
stay readable.

- New table `retired_keys(address, fingerprint, secret_enc, created_at,
  retired_at, PRIMARY KEY (address, fingerprint))`.
- `pgp._own_keys()`, which `open_message` uses to decrypt, also returns the
  retired keys, after the active ones. Retired keys are never used to sign
  or advertised in `Autocrypt:`.
- A signature made by a retired key still verifies as that address ("signed
  by"): the key was replaced, not compromised, and the mail it signed is
  our own. (Builder-check call, see "Calls made after the review".)
- Correspondents learn the restored key from the `Autocrypt:` header of the
  next mail, as they do today for any key change.

### Which key becomes active on restore

The file format has no marker for "active". The rules, applied per address
and in one transaction per file:

- **Order in the file.** `backup` writes, for each address, the active key
  first and the retired ones after it. On restore, the first key in the file
  for an address is the candidate for active; every other key for that
  address is a candidate for retired.
- **A key already in the store** (same address and fingerprint, active or
  retired) is left exactly as it is and reported as "already present".
  Restoring the same file twice changes nothing. Promoting a retired key
  back to active is not part of this change.
- **A new candidate for active** becomes the active key; the key it
  displaces, if any, moves to `retired_keys`.
- **A new candidate for retired** goes to `retired_keys`.
- **A key that cannot do everything.** To become active a key must pass the
  restore self-check for both decrypting and signing, and must not be
  expired or revoked. A key that only decrypts (expired, revoked, no usable
  signing subkey) is installed as retired and reported as such, with the
  reason; the active key stays. A key that cannot decrypt is refused.
- **Several user IDs** (usual in GnuPG and Thunderbird exports). The key is
  installed for every address among its user IDs that is a configured
  account. When none is, it is installed for the address of its first user
  ID, where it only ever decrypts. A key with no address in any user ID is
  refused.

### Commands

```
gigamail pgp list
gigamail pgp backup  [--address A] [--out FILE] [--force]
gigamail pgp restore FILE
```

- `list`: for each own key, the address, fingerprint, creation date and
  whether it is active or retired. No verification needed: nothing secret.
- `backup`: asks for the OS verification, then for a passphrase typed twice
  with `getpass` (never an argument, never echoed). Minimum 12 characters.
  Writes all own keys, active and retired, or only those of `--address`.
  Default file name `gigamail-key-backup-YYYY-MM-DD.asc` in the current
  folder. Refuses to overwrite an existing file without `--force`. The file
  is written to a temporary name in the same folder, owner-only (0600) on
  POSIX, and renamed into place only after the self-check passed. This is
  new code: `accounts._write_private` writes in place and restricts nothing
  on Windows, where the file gets the folder's permissions. Ends by printing
  the path, the fingerprints written, and a reminder that the passphrase
  cannot be recovered.
- `restore`: asks for the OS verification, reads the file, asks for the
  passphrase only when a key in it is protected, and reports per key:
  installed as active, already present, installed as retired, or refused and
  why, following "Which key becomes active on restore".
- When `require_human` raises `ConsentUnavailable` or returns False, nothing
  is read or written and the exit code is non-zero, as in
  `cmd_extensions_enable`.
- Exit codes follow the existing commands: 0 done, 1 refused or failed,
  2 verification not available.
- Each backup and restore is recorded in the audit trail with the
  fingerprints and the file name only.

### Self-check

Before `backup` reports success it re-reads the file it wrote and, for every
key: parses it with `pysequoia`, checks the fingerprint, checks that a test
message encrypted to the key decrypts with the passphrase and does not
without it, and checks that the unprotected secret bytes do not occur in the
file. On any failure the file is deleted and the command fails.

Before `restore` stores a key it checks that the unprotected key decrypts a
test message encrypted to its own certificate, and whether it can sign: the
first decides if the key is accepted at all, the second if it may be active.

### Tests

In `tests/test_pgp_backup.py`, all with invented addresses on `example.com`:

- protect then unprotect returns the original bytes, for a generated key;
- the protected key: same fingerprint, `pysequoia` decrypts and signs with
  the right passphrase, refuses a wrong one and none;
- the secret material is not present in the protected file;
- a wrong passphrase on restore changes nothing in the store;
- restore over an interim key: the interim key becomes retired, a mail
  encrypted to it still opens, new mail is signed with the restored key and
  the `Autocrypt:` header carries it;
- restore of the key already active is a no-op, and so is restoring the
  same file twice;
- a backup with an active and a retired key for one address, restored into
  an empty store: the same one is active again;
- a key with two user IDs is installed for each configured address;
- an expired key and a key without a signing subkey are installed as
  retired and the active key stays;
- a mail signed by a retired key still shows "signed by";
- end to end across two data folders: encrypt a mail in A, back up, restore
  in an empty B, the mail opens in B;
- refusals: version 6 key, unsupported algorithm, S2K 101, AEAD protection,
  truncated file, a public key only;
- CLI: no verification means no file and no store change; an existing file
  is not overwritten without `--force`; a short passphrase is refused; the
  passphrase never appears in output, logs or audit;
- the MCP tool list and the HTTP routes contain nothing that exports or
  imports a key;
- GnuPG interoperability, skipped with a stated reason when `gpg` is not on
  the machine: GnuPG imports the backup, decrypts and signs with the right
  passphrase and fails with a wrong one; a key generated and exported with a
  passphrase by GnuPG is restored by GigaMail and opens a mail GnuPG
  encrypted to it. No workflow installs or mentions `gpg` today. CI must
  actually run these tests on at least one job: the Ubuntu job gets an
  explicit step that installs `gnupg` if absent and sets an environment
  variable that turns a skip of these tests into a failure.

Thunderbird cannot be driven from the test suite. It is checked by hand once
before the release (import the backup, read a mail, send a signed one), and
the documentation says "checked by hand with Thunderbird <version>" only
after that has happened.

### Documentation

- `SECURITY.md`, OpenPGP section: replace "There is no export or backup of
  the key yet" with what the backup is, how it is protected, and its limits:
  the passphrase cannot be recovered; the protection is as strong as the
  passphrase (iterated SHA-256 is not a memory-hard function); the file is
  as sensitive as the key; the verification is the OS one.
- `README.md` (English, Italian, Chinese sections): one line under
  "Encrypted mail".
- `CHANGELOG.md`: an entry under `## Unreleased`.

## Known limit: mail format

Found during the spike and measured on 2026-11-25 with GnuPG 2.4.8,
independent of the backup. Mail between GigaMail users is encrypted and
opens in GigaMail; the limit is only about reading it with another program.

- When every recipient key was generated by GigaMail, `pysequoia` encrypts
  with the newest packet format (version 6 session-key packets, version 2
  encrypted data). GnuPG 2.4 cannot read it ("packet with unknown version
  6"), even holding the key.
- When at least one recipient has a key made by GnuPG, the same call uses
  the older format, and GnuPG reads the mail, the sender's copy included.
- Mail that GnuPG encrypts to a GigaMail key is read by both.
- Generating the key with `Profile.RFC4880` does not change this: GnuPG
  imports the key, and mail encrypted to it is still in the new format.
- Thunderbird was not tried.

So a backed-up key restored into GigaMail opens everything; imported into
GnuPG 2.4 it does not open mail exchanged between two GigaMail users.

The implementation repeats the measurement on a mail produced by
`pgp.encrypt_message`, as a test that documents the behaviour, and
`SECURITY.md` states the limit. Making that mail readable by other clients
(how GigaMail encrypts, or what its keys advertise) is a separate decision,
not part of this change; mail already sent stays in the new format.

## Calls made after the review

A reviewer read this document against the code. These answers are the
author's calls, not decisions the maintainer made; each can be changed
before the plan is written.

1. The first key in the file for an address is the one that becomes active;
   a key already in the store is never moved.
2. A key with several user IDs is installed for every configured address it
   names.
3. A key that can decrypt but not sign (expired, revoked, no signing
   subkey) is kept for decryption only and never becomes active.
4. A signature made by a retired key still shows "signed by".
5. The backup is the CLI only in this change; the console button follows.
6. The passphrase is chosen by the user, at least 12 characters; GigaMail
   does not generate one.
7. `restore` asks for the OS verification too, because it changes which key
   signs the user's mail.

## Left to the builder

- Internal names and the split of functions inside `pgp_backup.py`.
- How the GnuPG tests isolate their home directory (the agent socket needs a
  short path) and stop the agent afterwards.
- The exact wording of the messages, in both languages.
- Whether `list` is also shown by `gigamail check`.
