# ClawHub skill

`gigamail/` is the OpenClaw skill published on [ClawHub](https://clawhub.ai)
as `gigamail`. A skill is a policy layer in the agent's system prompt: it
teaches the OpenClaw agent how to use the GigaMail MCP server and, above
all, how to behave in front of the approval gate. It does not replace the
`mcp.servers` configuration — see [INTEGRATIONS.md](../../INTEGRATIONS.md).

Users install it with:

```bash
clawhub install gigamail
```

Publishing (maintainers), from the repository root:

```bash
clawhub login
clawhub skill publish integrations/clawhub/gigamail --slug gigamail --name GigaMail --version X.Y.Z --dry-run
clawhub skill publish integrations/clawhub/gigamail --slug gigamail --name GigaMail --version X.Y.Z --changelog "..."
```

The skill version follows its own semver (it is text, it changes at a
different pace than the server). Keep `version:` in the SKILL.md
frontmatter and `--version` in sync.
