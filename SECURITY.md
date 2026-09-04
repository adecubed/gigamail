# Security Policy

GigaMail hands an AI agent access to a mailbox. The whole point of the
project is that this stays safe, so security reports are welcome and taken
seriously.

## Reporting a vulnerability

**Please do not open a public issue for a vulnerability.**

Preferred: [GitHub private vulnerability reporting][gh] — the *Report a
vulnerability* button under the repository's **Security** tab. It creates a
private thread with the maintainers.

[gh]: https://github.com/adecubed/gigamail/security/advisories/new

Alternative: email **Founder@adecubed.com** with `GigaMail security` in the
subject.

What helps us act fast:

- what an attacker gains, and what they need to start (a crafted email? a
  local user account? a malicious MCP client?)
- steps to reproduce — a failing test or a hostile email body is ideal
- the version or commit you tested

You'll get an acknowledgement within **72 hours** and an assessment within
**7 days**. We'll tell you when a fix ships, and credit you in the release
notes unless you'd rather stay anonymous. This is a young project run by a
small team: there is no bounty programme, just genuine gratitude and a
public thank-you.

## In scope

The guarantees this project actually makes — break any of these and we want
to know:

- **The approval gate.** A destructive tool (`send_mail`, `reply_mail`,
  `delete_message`, `delete_folder`, `create_event`, `delete_event`)
  executing without a human approval given out of band — or executing with
  arguments other than the ones the human saw. In particular: **any path by
  which the agent can approve its own request**, or any secret reaching the
  model's context that could be spent to self-approve.
- **Account isolation.** Any path where an agent asking for account X reads
  or writes account Y.
- **Credential exposure.** Passwords, tokens or the account key reachable
  through an MCP tool, the console API, or a log file.
- **The knowledge-file whitelist.** `read_knowledge_file` or
  `list_knowledge_files` reaching a path the user never registered
  (traversal, symlink, UNC, junction).
- **Console API auth.** Any request served without a valid `X-ADE-Token`
  when a token is configured, or the token leaking.
- **Prompt injection that defeats the above** — email content that causes
  any of these outcomes rather than merely persuading the agent to *ask*.
- **The desktop console's renderer.** HTML from a message running script
  in the console, a link inside a message opening anything other than
  `http`, `https` or `mailto`, a renderer window reaching Node, the
  filesystem or a `file://` URL, or the console talking to any host other
  than its own local backend. See "The desktop console" below.

## Out of scope

Not because they don't matter, but because they aren't ours to fix:

- **What your agent decides to do**, as long as GigaMail still enforces the
  gate. If a hostile email convinces an agent to *request* an unwise send,
  the request stops at the preview — that is the design working.
- **Your model provider's data handling.** Content the agent reads leaves
  our boundary; see the README on data.
- **The action log is append-only, not tamper-proof.** Anyone with write
  access to your filesystem can alter `agent_audit.jsonl`. We state this
  plainly rather than pretending otherwise.
- **An agent with shell access using something other than GigaMail.** If
  it can run arbitrary commands as you, it can drive your mail client or
  the provider's API directly, bypassing GigaMail entirely. That is outside
  what a mail gate can enforce. What it can *not* do any more is use
  GigaMail's own approval path — see "Approval requires a human" below.
- Attacks requiring an already-compromised machine or Windows user account.

## Approval requires a human — not just a command

Until v0.1.3 we listed "an agent with shell access can run the approval
CLI" as a different threat model. **u/ranbuman** (r/mcp) pointed out that
this is exactly the agent the gate exists to supervise — Claude Code,
OpenClaw and Hermes all hold a shell — so "out of band from MCP" was not
"out of band from the agent". He was right, and v0.1.4 changes it:

- Approving — from `gigamail approvals approve <id>` **or** from the
  console's `POST /approvals/{id}/approve` — now requires an OS-level user
  verification: **Windows Hello** (PIN, fingerprint, face) on Windows,
  **LocalAuthentication** (Touch ID / password) on macOS. A process can
  *open* that prompt; only the person at the machine can *satisfy* it.
  There is no code to type, no file to read, no screen to capture.
- The CLI flag `--yes` is gone. It was the shortcut an agent would use.
- The console's session token alone no longer approves anything. The token
  lives in a file a process can read; the OS prompt is what it cannot pass.
