# Correspondents' keys: hold a changed key, show fingerprints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A different OpenPGP key for a known correspondent waits for the user's decision, blocks encryption to that address meanwhile, and fingerprints become visible.

**Architecture:** `peer_keys` keeps accepted keys only; a new table `held_peer_keys` in the same store holds pending, refused and replaced keys. `pgp.encrypt_message` refuses recipients with a pending key, so no caller can skip the check. One function, `pgp.decide_change`, moves a key between the tables; it is reachable from a console click and from the CLI after the OS verification, never from the agent.

**Tech Stack:** Python 3.10–3.13, SQLite, `pysequoia`, FastAPI (`http_api`), Electron console in plain JavaScript (`node --test`).

**Spec:** `specs/2026-11-26-pgp-peer-key-change-design.md`. Read it first: the exact user-facing strings, the store schema and the behaviour tables are there and are not repeated here.

## Global Constraints

- Everything written into the repository is in English. User-facing text carries both languages: in Python `pgp.say(it, en)` / `PgpError(it, en)`; in the console `T('key', 'italian')` with the key added to `console/i18n.js` in it, en and zh.
- No real data: only invented names on `example.com` (`mario.rossi@example.com`, `anna.bianchi@example.com`).
- No new dependency.
- New code in an Italian file is still English; do not translate existing code.
- **Do not commit, push or stage.** The maintainer commits. Each task ends by reporting the files changed.
- Tests: `.venv\Scripts\python.exe -m pytest -q` (whole suite) and `.venv\Scripts\python.exe -m ruff check src tests extras`. Console: `npm test` and `npm run lint` inside `console/`.
- CI runs Python 3.10, 3.12, 3.13 on Ubuntu and Windows: no `tomllib`, no syntax newer than 3.10.
- Schema changes are additive and made in `pgp._create_tables`.
- Keys already in `peer_keys` count as accepted; an upgrade asks nothing.
- The agent must never accept or refuse a key: no MCP tool, no HTTP route without the console click, no CLI path without the OS verification.
- Fingerprints are compared case-insensitively and shown upper case in groups of four.

## Review Focus

Each line has its test in the task named.

1. **The same new key learned twice at once** (watcher and console open the same mail): one pending row, one notice. — Task 4.
2. **A From with a display name or capitals** (`"Anna Bianchi" <Anna.Bianchi@Example.com>`): the same correspondent, the change is held, encryption is blocked. — Task 1, Task 2.
3. **The decision window is open and a newer key arrives**: deciding on the fingerprint shown is refused with a message that says to look again; nothing is accepted unseen. — Task 2, Task 7.
4. **A held row whose key data cannot be read**: other mail still opens and other recipients still encrypt; the bad row is skipped. — Task 3.
5. **A recipient with a pending key written in both To and Cc**: named once in the error, in `status.pending` and in the notice. — Task 2.

---

### Task 1: Store, own addresses, holding a changed key

**Files:**
- Modify: `src/gigamail/core/pgp.py` (`_create_tables`, `learn_autocrypt`, `missing_keys`, `_cert_for`; new functions below)
- Create: `tests/test_pgp_peer_keys.py`
- Modify: `tests/test_pgp.py` only where an existing test asserted silent replacement

**Interfaces:**
- Produces:
  - table `held_peer_keys` and column `peer_keys.first_seen`, as in the spec's "Store";
  - `pgp.peer_key_info(address: str) -> Dict`: `{"address": str, "known": {"fingerprint", "first_seen", "last_seen"} | None, "held": {"fingerprint", "first_seen", "last_seen", "state"} | None}`. `held` is the pending row when there is one, otherwise the most recently decided refused row; a replaced row is never returned;
  - `pgp.pending_changes() -> List[Dict]`: `peer_key_info` of every address with a pending row, by address;
  - `pgp.list_peer_keys() -> List[Dict]`: `peer_key_info` of every address in `peer_keys`, by address;
  - `learn_autocrypt` behaves as the spec's "Learning a key" table and "The user's own addresses".

The test file reuses the helpers of `tests/test_pgp.py` by copying the small ones it needs (`ME`, `PEER`, `_empty_store`, `_autocrypt_of`, `_mail_from_peer` with a `tsk` and a `date` argument).

- [ ] **Step 1: Write the failing tests** in `tests/test_pgp_peer_keys.py`:

