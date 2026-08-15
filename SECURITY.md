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
- **An agent with full shell access to the same machine.** It can run the
  approval CLI, read the console token, or just use your mail client
  directly. If your agent can run arbitrary commands as you, GigaMail's gate
  is not the weak link — state that threat model honestly rather than
  pretending otherwise.
- Attacks requiring an already-compromised machine or Windows user account.

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
