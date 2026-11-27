# Correspondents' keys: hold a changed key, show fingerprints — design

Date: 2026-11-26. Status: approved by the maintainer on 2026-11-26.

## Intent

GigaMail learns a correspondent's OpenPGP key from the `Autocrypt` header of
the mail they send (`pgp.learn_autocrypt`). When a later mail carries a
different key for the same address, the stored key is replaced at once and
the only trace is a line in the log. From then on GigaMail encrypts to the
new key and shows "signed by" for mail signed with it.

Anyone who can send a mail that appears to come from that address (a forged
From that passes the provider's checks, a taken-over mailbox) can therefore
plant a key of their own, read what the user sends next, and be shown as the
verified sender. The user is never told, and has no screen where a
fingerprint can be read and compared. `SECURITY.md` declares this limit.

This change makes a changed key wait for the user's decision, and shows
fingerprints.

## Goals

- A different key for a correspondent who already has one is **held
  pending**. The known key stays the one in use.
- While a key is pending for an address, **nothing is encrypted to that
  address**: not by the user, not by the agent, not by a rule. The send
  fails with the reason; it never leaves in clear.
- Reading is not affected. Mail signed with the pending key opens, and its
  badge says the signature is from a key not accepted yet.
- **Only a person decides**: accept the new key, or keep the old one. From
  the console (a click) or from the terminal (after the OS verification).
- "Keep the old one" is remembered: that key is not proposed again.
- Fingerprints are visible without any change pending: the user's own and
  the correspondent's, in the mail window and in the compose windows.
- The user is told when a key change is waiting, and when a send stopped
  because of it.

## Non-goals (this change)

- A "verified" mark on a key the user compared by hand.
- A screen with the history of every key a correspondent has had (replaced
  keys are kept, to check old signatures, but not listed in the console).
- Two installations of GigaMail on the same mailbox with different own
  keys.
- Key expiry, revocation, rotation of the user's own key.
- Encryption for Microsoft accounts, Bcc, or any change to the mail format.
- Importing a correspondent's key from a file through the console.

## Anti-goals

- The agent, a rule, a mail, or a script holding the console token must
  never be able to accept or refuse a key. No MCP tool does it; the HTTP
  route answers only to a console click; the CLI asks the OS verification.
  A test pins each of the three.
- A read path that returns a pending or refused key as if it were the
  correspondent's key. `peer_keys` holds accepted keys only, so code that
  reads it cannot make this mistake.
- A send that falls back to clear text, or to the old key without saying
  so, when a change is pending.
- A notification that can be answered from Telegram. Telegram tells; the
  decision is taken at the PC.

## Constraints

- Repository rules in `CLAUDE.md`: English in the repository; user-facing
  text in both languages picked with `policy.user_lang()` (in Python,
  `pgp.say(it, en)` and `PgpError(it, en)`); console strings in
  `console/i18n.js` in the three languages it holds (it, en, zh); invented
  data on `example.com`; tests with every behaviour change; an entry under
  `## Unreleased` in `CHANGELOG.md`.
- No new dependency.
- Existing installations upgrade without a question: every key already in
  `peer_keys` counts as accepted.
- The key store is opened by several processes (console backend, watcher,
  MCP server, CLI). Schema changes are additive and made in
  `_create_tables`, which every connection already runs.

## Approaches

**A. A waiting list next to the accepted keys (chosen).** `peer_keys` stays
as it is and holds accepted keys only. A new table holds the keys that
arrived and were not accepted (pending or refused). Encryption checks the
new table and refuses.
Trade-off: no history of replaced keys; one new column on `peer_keys` to
know since when a key has been known.

**B. A full history in one table.** Several keys per address in
`peer_keys`, each with a state. Gives history, but every query must
remember to filter on the accepted state, and one forgotten filter encrypts
to a key nobody approved. Needs a rebuild of the existing table (its
primary key is the address).

**C. Block at send time only.** Keys keep replacing each other as today; a
flag marks the address as "changed, to confirm" and the send path refuses.
The old key is lost, so "keep the old one" is impossible, and the new key
is already the active one for anything that reads the store.

The maintainer chose A: it does what was decided while leaving the existing
read paths untouched, and it makes the serious mistake impossible by
construction. The history of B can be added later on top of A.

## Design

### Store

`peer_keys` gains one column, `first_seen REAL NOT NULL DEFAULT 0`, added
with `ALTER TABLE` when missing; rows that have 0 are read as
`first_seen = last_seen`. It is set when a key is first stored and kept
when the same key is seen again.

New table:

```sql
CREATE TABLE IF NOT EXISTS held_peer_keys (
    address TEXT NOT NULL, fingerprint TEXT NOT NULL,
    keydata BLOB NOT NULL, prefer_encrypt TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,            -- 'pending' | 'refused' | 'replaced'
    first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    decided_at REAL,                -- when it was refused or replaced
    told INTEGER NOT NULL DEFAULT 0, -- bit 1: arrival told, bit 2: stopped send told
    PRIMARY KEY (address, fingerprint))
```

At most one row per address is `pending`. A `replaced` row is a key that
was the accepted one until the user accepted another: it is kept only to
check signatures on mail it signed, never to encrypt (mail is opened again
from the server at every read, so without it old mail would lose its
signature line).

### The user's own addresses

An address that has a key in `own_keys` is not a correspondent. Its own key
is the only one used for it: `learn_autocrypt` skips it (today a Sent copy
teaches the store the user's own key as a peer key), `_cert_for` and
`missing_keys` look at `own_keys` first, and no change is ever held for it.
Rows already in `peer_keys` for such an address are left and ignored.

### Learning a key (`pgp.learn_autocrypt`)

The checks that exist today stay: the header counts only when its `addr`
is the From address; a mail older than the stored key's `last_seen` changes
nothing. Then, for the sender's address:

| Situation | What happens |
|---|---|
| No accepted key | Stored as accepted (first contact, as today). |
| Same fingerprint as the accepted key | Key data, `prefer_encrypt` and `last_seen` updated in place. No question. |
| Different fingerprint, already `refused` | `last_seen` of that row raised to the mail's time. Nothing else. |
| Different fingerprint, already `pending` | `last_seen` of that row raised to the mail's time. |
| Different fingerprint, new or `replaced` | Stored `pending` (a `replaced` row becomes `pending` again: the user is asked at every switch). A `pending` row for another fingerprint of the same address is deleted. The user is told (see "Telling the user"). |

"Newest" is by the mail's time (`_mail_time`), not by the order of
reading: a mail older than the `last_seen` of the current pending row never
displaces it, and `last_seen` values only go up. Mail is read again and
again, in any order, by several processes; opening an old mail must not
bring back a key that a newer one displaced.

`learn_autocrypt` returns the address when it stored or refreshed an
accepted key, and None otherwise, as today.

`pgp.import_peer_key` (no caller today) stays a direct write of an
accepted key, and also deletes any held row with that fingerprint. It must
stay unreachable from MCP and HTTP.

### Encrypting

New `pgp.held_changes(recipients) -> List[str]`: the addresses among the
recipients that have a `pending` row.

`pgp.encrypt_message` calls it right after `missing_keys` and raises
`KeyChangePending(PgpError)` (new, carries `.addresses`), with the text:

- it: `{who} ha una chiave nuova da accettare`
- en: `{who} has a new key waiting to be accepted`

`imap_client.send_message` already turns a `PgpError` into "Not encrypted,
so not sent: …" and sends nothing; it also puts
`"blocked": "key_changed"` and the addresses in the result for this error,
so callers can tell it apart without reading the text.

A `refused` key does not block: the user chose the old key, and encryption
goes on with it.

`pgp.status(sender, recipients)` gains:

- `pending`: one entry per recipient with a pending change, each
  `{address, known: {fingerprint, first_seen, last_seen},
  held: {fingerprint, first_seen}}`;
- `peers`: `{address, fingerprint}` for every recipient with an accepted
  key;
- `can_encrypt` is false when `pending` is not empty.

`mail_router.encryption_status` sets `reason` to `'key_changed'` in that
case (checked before `'keys'`).

### Reading

`open_message` verifies signatures against the accepted keys **and** the
held ones, so a mail signed with a pending or refused key is recognised
instead of falling into "sender not verified". The info it returns gains:

- `signer_fingerprint`: the fingerprint that signed, when there is a valid
  signature;
- `signer_key`: `'accepted'`, `'pending'`, `'refused'`, `'replaced'` or
  `'own'` (an address with a key in `own_keys` is always `'own'`).

For a held key, `signer` is the address of the held row and
`signer_matches_from` is **false**: nothing that reads the existing fields
shows "signed by" for a key that is not the accepted one.

A mail read from the server is opened again at every read and its info
overwrites the archived one (`archivio.keep_opened`), so the badge follows
the store by itself: after the user accepts a key, mail signed with it
shows "signed by" at the next open, and mail signed with the key it
replaced shows "signed with their previous key". The one path that serves
stored info without opening again is the archive (`archivio._opened_info`):
there, a stored `signer_fingerprint` is resolved against the store when the
mail is served, so both paths give the same answer. Mail archived before
this change has no `signer_fingerprint` and is left as it is.

Every mail served, clear or encrypted, also carries `key_change`:
`{address, fingerprint}` when its sender has a pending key, else absent.
The new key usually arrives in a clear mail, which has no encryption info
at all; this is what lets the console show it there.

### Deciding

`pgp.decide_change(address, fingerprint, accept: bool) -> Dict`, one
transaction, the only function that changes which key is accepted for an
address that already has one:

- `fingerprint` must be a held row of that address (pending or refused);
  otherwise `PgpError`. The caller passes the fingerprint the person was
  shown, so a key that arrived in between is not accepted unseen.
- accept: the held key replaces the row in `peer_keys` (`first_seen` = the
  held row's), the held row is deleted, and the key it replaces is written
  to `held_peer_keys` as `replaced`.
- keep: the held row becomes `refused`, `decided_at` = now.
- A refused key can be accepted later the same way.
- Every decision is written to the audit trail (`policy.audit`) with the
  address, both fingerprints and the channel (console click / CLI).

`pgp.peer_key_info(address) -> Dict`: `{address, known, held}` with the
shapes above (`held` also carries `state`), for the decision window and the
CLI.

**HTTP** (in `http_api/mail.py`, next to `/encryption/status`):

- `GET /encryption/peer_key?address=` → `peer_key_info`. Fingerprints are
  public data: readable with the console token.
- `GET /encryption/pending` → the list of `peer_key_info` for every address
  with a pending key (`pgp.pending_changes()`).
- `POST /encryption/peer_key/decide` `{address, fingerprint, accept}` →
  only for a console click (`console_click.is_console_click`, as
  `http_api/spam.py` does); 403 otherwise.

**CLI** (group `pgp`, bilingual help like the others):

- `gigamail pgp peers` — correspondents' keys: address, fingerprint, known
  since, and any pending or refused key.
- `gigamail pgp accept <address>` and `gigamail pgp keep <address>` —
  print both fingerprints, then ask the OS verification
  (`_pgp_verify`), then decide. With no pending key for the address:
  `accept` falls back to a refused one, `keep` says there is nothing to
  decide.

### Telling the user

A small function in `policy` sends a plain notice (no approval, no
buttons) on the channels approvals already use: desktop notification, and
Telegram when configured. It never raises and never blocks.

- When a key is stored `pending` (once per key, `told` bit 1):
  - it: `GigaMail: {address} ha una chiave di cifratura nuova. Finché non decidi, le mail cifrate per questo indirizzo non partono. Apri GigaMail sul PC per vederla.`
  - en: `GigaMail: {address} has a new encryption key. Until you decide, encrypted mail to this address is not sent. Open GigaMail on the PC to see it.`
- The first time a send stops for that key (once per key, `told` bit 2),
  raised from `mail_router.send_message` when the result is blocked by
  `key_changed`:
  - it: `GigaMail: una mail cifrata per {address} non è partita: ha una chiave nuova da accettare. Apri GigaMail sul PC.`
  - en: `GigaMail: an encrypted mail to {address} was not sent: there is a new key to accept. Open GigaMail on the PC.`

The automatic path that meets this is `mail_router.reply_message`: a reply
to a mail that arrived encrypted is always encrypted, for the agent and the
rules too. The caller gets the same error text in its result.

### Console

All strings go through `console/i18n.js` (it, en, zh). Fingerprints are
shown upper case in groups of four.

**Mail window and reading pane** (`mail_render.encryptionLabel`):

- `signer_key == 'pending'` → tone `warn`: "Cifrata · firmata con una
  chiave nuova, non ancora accettata" / "Encrypted · signed with a new key,
  not accepted yet", with a "Vedi e decidi" / "Review and decide" link.
- `signer_key == 'refused'` → tone `warn`: "Cifrata · firmata con una
  chiave che hai rifiutato" / "Encrypted · signed with a key you refused",
  with the same link.
- `signer_key == 'replaced'` → tone `warn`: "Cifrata · firmata con la
  chiave precedente di {address}" / "Encrypted · signed with the previous
  key of {address}".
- A signed mail from an accepted key shows the signer's fingerprint under
  the badge, in small type.
- Any mail with `key_change`, clear mail included, shows a line under the
  sender, tone `warn`: "{address} ha una chiave di cifratura nuova, non
  ancora accettata" / "{address} has a new encryption key, not accepted
  yet", with the "Vedi e decidi" link. This is where the notice's "open
  GigaMail on the PC" leads.

**Main window**: while `GET /encryption/pending` is not empty, a line above
the mail list: "Chiavi nuove da accettare: {n}" / "New keys to accept:
{n}"; a click opens the decision window for the first, then the next.

**Compose and reply windows** (`encrypt_toggle.statusText`):

- `reason == 'key_changed'` → "Non posso cifrare per {address}: ha una
  chiave nuova da accettare." / "Cannot encrypt to {address}: there is a
  new key to accept." with the "Vedi e decidi" link.
- When encryption is on: a line with the user's own fingerprint and each
  recipient's.

**Decision window** (a dialog over the window that opened it):

```
anna.bianchi@example.com has a new encryption key

Key you knew    4F2A 91C0 …   seen from 3 Oct to 20 Nov
New key         B77E 0D15 …   arrived on 26 Nov

If they reinstalled or changed computer, this is normal.
If in doubt, ask them for the fingerprint by phone.

[Accept the new key]   [Keep the old one]   [Later]
```

Under "Keep the old one", one line: "If they really changed key, they will
not be able to read what you encrypt for them." After a decision the window
that opened the dialog refreshes its badge or status line.

### Documentation

`SECURITY.md` (the limit becomes a described behaviour, with what is still
open: first contact is accepted on trust; a correspondent who uses two
installations with different keys is asked about at every switch; no
"verified" mark), `README.md` in its three languages where it describes
encryption, `CHANGELOG.md` under `## Unreleased`.

## Tests that prove it

- A changed key is held; the accepted key and `peer_cert` do not change.
- With a change pending, `encrypt_message` raises and a send through
  `mail_router.send_message` and `reply_message` sends nothing and reports
  `blocked: key_changed`.
- A refused key does not block, is not proposed again, and can be accepted
  later.
- Same fingerprint with new key data updates in place without a question.
- An older mail with a different key creates nothing.
- A newer pending key replaces an older pending one.
- Mail signed with a pending key opens, with `signer_key == 'pending'` and
  `signer_matches_from` false; after acceptance the same archived mail is
  served as signed by the sender.
- Mail signed with a replaced key is served with `signer_key == 'replaced'`,
  from the server and from the archive alike; the replaced key never
  encrypts.
- A replaced key that shows up again in a newer mail is held pending.
- Opening an older mail does not bring back a displaced pending key and
  sends no second notice.
- An own address is never learned as a peer and never held; a Sent copy
  changes nothing in the store; a clear mail from a sender with a pending
  key is served with `key_change`.
- Upgrade: a store written by the current version (no `first_seen`, no
  held table) opens, and its keys are accepted.
- The decide route answers 403 without the click secret; no MCP tool
  reaches `decide_change` or `import_peer_key`; the CLI commands change
  nothing when the OS verification is refused.
- The two notices are sent once per key each.
- Console: label and status text for the new states (the existing
  `console/tests` style).

## Left to the builder

- Names of private helpers, the layout of the dialog, CSS.
- Where the "resolve again when served" step lives (archive or router), as
  long as both the IMAP read and the archive read give the same answer.
- The Chinese strings.
- How the plain notice reuses the internals of `policy._notify_now`.