```python
OLD = "Thu, 12 Nov 2026 10:00:00 +0100"
NEW = "Fri, 20 Nov 2026 10:00:00 +0100"
NEWER = "Mon, 23 Nov 2026 10:00:00 +0100"


def test_a_changed_key_is_held_and_the_known_one_stays(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    assert pgp.learn_autocrypt(_mail(other, NEW)) is None
    info = pgp.peer_key_info(PEER)
    assert info["known"]["fingerprint"] == _fpr(peer)
    assert info["held"]["fingerprint"] == _fpr(other)
    assert info["held"]["state"] == "pending"
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)


def test_the_same_key_seen_again_asks_nothing(peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(peer, NEW))
    info = pgp.peer_key_info(PEER)
    assert info["held"] is None
    assert info["known"]["first_seen"] < info["known"]["last_seen"]


def test_an_older_mail_with_another_key_creates_nothing(peer, other):
    pgp.learn_autocrypt(_mail(peer, NEW))
    pgp.learn_autocrypt(_mail(other, OLD))
    assert pgp.peer_key_info(PEER)["held"] is None


def test_a_newer_pending_key_replaces_an_older_one(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.learn_autocrypt(_mail(third, NEWER))
    assert pgp.peer_key_info(PEER)["held"]["fingerprint"] == _fpr(third)
    assert len(pgp.pending_changes()) == 1


def test_an_old_mail_does_not_bring_back_a_displaced_pending_key(peer, other, third):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW))
    pgp.learn_autocrypt(_mail(third, NEWER))
    pgp.learn_autocrypt(_mail(other, NEW))
    assert pgp.peer_key_info(PEER)["held"]["fingerprint"] == _fpr(third)


def test_a_display_name_and_capitals_are_the_same_correspondent(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(other, NEW, sender='"Anna Bianchi" <Anna.Bianchi@Example.com>'))
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"


def test_an_own_address_is_never_learned_or_held(peer):
    mine = pgp.own_key(ME)
    pgp.learn_autocrypt(_mail(peer, OLD, sender=ME, addr=ME))
    assert pgp.peer_key_info(ME) == {"address": ME, "known": None, "held": None}
    assert pgp._cert_for(ME).fingerprint == mine.extract_certificate().fingerprint


def test_a_store_from_the_current_version_upgrades_without_a_question(peer):
    # Build the old schema by hand: peer_keys without first_seen, no held table.
    _write_old_store(PEER, peer, last_seen=1_700_000_000.0)
    info = pgp.peer_key_info(PEER)
    assert info["held"] is None
    assert info["known"]["first_seen"] == info["known"]["last_seen"] == 1_700_000_000.0
    assert pgp.pending_changes() == []
```

Fixtures `other` and `third` are further `pysequoia.Tsk.generate(user_id=f"<{PEER}>")` keys; `_fpr(tsk)` is `tsk.extract_certificate().fingerprint`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py -q`
Expected: FAIL (`peer_key_info` not defined).

- [ ] **Step 3: Implement** the schema, the three functions and the new `learn_autocrypt` in `src/gigamail/core/pgp.py`. `missing_keys` and `_cert_for` look at `own_keys` before `peer_keys`. All of one learn happens in one `_db()` transaction.

- [ ] **Step 4: Run the new tests and `tests/test_pgp.py`**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py tests/test_pgp.py tests/test_pgp_backup.py -q`
Expected: PASS. An existing test that expected a newer key to replace the old one silently now expects it held; change that assertion, not the behaviour.

- [ ] **Step 5: Report** the files changed. Do not commit.

---

### Task 2: Deciding, and refusing to encrypt

**Files:**
- Modify: `src/gigamail/core/pgp.py` (`encrypt_message`, `status`, `import_peer_key`; new functions)
- Modify: `src/gigamail/core/imap_client.py:1737-1744` (the `PgpError` branch of the send)
- Modify: `src/gigamail/core/mail_router.py` (`encryption_status`; `_normalize_send_result` if it drops unknown keys)
- Test: `tests/test_pgp_peer_keys.py`

