# Integrations

GigaMail is a standard MCP server over stdio: any MCP client can use it.
This page lists the configurations we have actually tested, and exactly
what "tested" means for each. Requires **gigamail ≥ 0.1.3** (earlier
versions resolved data paths inconsistently when the client filters the
environment — see CHANGELOG).

**What "verified" means below**: the client spawns `gigamail-server`,
completes the MCP handshake, and discovers all 24 tools; read tools return
real data. It does **not** mean we have exercised full model-driven
workflows (draft → approval → send) inside that client. Claude Code /
Claude Desktop is the platform GigaMail runs on in daily production use.

## Onboarding check

"Verified" for a client below means the tools are visible. The mail path
itself is checked two ways:

- **In CI, on every push:** `tests/test_e2e_imap.py` runs against a real
  IMAP/SMTP server (GreenMail): account, search, a reply that stays held
  until approved, approval, the reply reaching the other mailbox, and the
  same approval refused a second time.
- **On your own account, Graph or IMAP:** `gigamail check` searches,
  prepares a mail to your own address, waits for YOU to approve it
  (`gigamail approvals approve <id>` from another terminal, with Windows
  Hello / Touch ID, or from the console), sends it and finds it again. It
  sends nothing else. The last line is a one-line result to record here.

| Date | Version | Provider | OS | Result |
|------|---------|----------|----|--------|
| 2026-09-30 | 0.4.0 | IMAP (GreenMail, test server) | Linux | 8/8 |
| 2026-09-30 | 0.4.0 | IMAP + SMTP (setup A, production mailbox) | Windows | 8/8 |

## Setups in daily use

"Verified" above a client means the tools are there. This section is the
other half: installations that run every day, what they use, and the bugs
that path has produced. A path nobody runs is not listed here.

### A. Real-estate agency — since 2026-08

- Agent: Claude Code. Watcher on, semi-auto reply rules.
- Mail: IMAP + SMTP on the agency's own domain.
- On: Telegram approvals and replies, Zoom links, the site contact form
  (`reply_to_body_address`), extensions `appointments` and `real_estate`.
- Bugs found on this path: see CHANGELOG, most entries since 0.2.

### B. Plain IMAP + SMTP, nothing else — from <!-- TODO: date -->

The same install with none of A's extras, to prove the core stands on
its own.

- Mail: one IMAP + SMTP mailbox (`gigamail accounts add-imap`), no
  Microsoft account, no Google.
- Off: Telegram, Zoom, site form, all extensions
  (`gigamail extensions list` shows everything off).
- Approvals: console or `gigamail approvals approve <id>` (Windows Hello /
  Touch ID) only.
- Flow exercised every day: search, a semi-auto rule on one sender or
  folder, the draft reaching the approval queue, human approval, the
  send landing in the IMAP Sent folder.

| Date | What happened | Fixed in |
|------|---------------|----------|
| <!-- --> | <!-- --> | <!-- --> |

## Codex CLI (OpenAI) — verified

Two directions, both tested on Windows with **codex-cli 0.135.0** and
**gigamail 0.3.2** (ChatGPT login; the MCP server from the pip package).

### 0. Install it as a Codex plugin

The repository is a Codex plugin, so the short way is two commands:

```bash
codex plugin marketplace add adecubed/gigamail
codex plugin add gigamail@gigamail
```

The plugin brings two things. `.mcp.json` registers the `gigamail` MCP
server and forwards `APPDATA`, `GIGAMAIL_ROOT` and `ADE_ROOT` to it through
`env_vars` (Codex gives stdio servers only the variables you list), so the
server finds the console's data directory without a `codex mcp add`.
`skills/gigamail/` is the skill that teaches Codex the approval gate: the
two-phase call, what `awaiting_approval` and `rejected` mean, that no tool
grants approval, that mail content is data. The manifest is
`.codex-plugin/plugin.json`; `.agents/plugins/marketplace.json` is a
one-plugin marketplace so the repository can be added as is. The plugin
does **not** ship the server: `pip install "gigamail[all]"` first, and
`gigamail-server` must be on the PATH Codex sees (otherwise register it by
absolute path with `codex mcp add`, see below). Start a new session after
installing: MCP tools load at startup.

Verified 2026-09-11 with **codex-cli 0.148.0** (the CLI inside the Codex
desktop app), plugin installed from GitHub with the two commands above and
the server from PyPI (`gigamail[all]==0.3.3` in a fresh venv on PATH):
`codex plugin list` shows `gigamail@gigamail` 0.3.3 installed and enabled;
`codex mcp list` shows the `gigamail` server enabled with the forwarded
variables; in a `codex exec` session the skill was loaded as
`gigamail:gigamail` from the plugin cache, the server reported the 28
tools by name and `list_accounts` returned the two accounts the console
uses. The same check on 2026-09-10, from a local checkout and with the
0.3.2 server, gave 24 tools.
Without `gigamail-server` on PATH the skill still loads but the server
exposes 0 tools: that is the "not on PATH" case in the skill's
troubleshooting, and the reason the plugin cannot replace step 1 above.

