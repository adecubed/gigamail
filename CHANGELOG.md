# Changelog

## v0.2.2 — unreleased

- **中文**: the README has a full Chinese section and the console speaks
  Chinese (language switch cycles IT → EN → 中; first-pass translation of
  all ~270 strings, with English fallback for anything missed — polish
  and corrections are very welcome: `console/i18n.js`).

- **Changing the Telegram chat revokes trust** (u/Secondmindsystems,
  r/mcp, within hours of the 0.2.1 post): the chat allowed to approve is
  the one recorded behind Windows Hello / Touch ID at `gigamail telegram
  setup --approve`, stored outside `notify.json`. If the configured
  chat_id stops matching it, the watcher disables Telegram approval,
  rejects every pending rule request (`decided_by:
  system:telegram-chat-changed`), alerts the previously trusted chat once,
  and audits the mismatch; approval returns only through the verified
  setup. His second point — an edited draft must invalidate the old
  approval — was already the behaviour (✏️ rejects the old request and
  creates a new request_id; approval binds to the canonical payload), now
  stated explicitly. Note: existing installs must re-run
  `gigamail telegram setup --approve` once to record the trusted chat.

## v0.2.1 — 2026-08-26

**The console catches up with 0.2.** Until now rules, the watcher and the
notification channels existed only in the CLI; the console still showed a
leftover "AI setup" panel (ChatGPT login / OpenAI API key) calling an
endpoint that no longer existed — a relic of the pre-GigaMail app and a
contradiction of "no built-in LLM".

- New **Automations** view: reply rules (list, create, pause, resume,
  delete, per-rule activity), watcher (status, start/stop, log) and a
  notifications/agent panel (which agent writes drafts, whether the human
  verification backend exists, desktop toast buttons with a one-click
  UAC setup, Telegram status).
- Same fence as the CLI: creating or resuming a rule from the console
  raises Windows Hello / Touch ID **in the backend** (`POST /rules`,
  `POST /rules/{id}/resume`) — the console token alone never pre-approves
  anything. Pausing and deleting need no prompt. The Telegram bot token
  is deliberately not enterable from the window (CLI only).
- Backend endpoints: `/rules*`, `/watch/status|start|stop|log`,
  `/notify/status`, `/notify/desktop-setup`. The watcher writes a
  heartbeat (pid, interval, last tick) so the console can tell "running"
  from "stale"; started from the console it runs detached and survives
  closing the window.
- Documents for a rule are chosen with the native file picker; only the
  chosen paths reach the backend.
- Removed: the ChatGPT/OpenAI "AI setup" modal and its i18n strings.

**An unreachable approval store now denies explicitly.** Both phases return
`status: store_unavailable` with a null `request_id`, and phase 2 never
calls the send function — it stays a deny even when the audit log itself
cannot be written. Behaviour under a missing store was already fail-closed
by exception; **u/ranbuman** (r/mcp) named why that is not enough on its
own: a bare exception reads as a bug, so the next person wraps it in a
try/except to quiet the logs and the gate becomes fail-open in a commit
that looks like cleanup. Six tests now turn red if that commit is ever
written. SECURITY.md documents it, including the one case where the hourly
cap does reset — delete the database and restart, which also drops every
pending and approved row: the cap moves, the gate does not.

## v0.2.0 — 2026-08-26 (tagged together with v0.2.1)

**Semi-auto and auto reply — rules with a fence around them.** The first
new capability since the gate: the user can declare, behind Windows Hello /
Touch ID, that mail from certain senders (or in a certain folder) gets a
drafted reply automatically — proposed for approval (`semi`) or sent within
strict limits (`auto`). Email autopilot is an existing category; what the
others don't ship is the fence. Design was published on r/mcp before the
code.

- **`gigamail watch`** — a new CLI process (the MCP server stays passive)
  that polls unread mail, matches rules, has the *user's own agent*
  (`agent_bridge`, default `claude -p`) draft the body, and turns it into a
  standard approval request. GigaMail still contains no LLM.
- **Rules live outside the agent's reach**: created, resumed and only
  manageable via `gigamail rules add/list/pause/resume/remove` — creation
  and reactivation require the OS-level human verification. There is no MCP
  tool that touches rules: a prompt injection cannot say "enable automode".
  Every rule has a mandatory expiry, a daily cap and a per-sender cooldown.
- **Fixed addressing**: the drafter produces the body and nothing else.
  Recipient, thread and subject are fixed by GigaMail from the incoming
  message — the reply goes to the authenticated `From` only, never to
  `Reply-To`, never to addresses written by the draft. An injection in the
  body has no exit channel.
- **Per-rule content**: the draft can only draw from the documents attached
  to that rule (plus the account identity) — no global knowledge, no mail
  search. Blast radius = the files you chose.
