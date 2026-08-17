# Changelog

## v0.1.3 — 2026-08-16

**Fix: data paths are now resolved in exactly one place.**

Six modules used to read `APPDATA` independently, each with its own
fallback (`~/ADE` for five of them, `~/.ade` for the sixth). Under an MCP
client that filters the environment of stdio subprocesses — Hermes passes
only a safe baseline, which does not include `APPDATA` on Windows — the
server silently opened an empty accounts DB and wrote approval requests to
a database the console and CLI never read. No error anywhere: the approval
gate failed silently.

All paths now come from `core/data_paths.py`:

- `ADE_ROOT` relocates everything (accounts, mail data, approvals, audit)
- `ADE_MAIL_DATA_DIR` relocates mail data only
- without `APPDATA`, the POSIX fallback is `~/.ade` — one directory, not two

With `APPDATA` present (any normal Windows setup) nothing moves: paths are
byte-identical to previous releases. Tests: 106 → 111.

**Verified integrations: OpenClaw and Hermes** (see INTEGRATIONS.md).
Tool discovery of all 24 tools verified against OpenClaw 2026.7.1-2
(`openclaw mcp add` + `probe`) and hermes-agent 0.19.0 (`hermes mcp test`),
both on Windows. End-to-end agent workflows on those two platforms are not
yet part of any claim.

## v0.1.2 — 2026-08-15

**Security fix: one approval could execute twice.** Consume was
SELECT-then-UPDATE, so two concurrent phase-2 calls could both see
"approved" and both execute — one human approval, two sends (8/8 with 8
concurrent calls in the regression test). Consume is now a single
conditional UPDATE; the identity of who approved is recorded in the audit
log.

Also: distribution renamed to **gigamail** on PyPI (`pip install
"gigamail[all]"`, verified from a clean venv against the real index),
publishing via GitHub trusted publisher (OIDC, no tokens), commands
`gigamail`, `gigamail-server`, `gigamail-console-api` with the legacy
`ade-mail-agent*` aliases kept.

## v0.1.1 — 2026-08-15

**Security fix: the agent could approve its own destructive actions.**

v0.1.0 returned a one-time confirmation token inside the tool result, which
put it in the model's context. The agent held both halves — the preview and
the key — so an instruction injected through an email could call the tool
again with the token it had just read. The gate stopped accidents, not a
determined injection. Reported on r/mcp by **u/ranbuman**; **u/anderson_the_one**
added the point about binding approval to the exact operation shown.

Approval is now **out of band**:

- a dangerous tool returns only `request_id`, an inert reference — no secret
  enters the model's context
- approval happens through channels the agent has no path to: the console
  API (behind its session token) or `gigamail approvals approve <id>`
- execution uses the canonical arguments stored when the request was made,
  never what the agent passes back at the second call
- repeating a `request_id` returns *awaiting approval*, indefinitely
- approvals live in SQLite, because requesting and approving now happen in
  different processes

New: `gigamail approvals list|approve|reject`, and `/approvals` endpoints on
the console API. Tool parameter renamed `confirm_token` → `request_id`.

Declared limitation: an agent with full shell access on the same machine can
run the approval CLI. That is a different threat model and GigaMail does not
claim to defend it.

Tests: 94 → 103, including one asserting that no MCP tool grants approval and
that the phase-1 payload contains no token. The red-team scenario now
instructs the agent to approve itself; with all tools live, it took no
destructive action.

## v0.1.0 — 2026-08-15

First public release. GigaMail is in daily production use at one company
(real estate: client enquiries answered with figures from our own files,
the right floor plans attached, and appointment slots from the calendar) —
but it is a 0.1: expect rough edges, and read the security model before
pointing it at a mailbox that matters.

### What's in it

**MCP server (stdio, no network port)** — 24 typed tools for an agent:

- *Read (15)*: accounts, identity, knowledge files, messages, unread,
  folders, hybrid search (provider + local index), attachment text, sender
  history, learned correction patterns, calendar events, free-slot
  availability
- *Safe writes (3, audited)*: mark read, move message, create folder
- *Destructive (6, two-phase)*: send, reply, delete message, delete folder,
  create/delete calendar event

**Permission model** — destructive tools never execute on the agent's word
alone: the first call returns a preview and a single-use token (5-minute
TTL), a human approves, the second call executes with the arguments that
were shown. Every write lands in an append-only action log. Login,
credentials and account management are CLI-only and never exposed as tools,
so a hostile email cannot reach them.

**Providers** — Microsoft Graph and IMAP/SMTP (Aruba, Gmail, Libero and any
IMAP server), Microsoft calendar, optional CalDAV configuration.

**Account context** — per-account identity (who you are, what you do, tone)
plus knowledge files you register: price lists, terms, product sheets. The
agent reads them to answer mail, and attachment suggestions follow what it
actually wrote.

**Human console (optional)** — Electron UI over a local HTTP API bound to
127.0.0.1 with a session token. What the old app delegated to an internal
LLM is now delegated to *your* agent through a bridge; there is no LLM
inside GigaMail.

**Privacy** — manual masking from the console (transparent MCP-side
filtering is planned). Mail indexes, credentials and memory stay on your
machine; content your agent reads is handled by that agent's provider.

### Quality

94 tests, green in CI on Windows and Linux across Python 3.10, 3.12 and
3.13. Anti-injection suite included: hostile emails ordering exfiltration,
mass deletion and self-approval with invented tokens were fed to a real
agent with all tools live — no destructive action occurred.

### Known limitations

- The action log is append-only but not tamper-proof.
- The bundled Azure app is not publisher-verified: the Microsoft consent
  screen shows an "unverified" notice. Bring your own `client_id` to avoid
  it; IMAP needs none of this.
- Gmail is supported via IMAP with an app password but has not been tested
  against a live account.
- Not on PyPI yet — install from a clone.
- The distribution/package name is still `ade-mail-agent` internally; the
  commands are `gigamail`, with the old names kept as aliases.
- `mark_spam`, `update_event`, `auth_status`, `search_contacts` and
  `list_followup_needed` are designed but not implemented.

### License

AGPL-3.0-or-later. Commercial licenses for closed-source use are available
from the copyright holder.