**Interfaces:**
- Consumes: Task 1's tables and `peer_key_info`.
- Produces:
  - `class pgp.KeyChangePending(PgpError)` with `.addresses: List[str]`; texts from the spec's "Encrypting";
  - `pgp.held_changes(recipients: Iterable[str]) -> List[str]`: normalized, unique, in order;
  - `pgp.decide_change(address: str, fingerprint: str, accept: bool) -> Dict`: `{"address", "outcome": "accepted" | "kept", "accepted": <fingerprint now in peer_keys>, "other": <the other fingerprint>}`. Raises `PgpError("Questa non è più la chiave in attesa: riapri e ricontrolla.", "This is no longer the key that is waiting: open it again and check.")` when `fingerprint` is not a pending or refused row of that address;
  - `pgp.status(...)` gains `pending` and `peers` as in the spec;
  - `mail_router.encryption_status(...)["reason"] == "key_changed"`;
  - a blocked send result carries `"blocked": "key_changed"` and `"blocked_addresses": List[str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_nothing_is_encrypted_while_a_change_is_pending(peer, other):
    _known_then_changed(peer, other)
    with pytest.raises(pgp.KeyChangePending) as e:
        pgp.encrypt_message(_clear_mail(), ME, [PEER])
    assert e.value.addresses == [PEER]


def test_a_blocked_send_sends_nothing_and_says_why(smtp, peer, other):
    _known_then_changed(peer, other)
    out = _send(encrypt=True)
    assert out["success"] is False and smtp.sent == []
    assert out["blocked"] == "key_changed" and out["blocked_addresses"] == [PEER]


def test_the_router_keeps_the_blocked_reason(monkeypatch, peer, other):
    # through mail_router.send_message with an IMAP account, as
    # test_router_passes_encrypt_down_to_smtp sets one up
    ...
    assert result["blocked"] == "key_changed"


def test_a_recipient_in_to_and_cc_is_named_once(peer, other):
    _known_then_changed(peer, other)
    assert pgp.held_changes([PEER, f"Anna <{PEER.upper()}>"]) == [PEER]
    st = pgp.status(ME, [PEER, PEER])
    assert [p["address"] for p in st["pending"]] == [PEER]
    assert st["can_encrypt"] is False


def test_status_shows_fingerprints_without_any_change(peer):
    pgp.own_key(ME)
    pgp.learn_autocrypt(_mail(peer, OLD))
    st = pgp.status(ME, [PEER])
    assert st["peers"] == [{"address": PEER, "fingerprint": _fpr(peer)}]
    assert st["pending"] == [] and st["can_encrypt"] is True


def test_accepting_makes_the_new_key_the_one_in_use(peer, other):
    _known_then_changed(peer, other)
    out = pgp.decide_change(PEER, _fpr(other).lower(), accept=True)
    assert out["outcome"] == "accepted" and out["accepted"] == _fpr(other)
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    assert pgp.held_changes([PEER]) == []
    pgp.encrypt_message(_clear_mail(), ME, [PEER])


def test_keeping_the_old_key_is_remembered(peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=False)
    pgp.learn_autocrypt(_mail(other, NEWER))
    assert pgp.held_changes([PEER]) == []
    assert pgp.peer_key_info(PEER)["held"]["state"] == "refused"
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)


def test_a_refused_key_can_be_accepted_later(peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=False)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)


def test_a_replaced_key_that_comes_back_is_held_again(peer, other):
    _known_then_changed(peer, other)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    pgp.learn_autocrypt(_mail(peer, NEWER))
    held = pgp.peer_key_info(PEER)["held"]
    assert (held["fingerprint"], held["state"]) == (_fpr(peer), "pending")
    assert pgp.peer_cert(PEER).fingerprint == _fpr(other)
    assert pgp.held_changes([PEER]) == [PEER]


def test_deciding_on_a_key_that_is_no_longer_pending_is_refused(peer, other, third):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(third, NEWER))
    with pytest.raises(pgp.PgpError):
        pgp.decide_change(PEER, _fpr(other), accept=True)
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)


def test_the_router_reports_key_changed(monkeypatch, peer, other):
    ...
    assert mail_router.encryption_status(1, [PEER])["reason"] == "key_changed"
```

`_known_then_changed(peer, other)` learns `peer` at `OLD` and `other` at `NEW`.