- **Deterministic anti-spam barriers, in front of the rules** (no LLM
  decides *whether* to reply): DMARC not `pass` → never `auto`; RFC 3834
  (Auto-Submitted, Precedence bulk/junk/list, List-Id/List-Unsubscribe,
  X-Auto-Response-Suppress, empty Return-Path, no-reply senders) → no reply
  at all; the provider's spam verdict is respected; executable/archive
  attachments and abnormal bodies never trigger; a burst of matches
  **pauses the rule by itself** (resume requires Hello); outgoing rule
  replies are marked `Auto-Submitted: auto-replied` over SMTP (Graph does
  not accept that header — declared, not faked).
- **first_contact: semi** by default — the first message from a new sender
  always goes through human approval, even on an `auto` rule; full auto for
  first contacts is an explicit per-rule opt-in.
- **auto = pre-approval, not self-approval**: the request is created
  already-approved with `decided_by automode:<rule_id>` — the human gave
  that approval behind Hello when creating the rule, for a precise scope,
  with an expiry. Same atomic consume→execute path, same audit, same
  `provider_result`; the pluggable notification (B5) fires either way.
- **Fixed live, day one**: replying through Microsoft Graph was broken —
  the `/reply` payload sent both `message.body` and `comment`, which Graph
  rejects (`SamePropertyContentConflictBody`). It failed as a bare
  `success: false`, because `reply_message` returned a boolean and threw
  the provider's answer away. Now `reply_message` returns the normalized
  result and `provider_result` reaches the audit for replies exactly as it
  does for sends — which is how the bug was found in the first live run of
  a rule (semi, Graph account, notification → Hello → sent, 202).
