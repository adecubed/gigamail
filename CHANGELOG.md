# Changelog

## v0.3.0 — in progress

The desktop console grows up. 0.2 shipped it as a beta next to the pip
package; 0.3 is about making it something a person can install and use
without reading the README.

- **Onboarding on first launch.** A fresh console no longer opens on an
  empty window: a guided setup inside the main window — same style as
  every other panel, no separate popups — connects a mailbox (Microsoft
  365 device flow or IMAP), fills the account identity and knowledge
  files, shows how to register GigaMail in the agent's MCP client and
  enables notification buttons. It is skippable, reopenable from
  Automations → AI (and from the dashboard while no account exists),
  and its "done" flag lives in the backend, so reinstalling the console
  does not bring it back. Italian, English and Chinese.

- **IMAP accounts are verified before they are saved.** The console
  sent a `provider` key the backend did not know and required hosts it
  did not have, so Gmail/Aruba/Libero saves failed with a 422 — and a
  wrong password was stored silently, to fail at the first sync.
  `POST /accounts/imap` now resolves the provider to its hosts (Outlook
  over IMAP included, SMTP 587 + STARTTLS), attempts a real IMAP login
  and answers 400 with a readable reason instead of writing the account.
  The first account becomes the active one.

- **IMAP-only installs load their accounts.** The console treated
  "connected" as "has a Microsoft token", so a console with only IMAP
  accounts never populated the account selector.

- **One way to render a mail, tested with hostile mail.** The HTML of a
  message went into an iframe by two different code paths (main window
  and mail window) with two different rules; now `mail_render.js` is the
  only one: structural sanitisation via DOMParser (scripts, frames,
  objects, forms, meta, base, links, every `on*` attribute, `javascript:`
  and `vbscript:` URLs, CSS `expression()`), an iframe sandbox with
  neither scripts nor popups, its own CSP, and link clicks that go to the
  system browser instead of navigating the frame. Seventeen known XSS
  payloads run through it in unit tests (jsdom) and in the real Electron
  (`npm run test:e2e`, Chrome DevTools Protocol), which also checks that
  the renderer has no Node, that the preload exposes no secrets, and —
  on a pristine profile — that onboarding opens by itself. The e2e runs
  in CI on Windows before every installer build.

- **The watcher is a package.** `watcher.py` had grown to 1,150 lines
  doing polling, rule matching, drafting, addressing, approvals,
  notifications, Telegram commands and execution in one file. It is
  now `ade_mail_agent/watcher/` with one module per responsibility
  (ingestion, drafting, addressing, approvals, notify, pipeline,
  execution, telegram, process_state, runner) behind the same facade:
  `from ade_mail_agent import watcher` and every public name still
  work, the CLI and the console did not change. The `except: pass`
  around the heartbeat and the Telegram trust warning now log through
  `logging` ("gigamail.watcher") instead of vanishing — a heartbeat
  that fails is exactly what makes the console launch a second watcher.

- **The console API is a package of routers.** `http_api.py` (1,200
  lines, 81 endpoints) is now `ade_mail_agent/http_api/` with one
  FastAPI router per domain — accounts, addresses, mail, calendar,
  mask, agent, approvals, rules/watch, notify/onboarding — behind the
  same `app`, the same paths and the same token middleware (kept in the
  facade so `importlib.reload` in tests still re-reads the token).
  `python -m ade_mail_agent.http_api` and the `gigamail-console-api`
  entry point are unchanged.

- **Mail list and detail leave renderer.js.** `renderer_mail.js` holds
  the list, the message detail with its actions and attachments, and the
  forward composer; the pure parts (`MailView`: list item, detail header,
  HTML→text) are unit-tested with hostile subjects, senders, addresses
  and attachment names. Two things fixed on the way: the forward path
  extracted text by assigning raw mail HTML to an element attached to
  the live document (an `onerror` would fire in the main window), now
  it parses into an inert `DOMParser` document; and the old
  `openMailWindow` built an unescaped HTML page for a `window.open`
  that main.js denies — dead code replaced by a delegation to the real
  mail window. renderer.js goes from 2,055 to 1,465 lines.

- **Console hardening.** Electron permissions are an explicit whitelist
  (microphone only, for dictation), every window carries a CSP without
  `unsafe-eval`, the mail iframe no longer lets popups escape the
  sandbox, and backend responses forbid scripts.

- **One version.** `console/package.json` follows `pyproject.toml`
  automatically at build time; the installer, the Python package and
  the release notes cannot disagree again.

- **Lint in CI**, and two bugs it found: a `NameError` silently dropping
  every message in the IMAP UID listing, and account deletion leaving
  the learned reply patterns behind.

## v0.2.4 — 2026-09-01

A day of using GigaMail on real mail, which is where the rest of these
were found. The recurring shape: something reported success, or reported
a capability it did not have, and only the phone or the customer found
out.

- **Rules can answer the person instead of the portal.** A listings site
  sends its notification from a relay (`reply@idealista.it`) and puts the
  enquirer's address in the body, so a semi-auto rule drafted a perfect
  reply and addressed it to a robot. Fixed addressing stays the default —
  it is what stops a hostile mail redirecting an answer via `Reply-To` —
  but a rule can now opt out with `reply_to_body_address`. The extracted
  address is shown in the approval preview, flagged as coming from the
  body, because it is the one field that does not come from an
  authenticated sender. No address found skips the message rather than
  falling back to the relay.

- **Rules carry cc and attachments.** Attachment names resolve against
  the account identity and are listed with real sizes in the preview; a
  name that no longer resolves skips the message instead of sending a
  mail that cites floor plans it does not have. `gigamail rules add`
  resolves them once at creation so a typo surfaces then, not a month
  later.