- [ ] **Step 2: Run and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py -q`
Expected: FAIL (`KeyChangePending`, `decide_change` not defined).

- [ ] **Step 3: Implement.** `encrypt_message` calls `held_changes` right after `missing_keys`. `decide_change` is one transaction: on accept, the row it replaces in `peer_keys` is written to `held_peer_keys` as `replaced` with `decided_at` now. `import_peer_key` deletes any held row with the fingerprint it stores. In `imap_client.send_message`, the `except pgp.PgpError` branch adds the two `blocked*` keys when the error is a `KeyChangePending`; make sure they survive to the caller of `mail_router.send_message`.

- [ ] **Step 4: Run**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py tests/test_pgp.py -q`
Expected: PASS.

- [ ] **Step 5: Report** the files changed. Do not commit.

---

### Task 3: Reading — who signed, and `key_change` on every mail

**Files:**
- Modify: `src/gigamail/core/pgp.py` (`open_message`, `_all_peer_certs`, `_address_of`; new functions)
- Modify: `src/gigamail/core/archivio.py` (`_opened_info` and its caller around line 814)
- Modify: `src/gigamail/core/mail_router.py` (`get_message`)
- Test: `tests/test_pgp_peer_keys.py`

**Interfaces:**
- Consumes: Task 1 tables, Task 2 `decide_change`.
- Produces:
  - `open_message` info gains `signer_fingerprint: str | None` and `signer_key: "accepted" | "pending" | "refused" | "replaced" | "own" | None`; for any `signer_key` other than `accepted` and `own`, `signer_matches_from` is false;
  - `pgp.resolve_signer(info: Dict | None, from_address: str) -> Dict | None`: for info with a `signer_fingerprint`, recomputes `signer`, `signer_key` and `signer_matches_from` from the store today; returns info unchanged otherwise;
  - `pgp.key_change_for(address: str) -> Dict | None`: `{"address", "fingerprint"}` when the address has a pending row;
  - the dict returned by `mail_router.get_message` carries `key_change` when its sender has a pending key (every provider, clear mail included).

- [ ] **Step 1: Write the failing tests**

```python
def test_mail_signed_with_a_pending_key_opens_without_signed_by(peer, other):
    _known_then_changed(peer, other)
    opened, info = pgp.open_message(_encrypted_from(other), ME)
    assert info["decrypted"] is True and info["signature_valid"] is True
    assert info["signer_key"] == "pending"
    assert info["signer_fingerprint"].upper() == _fpr(other).upper()
    assert info["signer"] == PEER and info["signer_matches_from"] is False


def test_after_acceptance_the_same_mail_is_signed_by_the_sender(peer, other):
    _known_then_changed(peer, other)
    _, before = pgp.open_message(_encrypted_from(other), ME)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    after = pgp.resolve_signer(dict(before), PEER)
    assert after["signer_key"] == "accepted" and after["signer_matches_from"] is True


def test_mail_signed_with_the_replaced_key_says_so(peer, other):
    _known_then_changed(peer, other)
    mail = _encrypted_from(peer)
    pgp.decide_change(PEER, _fpr(other), accept=True)
    _, info = pgp.open_message(mail, ME)
    assert info["signer_key"] == "replaced" and info["signer_matches_from"] is False
    with_archive = pgp.resolve_signer({"signer_fingerprint": _fpr(peer).lower(),
                                       "signature_valid": True, "signer": PEER,
                                       "signer_key": "accepted",
                                       "signer_matches_from": True}, PEER)
    assert with_archive["signer_key"] == "replaced"


def test_info_archived_before_this_change_is_left_alone():
    old = {"encrypted": True, "decrypted": True, "signature_valid": True,
           "signer": PEER, "signer_matches_from": True}
    assert pgp.resolve_signer(dict(old), PEER) == old
    assert pgp.resolve_signer(None, PEER) is None


def test_a_held_row_that_cannot_be_read_does_not_stop_other_mail(peer, other):
    pgp.learn_autocrypt(_mail(peer, OLD))
    _insert_held_row("luca.verdi@example.com", "AA" * 20, b"not a key", "pending")
    _, info = pgp.open_message(_encrypted_from(peer), ME)
    assert info["decrypted"] is True and info["signer_key"] == "accepted"
    pgp.encrypt_message(_clear_mail(), ME, [PEER])


def test_a_clear_mail_from_a_sender_with_a_pending_key_carries_key_change(
        monkeypatch, peer, other):
    _known_then_changed(peer, other)
    assert pgp.key_change_for(f"Anna <{PEER}>") == {"address": PEER,
                                                    "fingerprint": _fpr(other)}
    # mail_router.get_message with the provider read patched to return a
    # clear mail from PEER
    ...
    assert served["key_change"]["address"] == PEER


def test_the_archive_read_resolves_the_signer_again(archive, peer, other):
    # keep an opened mail signed by `other` while pending, accept, then read
    # it through archivio.leggi with an "arch-" id
    ...
    assert served["encryption"]["signer_matches_from"] is True
```