- **The notification now tells you everything** ("mail arrived from X,
  I propose this reply — approve?"): a new `{message}` placeholder carries
  the full human-readable text (sender, subject, draft body, the approve
  command) to the configured notify command; a **native desktop toast**
  (Windows/macOS/Linux) fires by default on every approval request —
  `GIGAMAIL_NOTIFY_DESKTOP=0` disables it. The notify command can now also
  live in `notify.json` next to `agent.json` (env var still wins), so it
  survives reboots. For `auto` rules the notification fires *after* the
  send, with the real outcome. Notification remains notification: no
  channel approves anything. Notifications speak **the user's language**
  (system locale, `GIGAMAIL_LANG` to override; it/en today) — while the
  *reply* language is chosen by the drafting agent from the incoming mail,
  two different audiences. Measured live on Windows 11: toasts from an
  unpackaged app are silently dropped until a Start-menu shortcut carries
  `System.AppUserModel.ID` — the registry key alone is not enough —
  so GigaMail registers itself (per-user shortcut + HKCU key,
  once, best-effort). Notification commands also survive short-lived
  processes now (`watch --once` no longer kills the notify thread
  mid-flight), and `notify.json` tolerates the BOM that Windows editors
  add.
- **Approve, reject or ask for changes from Telegram.** `gigamail telegram
  setup` (token typed, never an argument) makes Telegram a native channel:
  semi drafts arrive with ✅ / ❌ / ✏️ buttons; the watcher long-polls
  `getUpdates` between ticks and reacts in a second. Commands are accepted
  **only from the configured chat_id** — the Bot API cannot forge a
  message from a user, so a process on the PC cannot say yes for you.
  ✅ requires `--approve`, an explicit opt-in given behind Windows Hello /
  Touch ID (your phone becomes an approval device — see SECURITY.md);
  ❌ and ✏️ never need it. ✏️ asks for your changes, the drafter redoes
  the body with them (and the rejected draft as context), and the new
  draft goes through the gate again — always as semi, even on an `auto`
  rule. Audit: `decided_by: telegram:<chat_id>`; the trusted chat is
  written to the audit at every watcher start.
- **Clickable Windows notifications.** Semi drafts arrive as a toast with
  ✅ / ❌ buttons that open `gigamail://approve/<id>` — a URL scheme that
  launches the CLI, which raises Windows Hello. The toast never approves by
  itself; it opens the door. Measured live: toast buttons resolve custom
  schemes only from the *machine-level* registry (per-user registration is
  enough for the shell, not for toasts), so `gigamail desktop-setup` writes
  that key once behind a UAC prompt; until then toasts arrive without
  buttons (the text still says how to approve) rather than with a dead
  "Get an app" dialog.
- Watcher robustness from the live runs: rules now consider every message
  received after the rule was created, read or unread (a thread open in
  the mail client marks mail read before the watcher sees it) — a mail the
  user already read never goes `auto`, at most `semi`; a draft that times
  out (`claude -p` under load) is retried up to 3 times with a 300 s
  timeout (`GIGAMAIL_DRAFT_TIMEOUT`), then the user is told to reply by
  hand instead of a silent failure.
- **Tool descriptions rewritten for agents** (after glama.ai's Tool Score
  rated `create_folder` D and the `delete_*` tools C: one-line Italian
  descriptions, 0% parameter documentation, no annotations). All 24 tools
  now carry an English description that states purpose, side effects,
  prerequisites, what is returned and what to use instead; every
  parameter is documented in the schema; MCP annotations
  (`readOnlyHint` / `destructiveHint` / `idempotentHint` /
  `openWorldHint`) declare the risk class machine-readably and match the
  READ / WRITE_SAFE / DANGEROUS map. The six two-phase tools share one
  explicit contract text. Server `instructions` are in English too. A
  test keeps all of this from regressing.
- `gigamail rules add` also takes flags (`--senders/--folder`, `--style`,
  `--doc`, `--mode`, caps, expiry) and skips the questions; the Windows
  Hello / Touch ID prompt remains the one thing that cannot be scripted.
- New: `core/rules.py` (`.rules.db`), `core/mail_guard.py`, `watcher.py`,
  `get_message_headers` on both providers (IMAP `BODY.PEEK[HEADER]`, Graph
  `internetMessageHeaders`). 191 tests (was 160), including the
  anti-injection harness extended to rules: a hostile mail in a watched
  folder gets its reply sent only to its own sender, with only the
  drafter's text.

## v0.1.4 — 2026-08-19

**Approval now requires the person at the machine.** Three days after
v0.1.3, **u/ranbuman** (r/mcp) pointed out that "an agent with shell access
can run the approval CLI" is not a different threat model — it is exactly
the agent the gate exists to supervise: Claude Code, OpenClaw and Hermes
all hold a shell. He was right.

- Approving — `gigamail approvals approve <id>` **or** the console's
  `POST /approvals/{id}/approve` — now opens an OS-level user verification:
  **Windows Hello** (PIN/fingerprint/face) on Windows, **LocalAuthentication**
  (Touch ID/password) on macOS. A process can open that prompt; only the
  person at the machine can pass it. No code to type, no file to read, no
  screen to capture. `--yes` is gone. The console token alone no longer
  approves. **No backend, no approval** — the CLI refuses and the console
  returns 503 on machines without Windows Hello / LocalAuthentication.
  Rejecting never needs the prompt.
- Measured, not assumed (Windows 11): the prompt blocks until the human
  answers; a second request right after a successful one raises a **new**
  prompt — no sudo-style grace; it appears from a background process with
  no window. macOS reuse duration is set to 0. Details in SECURITY.md.

**The approval path no longer asserts what it has not verified.**

- **Cap on requests** (promised to u/Rebekator): the same payload with a
  live pending request returns the same `request_id` instead of a new one;
  more than `GIGAMAIL_APPROVAL_MAX_PER_HOUR` (20) per tool per hour →
  `rate_limited`, nothing created. An insisting agent cannot produce a burst
  of identical approvals.
- **Audit from the provider's response** (u/ranbuman): SMTP per-recipient
  refusals are read back from `sendmail()` and recorded as
  `provider_result` next to the approved payload — in the audit log and on
  the approval row (`execution_outcome`: ok / failed / dryrun). Graph
  returns 202 with no per-recipient result: recorded as such
  (`per_recipient_verified: false`), not faked.
- **Preview shows addresses, never display names**, and flags any
  recipient that is not an explicit SMTP address (bare name, group, list)
  as `may_expand` — the count you approve is not guaranteed.
- **SMTP TLS verified by default.** Port 465 used `CERT_NONE`; it now
  verifies, with per-account `insecure_tls` opt-out for self-signed servers.

**Notification.** `GIGAMAIL_APPROVAL_NOTIFY_CMD` (JSON argv with
`{request_id} {tool} {summary}`) runs on every new request — e.g.
`openclaw message send --channel telegram …` to reach you where your agent
lives. Notification only: it cannot approve. Run without a shell, best
effort, one per request (dedup does not re-notify).

**Also:** `GIGAMAIL_ROOT` / `GIGAMAIL_DATA_DIR` (ADE_* kept as aliases);
`GIGAMAIL_APPROVAL_TTL`; MCP server now identifies as `gigamail` with its
package version; console refuses to reuse a port-8002 backend that is not
GigaMail; Dependabot grouped; `server.json` for the official MCP Registry
(`io.github.adecubed/gigamail`) and a README note for agents installing on
a human's behalf.

Tests: 111 → 159. New dependency on Windows: `winrt-Windows.Security.
Credentials.UI` (Microsoft's PyWinRT projection); on macOS:
`pyobjc-framework-LocalAuthentication`.

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
