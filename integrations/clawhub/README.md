# ClawHub skill

`gigamail/` is the OpenClaw skill published on [ClawHub](https://clawhub.ai)
as `gigamail`. A skill is a policy layer in the agent's system prompt: it
teaches the OpenClaw agent how to use the GigaMail MCP server and, above
all, how to behave in front of the approval gate. It does not replace the
`mcp.servers` configuration — see [INTEGRATIONS.md](../../INTEGRATIONS.md).

Page: https://clawhub.ai/adecubed/skills/gigamail — security audit
(NVIDIA SkillSpector + VirusTotal + static analysis): **Pass**.

Users install it with either:

```bash
openclaw skills install @adecubed/gigamail
clawhub install @adecubed/gigamail
```

Publishing (maintainers), from the repository root:

```bash
clawhub login
clawhub skill publish integrations/clawhub/gigamail --slug gigamail --name GigaMail --version X.Y.Z --dry-run
clawhub skill publish integrations/clawhub/gigamail --slug gigamail --name GigaMail --version X.Y.Z --changelog "..."
```

**License.** ClawHub publishes every skill under MIT-0 (the CLI accepts
those terms on publish; the registry schema admits no other value). This
skill text — `gigamail/SKILL.md` — is therefore MIT-0. That does not extend
to GigaMail itself: the server, CLI and console remain AGPL-3.0-or-later
under the repository LICENSE.

The skill version follows its own semver (it is text, it changes at a
different pace than the server). Keep `version:` in the SKILL.md
frontmatter and `--version` in sync.

**Do not bump the skill version during a server release.** Releases 0.2.3
and 0.2.4 raised `version:` in the frontmatter without changing a word of
the skill, which left the repository claiming 0.2.4 while ClawHub served an
identical 0.2.2 — a listing that looks stale but is not. Bump and publish
only when the skill text actually changes; leave it behind the server
number otherwise.