`_encrypted_from(tsk)` builds a mail encrypted to `ME` and signed by `tsk`, as `_encrypted_from_peer` in `tests/test_pgp.py` does; `archive` is the fixture of that file.

- [ ] **Step 2: Run and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py -q`
Expected: FAIL (`signer_key` missing, `resolve_signer` not defined).

- [ ] **Step 3: Implement.** The certificate store handed to `decrypt` holds accepted and held keys of every state; a row that does not parse is skipped with a log line. The signer is looked up in this order: own keys, accepted, held. In the archive, `resolve_signer` is applied where stored info is served without opening the mail again.

- [ ] **Step 4: Run**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py tests/test_pgp.py -q`
Expected: PASS.

- [ ] **Step 5: Report** the files changed. Do not commit.

---

### Task 4: Telling the user

**Files:**
- Modify: `src/gigamail/policy.py` (new `notify_plain`)
- Modify: `src/gigamail/core/pgp.py` (`learn_autocrypt`; new `note_blocked_send`)
- Modify: `src/gigamail/core/mail_router.py` (`send_message`, after the provider call)
- Test: `tests/test_pgp_peer_keys.py`

**Interfaces:**
- Consumes: `held_peer_keys.told`; the `blocked` / `blocked_addresses` keys of Task 2.
- Produces:
  - `policy.notify_plain(text: str) -> bool`: desktop notification and, when configured, Telegram, with no buttons; never raises, never blocks; reuses what `_notify_now` uses;
  - `pgp.note_blocked_send(addresses: Iterable[str]) -> None`;
  - both notices use the exact texts of the spec's "Telling the user".

A notice is sent only by the caller whose `UPDATE held_peer_keys SET told = told | :bit WHERE address=? AND fingerprint=? AND told & :bit = 0` changed a row: that is what makes it once per key across processes. It is sent after the transaction is committed, and a failure to notify changes nothing else.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.fixture()
def notices(monkeypatch):
    sent = []
    from gigamail import policy
    monkeypatch.setattr(policy, "notify_plain", lambda text: sent.append(text) or True)
    return sent


def test_the_user_is_told_once_when_a_key_changes(notices, peer, other):
    _known_then_changed(peer, other)
    pgp.learn_autocrypt(_mail(other, NEW))      # the other process, same mail
    pgp.learn_autocrypt(_mail(other, NEWER))
    assert len(notices) == 1 and PEER in notices[0]


def test_first_contact_and_the_same_key_tell_nothing(notices, peer):
    pgp.learn_autocrypt(_mail(peer, OLD))
    pgp.learn_autocrypt(_mail(peer, NEW))
    assert notices == []


def test_a_stopped_send_is_told_once(notices, smtp, peer, other):
    _known_then_changed(peer, other)
    del notices[:]
    pgp.note_blocked_send([PEER, PEER])
    pgp.note_blocked_send([PEER])
    assert len(notices) == 1 and PEER in notices[0]


def test_the_router_tells_when_a_reply_is_stopped(monkeypatch, notices, peer, other):
    # mail_router.send_message(encrypt=True) on an IMAP account, blocked
    ...
    assert any("non è partita" in n or "was not sent" in n for n in notices)


def test_a_failing_notification_does_not_break_reading(monkeypatch, peer, other):
    from gigamail import policy
    monkeypatch.setattr(policy, "notify_plain",
                        lambda text: (_ for _ in ()).throw(RuntimeError("no toast")))
    _known_then_changed(peer, other)
    assert pgp.peer_key_info(PEER)["held"]["state"] == "pending"
```

- [ ] **Step 2: Run and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pgp_peer_keys.py -q`
Expected: FAIL (`notify_plain` not defined).

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** the file, then `tests/test_policy*.py` if present.

Expected: PASS.

- [ ] **Step 5: Report** the files changed. Do not commit.

---

### Task 5: HTTP routes, and the agent kept out

