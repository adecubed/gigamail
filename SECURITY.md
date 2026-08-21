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
- Declared limit: outgoing rule replies carry `Auto-Submitted:
  auto-replied` over SMTP; Microsoft Graph rejects non `x-*` custom headers,
  so replies sent through Graph do not carry it. Our own loop protection
  does not depend on that header (it is inbound, per RFC 3834).

## Fixed

- **v0.1.1 — agent could self-approve destructive actions.** v0.1.0 returned
  a one-time confirmation token inside the tool result, so it entered the
  model's context: an injected instruction could call the tool again with the
  token it had just read. Approval now happens out of band and the agent
  receives only an inert request id. Reported on r/mcp by **u/ranbuman**,
  with a sharpening from **u/anderson_the_one** on binding approval to the
  exact operation shown. Thank you both.

## How we test this ourselves

Structural anti-injection tests run in CI on every push
([tests/test_injection.py](tests/test_injection.py)). A red-team harness
feeds hostile emails to a real agent with every tool enabled
([scripts/injection_e2e.py](scripts/injection_e2e.py)); it runs with a
dry-run guard, so confirmed destructive actions are audited and never
executed.

## Supported versions

Pre-1.0: only the latest release receives fixes. Once 1.0 ships, this table
will list supported lines.