- **No backend, no approval.** On a machine without Windows Hello or
  LocalAuthentication (headless Linux, a server), the CLI refuses and the
  console returns 503. We fail closed rather than fall back to a keyboard
  confirmation.
- Rejecting never needs the prompt: saying no is always safe.

**What we measured, not what the docs promise** (Windows 11, 2026-08-19,
`UserConsentVerifier.RequestVerificationAsync`): the prompt blocked for
37 minutes until the human answered; a second request issued immediately
after a successful one raised a **new** prompt (24 s of human wait) — no
sudo-style grace window; the prompt appears even when invoked from a
background process with no window. macOS sets
`touchIDAuthenticationAllowableReuseDuration = 0` explicitly. If you find a
platform that caches a verification and cannot be told not to, report it:
on that platform the CLI path should degrade to console-only.

What this does not cover: the same agent driving your mail client or the
provider's API directly. That is no longer GigaMail's approval being
bypassed — it is GigaMail not being in the loop at all.

## Reply rules (0.2): auto means pre-approved, not self-approved

Semi-auto and auto reply look like the opposite of everything above — an
action leaving without a per-send approval. The properties that make it
compatible:

- **A rule is created and reactivated only behind the OS prompt** (Windows
  Hello / Touch ID), only from the CLI or console. **No MCP tool can touch
  rules**: an injected instruction cannot say "enable automode" — the agent
  has no tool for it. Pausing a rule needs no prompt (saying stop is always
  safe); resuming does.
- **Scope is narrow and declared**: specific senders or one folder, only
  the documents attached to the rule as content sources, a daily cap, a
  per-sender cooldown, and a **mandatory expiry**. Never "everything".
- **Fixed addressing**: the drafting agent produces the reply *body* and
  nothing else. GigaMail fixes recipient, subject and thread from the
  incoming message — the reply goes to the `From` that matched the rule,
  never to `Reply-To`, never to addresses appearing in the draft. A prompt
  injection in the mail body has no exit channel.
- **Deterministic barriers decide *whether* to reply; no LLM does**:
  DMARC not `pass` → never auto (a whitelist is worthless on an
  unauthenticated `From`); RFC 3834 auto-generated mail, mailing lists,
  no-reply senders, the provider's spam verdict, executable/archive
  attachments → no reply at all; the first message from a new sender goes
  through human approval by default; a burst of matches pauses the rule
  itself (resume requires the prompt). Headers unreadable = fail closed.
- **The audit trail is identical to a human approval**, with
  `decided_by: automode:<rule_id>` — it is always visible *which* rule let
  *what* through — and the approval-request notification fires for auto
  sends too, so the human sees it even after the fact.
- **Approving from Telegram** (opt-in, `gigamail telegram setup --approve`,
  behind the OS prompt). This looks like the "typeable secret moved to
  chat" we rejected — it is not. The rejected design was a code shown in
  chat that the agent could read and type back. Here the watcher accepts
  `approve / reject / edit` **only from the configured chat_id**, and the
  Bot API cannot fabricate a message *from* a user: a process on the PC,
  even holding the bot token, writes *as the bot*, never as you. The trust
  anchor becomes your phone's Telegram session — the same nature as
  Windows Hello (whoever holds the unlocked phone ≈ whoever knows the
  PIN). Declared limits: the phone is now an approval device, protect it
  like one; a stolen bot token lets someone read the draft previews or
  silence the channel (DoS → fail-closed), **not** approve; `notify.json`
  is a file on disk, so a process with your shell could edit the
  configured chat_id — but the chat that can approve is the one recorded
  behind the OS prompt at `telegram setup --approve`, stored separately.
  When the configured chat stops matching it, the watcher disables
  Telegram approval, revokes every pending rule request, alerts the
  previously trusted chat, and writes the mismatch to the audit; approval
  comes back only through the verified setup path (hardening suggested by
  u/Secondmindsystems on r/mcp). Rejecting and
  asking for changes never need approval rights. Audit: `decided_by:
  telegram:<chat_id>`.
- Declared limit: outgoing rule replies carry `Auto-Submitted:
  auto-replied` over SMTP; Microsoft Graph rejects non `x-*` custom headers,
  so replies sent through Graph do not carry it. Our own loop protection
  does not depend on that header (it is inbound, per RFC 3834).