**Files:**
- Modify: `src/gigamail/http_api/mail.py` (next to `/encryption/status`)
- Create: `tests/test_http_peer_keys.py`

**Interfaces:**
- Consumes: `pgp.peer_key_info`, `pgp.pending_changes`, `pgp.decide_change`.
- Produces:
  - `GET /encryption/peer_key?address=` → `peer_key_info`;
  - `GET /encryption/pending` → `{"pending": [...]}`;
  - `POST /encryption/peer_key/decide` body `{"address": str, "fingerprint": str, "accept": bool}` → the dict of `decide_change`; 403 `"only from the console"` without the click secret; 409 with the user-language text when `decide_change` raises `PgpError`;
  - every decision is audited: `policy.audit("pgp_key_decision", {"address", "fingerprint", "other"}, "accepted" | "kept", detail="console click")`.

Follow `tests/test_spam_filters.py` for the client and for `console_click.set_secret`.

- [ ] **Step 1: Write the failing tests**

```python
def test_peer_key_info_is_readable_with_the_console_token(client, peer, other): ...
    # 200, body == pgp.peer_key_info(PEER)

def test_pending_lists_every_address_waiting(client, peer, other): ...
    # {"pending": [info]} ; [] when nothing waits

def test_deciding_without_the_click_secret_is_refused(client, peer, other):
    r = client.post("/encryption/peer_key/decide",
                    json={"address": PEER, "fingerprint": _fpr(other), "accept": True})
    assert r.status_code == 403
    assert pgp.peer_cert(PEER).fingerprint == _fpr(peer)

def test_a_console_click_accepts_and_is_audited(client, human, audit_log, peer, other): ...
    # 200, outcome "accepted", one "pgp_key_decision" audit line

def test_a_stale_fingerprint_answers_409(client, human, peer, other, third): ...

def test_the_agent_has_no_way_to_decide_a_key():
    names = _mcp_tool_names()
    assert names
    assert [n for n in names if "peer_key" in n or "decide" in n or "accept_key" in n] == []
    for module in ("server.py", "remote_http.py"):
        source = _source_of(module)
        assert "decide_change" not in source and "import_peer_key" not in source
```

`_mcp_tool_names` is the helper of `tests/test_pgp_backup.py` (copy it).

- [ ] **Step 2: Run and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_http_peer_keys.py -q`
Expected: FAIL (404 on the new routes).

- [ ] **Step 3: Implement** the three routes.

- [ ] **Step 4: Run**

Run: `.venv\Scripts\python.exe -m pytest tests/test_http_peer_keys.py tests/test_pgp_backup.py -q`
Expected: PASS (the backup file's "agent has no way to a secret key" test must still pass untouched).

- [ ] **Step 5: Report** the files changed. Do not commit.

---

### Task 6: Terminal commands

**Files:**
- Modify: `src/gigamail/cli.py` (the `pgp` group, near `cmd_pgp_list`)
- Create: `tests/test_cli_peer_keys.py`

**Interfaces:**
- Consumes: `pgp.list_peer_keys`, `pgp.peer_key_info`, `pgp.decide_change`, the existing `_pgp_verify(reason)` and `_tr(it, en)`.
- Produces: `gigamail pgp peers`, `gigamail pgp accept <address>`, `gigamail pgp keep <address>`; exit codes 0 done, 1 nothing to decide or verification refused, 2 verification unavailable (as the other `pgp` commands). Decisions are audited with `detail="cli"`.

`accept` and `keep` print the address, the known fingerprint and the held one (grouped in fours) **before** asking the OS verification. With no pending key, `accept` acts on a refused one; `keep` prints that there is nothing to decide.

Tests use `GIGAMAIL_CONSENT_BACKEND=allow` with `ADE_MAIL_DRYRUN=1` for the verified path, as `tests/test_pgp_backup.py` does, and a refusing backend for the other.

- [ ] **Step 1: Write the failing tests**

```python
def test_peers_lists_keys_and_what_is_waiting(capsys, peer, other): ...
    # output has PEER, both fingerprints grouped in fours, and marks the pending one

def test_peers_with_an_empty_store_says_so(capsys): ...

def test_accept_after_verification_changes_the_key(verified, capsys, peer, other): ...
    # exit 0; pgp.peer_cert(PEER).fingerprint == _fpr(other); both fingerprints printed

