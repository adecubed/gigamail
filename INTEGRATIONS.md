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

## One rule for every client: declare `ADE_ROOT`

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
[integrations/hermes/](integrations/hermes/). Verified locally: install
from the manifest, `uvx --from "gigamail[all]==0.1.3" gigamail-server`,
24 tools discovered, read + safe-write tools enabled by default and the 6
dangerous ones opt-in. Not yet submitted — Nous's pin policy requires the
pinned release to be at least two weeks old.

Optional hardening on any client that supports tool filters (both above
do): restrict to read-only tools with an include list, e.g. Hermes
`tools: {include: [list_*, read_*, search_mail, sender_history]}`. The
dangerous tools are already gated by out-of-band human approval either
way.

## Anything else

Any MCP client that can spawn a stdio server works the same way: command
`gigamail-server`, plus `ADE_ROOT` in its env block. If you verify GigaMail
on a platform not listed here, tell us — we only list what has actually
been run.