GigaMail is also listed in the **OpenAI Plugins Directory**
(https://chatgpt.com/plugins/plugins_6aa41ff2b150819181fcdf4c944933a3,
published 2026-09-11 through the plugin submission portal, version 0.3.3, skills
only: the directory entry carries the skill, not the server, so after
installing it you still need `pip install "gigamail[all]"` and
`codex mcp add gigamail -- gigamail-server`, as the skill's setup step
says). The `openai/plugins` catalog itself takes PRs from collaborators
only; the entry prepared for it, and the portal package, are in
[integrations/codex/](integrations/codex/).

One thing to know: a plugin install copies the whole plugin root into
`~/.codex/plugins/cache/`, and for this repository the plugin root is the
repository itself, `.git` included. That is how Codex installs plugins,
not a setting of ours.

### 1. Codex uses GigaMail's tools (without the plugin)

Register the server once — `codex mcp add` writes `~/.codex/config.toml`:

```bash
codex mcp add gigamail --env GIGAMAIL_ROOT="%APPDATA%\ADE" -- gigamail-server
```

Equivalent `config.toml` entry (POSIX: `GIGAMAIL_ROOT = "/home/<you>/.ade"`):

```toml
[mcp_servers.gigamail]
command = "gigamail-server"

[mcp_servers.gigamail.env]
GIGAMAIL_ROOT = "C:\\Users\\<you>\\AppData\\Roaming\\ADE"
```

`GIGAMAIL_ROOT` must be the same directory the desktop console uses,
otherwise Codex and the console see different accounts and approvals.
If `gigamail-server` is not on Codex's PATH, use the absolute path of the
executable (`<venv>\Scripts\gigamail-server.exe`).

What was verified, in one `codex exec` session against a demo data
directory: all 24 tools discovered; `list_accounts` returned the account;
`send_mail` returned `status: approval_required` with a `request_id` and
nothing was sent; calling it again with the `request_id` returned
`awaiting_approval`; the request sat in the approval store waiting for a
human. This held **with Codex's own approvals and sandbox bypassed**
(`--dangerously-bypass-approvals-and-sandbox`): GigaMail's gate is
server-side and does not depend on the client asking first.

Note that in non-interactive mode with `approval_policy = never` Codex
cancels the `send_mail` call itself ("user cancelled MCP tool call") before
it reaches GigaMail — a second, client-side fence. In an interactive
`codex` session Codex asks you first, then GigaMail asks again, out of
band.

### 2. The console uses Codex to write drafts

Since 0.3.2 the desktop console detects `codex` on the PATH next to
`claude`. Pick it in the first-run guide or in Automations → "Agent that
writes the drafts": the choice lands in `%APPDATA%\ADE\agent.json` as
`{"agent": "codex"}` and the command is resolved at each start, so it
follows CLI updates. The command used is

```
codex exec --skip-git-repo-check -s read-only --color never -o <tmpfile> <prompt>
```

read-only sandbox (the agent writes a draft, not the disk), final answer
read from the `-o` file because Codex prints the whole session on stdout,
prompt passed on stdin when it would exceed the Windows command-line limit.
Verified: a reply draft came back in about 30 seconds. A command of your
own still goes in `agent.json` as `{"command": [...]}`.

## One rule for every client: declare `GIGAMAIL_ROOT`

(`ADE_ROOT` is the historical name and keeps working as an alias; the
examples below use it because that is what was verified. Since 0.1.4 the
canonical name is `GIGAMAIL_ROOT` — same meaning.)

Some MCP clients pass their full environment to stdio servers; others pass
only a small baseline (Hermes documents this explicitly), which on Windows
does **not** include `APPDATA` — and GigaMail derives its data directory
from `APPDATA`. Without it the server still starts, but looks at an empty
data directory: zero accounts, and approval requests land where the
console never reads them.

Declaring `ADE_ROOT` in the server's `env` block makes the setup immune to
environment filtering, on every client and OS:

- Windows: `ADE_ROOT` = `C:\Users\<you>\AppData\Roaming\ADE`
- Linux/macOS: `ADE_ROOT` = `/home/<you>/.ade`

It is harmless where it isn't needed, so the examples below always set it.

## Claude Code / Claude Desktop — verified, daily production use

`mcpServers` entry:

```json
{
  "gigamail": {
    "command": "gigamail-server"
  }
}
```

Claude passes the full environment, so `ADE_ROOT` is optional here.