def test_keep_after_verification_refuses_the_key(verified, peer, other): ...

def test_without_verification_nothing_changes(refused, peer, other): ...
    # exit 1 for accept and for keep; still pending

def test_keep_with_nothing_pending_says_so(verified, capsys, peer): ...
    # exit 1

def test_accept_falls_back_to_a_refused_key(verified, peer, other): ...

def test_help_is_in_the_users_language(monkeypatch, capsys): ...
```

- [ ] **Step 2: Run and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_peer_keys.py -q`
Expected: FAIL (unknown subcommand).

- [ ] **Step 3: Implement** `cmd_pgp_peers`, `cmd_pgp_accept`, `cmd_pgp_keep` and their parsers with bilingual help.

- [ ] **Step 4: Run**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_peer_keys.py -q`
Expected: PASS.

- [ ] **Step 5: Report** the files changed. Do not commit.

---

### Task 7: Console

**Files:**
- Modify: `console/mail_render.js` (`encryptionLabel`, `encryptionBadgeHtml`; new `formatFingerprint`, `keyChangeHtml`)
- Modify: `console/encrypt_toggle.js` (`statusText`; new `fingerprintLines`)
- Create: `console/key_change_dialog.js`
- Modify: `console/mail_window_page.js`, `console/renderer_mail.js`, `console/new_mail_window_page.js`, `console/reply_window_page.js`, and the four `.html` files that load them (script tag for the dialog)
- Modify: `console/i18n.js` (new keys in it, en, zh)
- Create: `console/tests/key_change.test.js`; modify `console/tests/encrypt_toggle.test.js`

**Interfaces:**
- Consumes: `msg.encryption.signer_key`, `msg.encryption.signer_fingerprint`, `msg.key_change` (Task 3); `/encryption/status` fields `reason`, `pending`, `peers`, `own_fingerprint` (Task 2); the routes of Task 5.
- Produces:
  - `MailRender.formatFingerprint(fpr) -> string`: upper case, groups of four separated by a space; `''` for empty input;
  - `MailRender.encryptionLabel(enc, T)` returns, besides `tone` and `text`, `fingerprint` (formatted, only for an accepted signer) and `decide` (the address, when the label offers "Review and decide");
  - `MailRender.keyChangeHtml(keyChange, T, esc) -> string`: the line for a mail whose sender has a pending key; `''` otherwise;
  - an element with `data-key-change="<address>"` is the "Review and decide" link in both;
  - `EncryptToggle.statusText(st, T)` handles `reason === 'key_changed'`; `EncryptToggle.fingerprintLines(st, T) -> string[]`;
  - `window.GMKeyChange = { model, open, pendingLine }`:
    - `model(info, T, formatDate) -> {title, rows: [{label, fingerprint, when}], hint, keepWarning, buttons}` (pure, tested);
    - `open({api, address, T, fetchFn, onDone})`: fetches `/encryption/peer_key`, shows the dialog with the existing `console/dialog.js`, posts the decision with the fingerprint that was shown, and on a 409 shows the server's message and loads the dialog again;
    - `pendingLine(count, T) -> string` for the main window.

All strings are in the spec's "Console" section; use them verbatim for it and en.

- [ ] **Step 1: Write the failing tests** (`node --test`, in the style of `console/tests/encrypt_toggle.test.js`):

```js
test('fingerprints are shown upper case in groups of four', () => {
  assert.equal(formatFingerprint('4f2a91c0b77e0d15'), '4F2A 91C0 B77E 0D15');
  assert.equal(formatFingerprint(''), '');
});

test('a mail signed with a pending key offers the decision', () => {
  const l = encryptionLabel({ encrypted: true, decrypted: true, signature_valid: true,
    signer: 'anna.bianchi@example.com', signer_key: 'pending', signer_matches_from: false }, T);
  assert.equal(l.tone, 'warn');
  assert.equal(l.decide, 'anna.bianchi@example.com');
  assert.match(l.text, /non ancora accettata/);
});

test('refused and replaced keys have their own line and never "signed by"', () => { /* both states */ });

test('an accepted signer shows its fingerprint', () => { /* l.fingerprint grouped */ });

test('info without signer_key reads as before', () => { /* the four existing labels unchanged */ });