## When the approval store is unavailable

Every gate here depends on one SQLite file. What happens when it is not
reachable — deleted, locked, permissions revoked mid-run — is part of the
design, not an accident, and it is written down here because
**u/ranbuman** (r/mcp) pointed out why it has to be:

> A bare exception from a missing store looks exactly like a bug, so the
> next person who sees it in the logs wraps it in a try/except to quiet
> the noise, and the gate becomes fail open in a commit that reads like
> cleanup.

So the deny is explicit and named rather than implicit. Phase 1 and phase
2 both return `status: store_unavailable` with `request_id: null`, and
**execution is never attempted** — the send function is not called at all.
It is a deliberate answer, not a crash, and it stays a deny even if the
audit log itself cannot be written. Tests in
`tests/test_store_unavailable.py` assert exactly that, including that
`execute_fn` is never invoked; anyone "cleaning up" the deny turns them red.

**The one case where the rate cap does not hold, stated plainly.** Delete
`approvals.db` and restart the process, and the schema is recreated empty,
so the hourly request counter starts again from zero. The same act drops
every pending and approved row, so there is nothing left to consume: the
cap resets, the gate does not move. Which is the honest framing of what
the cap is — a limiter on how many requests can be *created*, not a
security boundary. The boundary is the human approval plus the OS prompt,
and neither survives in a deleted database.

## Fixed

- **v0.1.1 — agent could self-approve destructive actions.** v0.1.0 returned
  a one-time confirmation token inside the tool result, so it entered the
  model's context: an injected instruction could call the tool again with the
  token it had just read. Approval now happens out of band and the agent
  receives only an inert request id. Reported on r/mcp by **u/ranbuman**,
  with a sharpening from **u/anderson_the_one** on binding approval to the
  exact operation shown. Thank you both.

## The desktop console

The Windows app (0.3) renders mail written by strangers, so its renderer is
treated as hostile ground:

- **One rendering pipeline.** Every message body — main window, detached
  mail window, forward/quote — passes through the same sanitizer
  (`console/mail_render.js`): scripts, event handlers, forms and `javascript:`
  URLs are stripped, and the result is shown in a sandboxed iframe with a
  Content-Security-Policy that allows no script at all.
- **No Node in any renderer.** Context isolation is on, `nodeIntegration`
  off, `webSecurity` on; the only bridge is a preload exposing the backend
  URL and a handful of typed IPC calls. Every window has a CSP meta tag,
  and the backend's responses carry a CSP header as well.
- **Links go through a whitelist.** `shell.openExternal` is never called
  directly: links are routed through one function that accepts only
  `http`, `https` and `mailto`. New windows and navigations are denied.
- **The backend is local and token-gated.** The console spawns its own
  Python on `127.0.0.1` with a per-install random token; the renderer gets
  the URL from the main process, never from a hardcoded port.
- **Features follow the backend.** Buttons whose endpoint the running
  backend does not expose are hidden (`data-requires`), so a console paired
  with a smaller backend cannot call into a void.
- **Not yet code-signed.** Installers are built in CI from the tagged
  commit and attached to the GitHub Release together with `latest.yml`, the
  auto-update feed. Until they are signed, verify the SHA-256 digest shown
  on the Release page before running one.

## How we test this ourselves

Structural anti-injection tests run in CI on every push
([tests/test_injection.py](tests/test_injection.py)). A red-team harness
feeds hostile emails to a real agent with every tool enabled
([scripts/injection_e2e.py](scripts/injection_e2e.py)); it runs with a
dry-run guard, so confirmed destructive actions are audited and never
executed.

For the console: unit tests fire XSS payloads at the sanitizer
([console/tests](console/tests)); an end-to-end run drives the real
Electron app over the DevTools protocol and checks isolation, the link
whitelist, `file://` access and the capability gate
([console/tests/e2e.mjs](console/tests/e2e.mjs)); and every push builds the
installer, installs it on a clean Windows runner, launches the installed
app and repeats the core checks against it
([console/tests/smoke_packaged.mjs](console/tests/smoke_packaged.mjs)).

## Supported versions

Pre-1.0: only the latest release receives fixes. Once 1.0 ships, this table
will list supported lines.
