# Hermes catalog manifest

`optional-mcps/gigamail/manifest.yaml` is the entry proposed for the
Hermes Agent MCP catalog (`hermes mcp catalog` / `hermes mcp install
gigamail`). The catalog is curated: entries live in `optional-mcps/` in
the [hermes-agent](https://github.com/NousResearch/hermes-agent) repository
and are added by PR review — presence there is Nous approval.

Catalog rules that shape this manifest:

- **Pinned transport**: `uvx --from "gigamail[all]==X.Y.Z" gigamail-server`,
  exact version. The pinned release must be **at least two weeks old** at
  pin time; bumping the pin is a PR to the manifest.
- **No secrets through Hermes**: mailbox login happens once with the
  GigaMail CLI, in a shell. The only variable Hermes passes is `ADE_ROOT`
  (non-secret) — Hermes gives stdio servers a filtered environment.
- **Read-mostly default**: `tools.default_enabled` lists the 17 read tools
  and the 3 audited safe writes. The 9 dangerous tools are opt-in at
  install time, and even when enabled they execute only after out-of-band
  human approval.

Verified locally (2026-08-18, with the manifest then pinned to 0.1.3) by dropping the manifest into a Hermes
0.19.0 install: `hermes mcp catalog` lists it, `hermes mcp install
gigamail` prompts for `ADE_ROOT`, probes, prints `post_install`;
`hermes mcp test gigamail` → Connected, 24 tools, transport `uvx` from
PyPI.

Pinned to **0.3.4** (released 2026-09-15, eligible from 2026-09-29). The
PR to hermes-agent was opened on 2026-09-25/26; this directory mirrors it.
The next bump (0.4.0, released 2026-09-30) is eligible from 2026-10-14.