test('a clear mail from a sender with a pending key shows the line', () => {
  const html = keyChangeHtml({ address: 'anna.bianchi@example.com', fingerprint: 'B77E' }, T, esc);
  assert.match(html, /data-key-change="anna\.bianchi@example\.com"/);
  assert.equal(keyChangeHtml(null, T, esc), '');
});

test('the address is escaped in the link', () => { /* an address with a quote cannot break the attribute */ });

test('compose says why it cannot encrypt', () => {
  const s = statusText({ available: true, can_encrypt: false, reason: 'key_changed',
    pending: [{ address: 'anna.bianchi@example.com' }], missing: [] }, T);
  assert.match(s, /anna\.bianchi@example\.com/);
  assert.match(s, /chiave nuova da accettare/);
});

test('fingerprint lines name the user and each recipient', () => { /* own_fingerprint + peers */ });

test('the dialog shows both keys with their dates', () => {
  const m = model(INFO, T, (ts) => `d${ts}`);
  assert.equal(m.rows.length, 2);
  assert.equal(m.rows[0].fingerprint, '4F2A 91C0');
  assert.equal(m.buttons.length, 3);
});

test('the dialog for a refused key offers to accept it after all', () => { /* held.state === 'refused' */ });

test('a 409 on decide reloads the dialog and accepts nothing', async () => {
  /* fetchFn stub: GET info, POST → 409, GET info again; onDone not called with accepted */
});

test('the pending line counts', () => {
  assert.equal(pendingLine(0, T), '');
  assert.match(pendingLine(2, T), /2/);
});
```

- [ ] **Step 2: Run and see them fail**

Run (in `console/`): `npm test`
Expected: FAIL in `key_change.test.js` and the new cases of `encrypt_toggle.test.js`.

- [ ] **Step 3: Implement** the pure functions and the dialog module, then the i18n keys (`console/tests/i18n_keys.test.js` checks that every key exists in every language).

- [ ] **Step 4: Wire the pages.** Each of the four pages listens for a click on `[data-key-change]` and calls `GMKeyChange.open`; `onDone` reloads the mail (mail windows) or calls `encryptToggle.recheck()` (compose windows). The mail views put `keyChangeHtml(msg.key_change, …)` under the encryption badge. The compose windows show `fingerprintLines` under the status when encryption is on. The main window asks `/encryption/pending` when the mail list loads and shows `pendingLine` above it; a click opens the dialog for the first address and asks again when it closes.

- [ ] **Step 5: Run**

Run (in `console/`): `npm test` then `npm run lint`
Expected: all tests pass, no lint errors (`csp.test.js` included: no inline script, no new remote source).

- [ ] **Step 6: Report** the files changed. Do not commit.

---

### Task 8: Documentation and the whole suite

**Files:**
- Modify: `SECURITY.md`, `README.md` (its English, Italian and Chinese parts, where encryption is described), `CHANGELOG.md` (`## Unreleased`)

**Interfaces:**
- Consumes: the behaviour of Tasks 1–7 as built.

- [ ] **Step 1: `SECURITY.md`.** Replace the declared limit "a correspondent's key is replaced silently / fingerprints not shown" with the behaviour: a changed key is held, encryption to that address stops, only a person decides (console click or terminal after the OS verification), the agent cannot. State what is still open: the first key of a correspondent is accepted on trust; a correspondent with two installations and two keys is asked about at every switch; there is no "verified" mark; two GigaMail installations on one mailbox with different own keys are not handled.

- [ ] **Step 2: `README.md`.** One or two sentences in each language, in the encryption section, and the three terminal commands where the `pgp` commands are listed.

- [ ] **Step 3: `CHANGELOG.md`.** Under `## Unreleased`: the changed-key hold, the fingerprints, the three commands, and that keys already known are kept as accepted.

- [ ] **Step 4: Check the diff for real data.**

Run: `git diff --stat` and search the diff and the new files for any address not on `example.com` and for Italian outside user-facing strings.
Expected: none.

- [ ] **Step 5: Run everything.**

Run: `.venv\Scripts\python.exe -m pytest -q`
Run: `.venv\Scripts\python.exe -m ruff check src tests extras`
Run (in `console/`): `npm test` and `npm run lint`
Expected: all green. Report the real numbers.

- [ ] **Step 6: Report** the files changed, and whether `main` is behind `origin/main` (`git fetch` then `git status -sb`). Do not commit.