- **The watcher survives logout.** `scripts/watch-task.ps1` registers it
  with Task Scheduler, in the user's interactive session — never as
  SYSTEM, because account passwords are sealed with per-user DPAPI and
  approval toasts only exist inside a session. Stopping the task does not
  kill the tree it launched, which left two watchers competing over the
  same mail, so the launcher now asks `gigamail watch-running` first and
  that answer moved into `watcher.running_state()`, shared by console,
  CLI and task.

- **Telegram approvals actually work.** Requests raised by a tool arrived
  with no buttons, and tapping one answered "unknown request" because the
  handler required a rule row. Both fixed. Approving a tool request from
  the chat does not send — phase 2 belongs to the agent that asked — and
  the reply says so instead of implying the mail left.

- **Nothing in a Telegram approval is tappable except the buttons.**
  Without `parse_mode` Telegram linkifies addresses itself, so in a
  buttonless message the only thing to press was the recipient's
  `mailto:` — which opens the phone's mail client and asks you to sign
  in. An approval whose single affordance is an unexpected login prompt
  is indistinguishable from phishing, on the one channel with no Hello
  behind it. Addresses and URLs now go in `<code>`.

- **The chat shows the whole mail**, not just its subject: sender,
  recipients, cc, attachments and body, trimmed to fit Telegram's limit
  with the cut labelled. The toast can stay terse because it has a Leggi
  button; the chat has no second step.

- **A request that expired is not one that was decided.** The reply said
  "already decided or expired (pending)" — two contradictory things at
  once. The cases now read differently, and the buttons are stripped the
  moment you discover the request is dead, so the message stops offering
  actions that can only be refused.

- **No more announcing an approval that is switched off.** `notify.json`
  can say `approve: true` while no chat was ever recorded behind Windows
  Hello; the watcher logged "Telegram con approvazione" on the strength
  of the file alone, and the only way to learn otherwise was to tap
  Approva and be told no.

- **Optional PIN before approving from Telegram** (`gigamail telegram
  pin`, set and removed behind Hello). A tap alone means whoever holds
  the unlocked phone can send mail. Stored as scrypt with a random salt,
  three wrong tries lock the channel for 15 minutes, and the message
  carrying the PIN is deleted whether it was right or wrong. It is not
  Hello and does not pretend to be: the PIN crosses the chat in clear, so
  it guards against a phone left unlocked, not against someone who
  controls the Telegram account.

## v0.2.3 — 2026-08-31

Four bugs found by using GigaMail for a real morning of mail, not by
reading the code. Three of them shared a shape: the action reported
success and did the wrong thing quietly.

- **Approval toasts came out mute.** Every MCP tool creates its request
  through `require_approval()`, which notified without passing `actions`
  — so the toast was built with no buttons and the human saw an alert
  with nothing to press. Only the watcher's semi-auto path passed them,
  which is why the feature looked like it worked. Now every approval
  carries the same four: Leggi / Approva / Modifica / Rifiuta. **Leggi**
  shows the entire preview (no more 300-character truncation of a mail
  body) and lets you decide on the spot — reading and deciding are the
  same moment. **Modifica** rejects the request and hands back your note.
  Buttons still only open a `gigamail://` URL: Approva goes through
  Windows Hello exactly as before.

- **A second Python on the machine silenced the buttons.**
  `protocol_registered()` compared the HKLM registration with
  `sys.executable`, so the system Python next to the venv one produced a
  mute toast without a word. What matters is the *registered* command,
  not who is reading it.

- **Multi-recipient sends put one malformed address in the envelope.**
  `send_mail("a@x.it, b@y.it")` passed the string whole: SMTP issued a
  single `RCPT TO:<a@x.it, b@y.it>`, Graph a single `toRecipients`. The
  provider need not refuse it — ours didn't, returning `success: true`
  and `"accepted": 1`. Half the recipients were never in the envelope and
  nothing said so; the `To:` header was right, so the copy in Sent looked
  fine. `split_addresses()` (new `core/addresses.py`) is now used by
  SMTP, by Graph **and** by the preview you approve, so the list you
  approve and the envelope that leaves cannot drift apart.

- **`send_mail` and `reply_mail` can attach identity files.** Only files
  registered in that account's identity (price lists, floor plans),
  never an arbitrary path — otherwise send_mail is the easiest way to
  walk a file off the disk, and approval doesn't help, because the human
  approves a *name*. The preview lists name, path and real size of every
  attachment; a name that resolves to nothing aborts the request rather
  than sending a mail without the plan its body promises.

- **Dotted names resolved to the wrong file.**
  `os.path.splitext("B.1.3")` returns `("B.1", ".3")`, so a lookup for
  apartment B.1.3 searched for "B.1" and matched B.1.1, B.1.2, B.1.4 as
  well — first one wins. Silent: the mail went out carrying another
  apartment's floor plan. `read_knowledge_file` shares that function, so
  asking for one data sheet could return another. Fixed, and an
  ambiguous name now stops the request instead of guessing.

- **Toasts stayed put and stopped swallowing each other.** Five approvals
  raised in a row appeared as one: Windows collapses toasts from the same
  app unless each carries its own `tag`, so four vanished silently at the
  exact moment there were five decisions to make. The tag is now the
  request_id — and re-raising the *same* request replaces its toast
  instead of stacking a duplicate. The popup also no longer expires under
  you mid-read (`scenario='reminder'`: it stays until you decide; Windows
  offers no arbitrary duration, `duration='long'` tops out near 25s).
  The 15 minutes now live where they are real: the notification is born
  with the request's own TTL, so it sits in the action centre exactly as
  long as the approval is valid and removes itself when it dies — no
  Approva button on a request that can no longer be approved.

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