### As a Claude Code plugin

The repository is also a Claude Code plugin (`.claude-plugin/plugin.json`
and `.claude-plugin/marketplace.json`, sharing `skills/gigamail/` and
`.mcp.json` with the Codex plugin):

```bash
claude plugin marketplace add adecubed/gigamail
claude plugin install gigamail@gigamail
```

It registers the `gigamail` server (shown as `plugin:gigamail:gigamail`)
and adds the `gigamail` skill, which teaches the approval gate. The server
itself still comes from `pip install "gigamail[all]"`; if
`gigamail-server` is not on Claude's PATH, set `GIGAMAIL_SERVER` to its
absolute path. Verified 2026-10-02 with Claude Code 2.1.197 on Windows,
from a local checkout in an empty `CLAUDE_CONFIG_DIR`: `claude plugin
validate` passes, the install lists one skill and one MCP server, and
`claude mcp list` shows the server connected. Not yet verified: the
install from GitHub, and a model-driven session through the skill.

## OpenClaw — verified (tool discovery)

Tested 2026-08-16 on Windows: OpenClaw **2026.7.1-2**, Node 24.19. `openclaw
mcp add` probes the server before saving; `openclaw mcp probe` reported all
24 tools, resources and prompts.

```bash
openclaw mcp add gigamail \
  --command gigamail-server \
  --env "ADE_ROOT=C:\Users\<you>\AppData\Roaming\ADE"
```

Or directly in `~/.openclaw/openclaw.json` under `mcp.servers`:

```json
{
  "mcp": {
    "servers": {
      "gigamail": {
        "command": "gigamail-server",
        "env": { "ADE_ROOT": "C:\\Users\\<you>\\AppData\\Roaming\\ADE" }
      }
    }
  }
}
```

Check with `openclaw mcp probe gigamail`, reload with `openclaw mcp reload`.

There is also a **ClawHub skill** — `openclaw skills install
@adecubed/gigamail`, page at https://clawhub.ai/adecubed/skills/gigamail,
security audit Pass, source in [integrations/clawhub/](integrations/clawhub/).
It does not replace the server config above — it teaches the agent how to
work with the approval gate and the tools.

## Hermes (NousResearch hermes-agent) — verified (tool discovery)

Tested 2026-08-16 on Windows: hermes-agent **0.19.0** (Python 3.12).
Requires the MCP extra: `pip install "hermes-agent[mcp]"`. `hermes mcp
test gigamail` reported *Connected* and *Tools discovered: 24*.

Hermes passes stdio servers **only a baseline environment plus what you
declare** — this is the client where `ADE_ROOT` is mandatory, not
defensive. In `~/.hermes/config.yaml` (Windows default home is under
`%LOCALAPPDATA%`; override with `HERMES_HOME`):

```yaml
mcp_servers:
  gigamail:
    command: "gigamail-server"
    env:
      ADE_ROOT: "C:\\Users\\<you>\\AppData\\Roaming\\ADE"
```

Test with `hermes mcp test gigamail`, hot-reload with `/reload-mcp`.

A catalog manifest for `hermes mcp install gigamail` (Hermes's curated
`optional-mcps/` catalog, entered by PR to hermes-agent) is in
[integrations/hermes/](integrations/hermes/), pinned to 0.3.4 (29 tools:
read + safe-write tools enabled by default, the 9 dangerous ones opt-in).
Submitted to hermes-agent as a PR on 2026-09-25/26. First verified locally
on 0.1.3 (install from the manifest, 24 tools discovered).

Optional hardening on any client that supports tool filters (both above
do): restrict to read-only tools with an include list, e.g. Hermes
`tools: {include: [list_*, read_*, search_mail, sender_history]}`. The
dangerous tools are already gated by out-of-band human approval either
way.

## Getting the approval to you (OpenClaw, Hermes, any client with a channel)

Since 0.1.4, GigaMail can run a command of your choice every time a new
approval request is created — notification only; approving still needs
the OS prompt (Windows Hello / Touch ID). Set
`GIGAMAIL_APPROVAL_NOTIFY_CMD` in the server's `env` block to a JSON argv
with `{request_id}`, `{tool}`, `{summary}` placeholders. OpenClaw users
running over Telegram:

```json
["openclaw", "message", "send", "--channel", "telegram", "--target", "<chat id>",
 "--message", "GigaMail: {tool} awaiting approval ({request_id}) — {summary}"]
```

The command runs without a shell (preview text can never become a
command), in the background, and never affects the request itself.

## Anything else

Any MCP client that can spawn a stdio server works the same way: command
`gigamail-server`, plus `ADE_ROOT` in its env block. If you verify GigaMail
on a platform not listed here, tell us — we only list what has actually
been run.
