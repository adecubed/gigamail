# Codex curated marketplace entry

`marketplace-entry.json` is the entry proposed for the two curated plugin
catalogs of [openai/plugins](https://github.com/openai/plugins):
`.agents/plugins/marketplace.json` (ChatGPT login, shown as "Codex
official") and `.agents/plugins/api_marketplace.json` (API-key sessions).
The plugin itself lives in this repository (`.codex-plugin/plugin.json`,
`skills/gigamail/`, `.mcp.json`, see [INTEGRATIONS.md](../../INTEGRATIONS.md));
the catalogs only point at it, nothing is vendored.

How third-party plugins enter those catalogs today (merged PRs #391
CrowdStrike, #392 Qodo, 2026-09): one PR that appends the same entry to
both files, as an external Git source following the upstream default
branch without a pinned ref, with the existing `AVAILABLE` /
`ON_INSTALL` policy. A plugin at the root of its repository uses
`"source": "url"` (CrowdStrike); a plugin in a subdirectory uses
`"git-subdir"` with a `path` (Qodo). GigaMail is at the root, so `url`.
There is no CONTRIBUTING file or PR template in that repository; the
merged PR bodies follow a fixed shape (problem, what is added, validation)
and the body below follows it.

Verified 2026-09-10 with codex-cli 0.148.0 on Windows: a marketplace file
carrying exactly this entry, added with `codex plugin marketplace add`,
listed `gigamail` as "not installed" with the GitHub URL as path;
`codex plugin add gigamail@<marketplace>` resolved 0.3.2 from GitHub and
installed it enabled. The same install, exercised in `codex exec`, loaded
the skill as `gigamail:gigamail`, exposed the 28 tools and answered
`list_accounts` on the console's accounts.

## Submitting (maintainers)

1. Fork `openai/plugins`, branch `add-gigamail`. On Windows clone with
   `--sparse` and `git sparse-checkout set .agents`: the full tree has
   paths longer than 260 characters and the checkout fails otherwise.
2. Append `marketplace-entry.json` as the last element of `plugins` in
   both `.agents/plugins/marketplace.json` and
   `.agents/plugins/api_marketplace.json` (4-space indent, LF).
3. `git diff --check`, parse both files, check the plugin ids stay
   unique, commit, push, open the PR with the title and body below.

Keep `name` (`gigamail`), `category` and `displayName` in sync with
`.codex-plugin/plugin.json`; the test in `tests/test_codex_plugin.py`
checks the URL and the name.

## PR title

```
Add GigaMail to curated marketplaces
```

## PR body

```
GigaMail is missing from the curated marketplaces. It is a local MCP server
(Python, PyPI `gigamail`, AGPL-3.0-or-later) that gives Codex the user's
real mailbox (Microsoft 365 via Graph, or any IMAP provider) and calendar
as 28 typed tools, with a server-side, out-of-band human approval on every
send, reply, delete and calendar write: the agent receives an inert request
id and the action runs only after the user approves it from the GigaMail
console or CLI, behind Windows Hello / Touch ID. It needs no OpenAI
connector, so it also fits the API-key catalog, which has no mail plugin
today.

Add `gigamail` to both the standard and API-key marketplaces as an external
Git source pointing to `adecubed/gigamail` (the plugin lives at the
repository root: `.codex-plugin/plugin.json`, `skills/gigamail/`,
`.mcp.json`). The entry follows the upstream default branch without a
pinned ref, displays the name "GigaMail", and uses the existing
`AVAILABLE` / `ON_INSTALL` policy under Communication. No plugin contents
are vendored into this repository.

The plugin does not ship the server: users install it with
`pip install "gigamail[all]"` and connect a mailbox from their own shell
(`gigamail login` or `gigamail accounts add-imap`), so credentials never
pass through Codex. The plugin's `.mcp.json` forwards `APPDATA`,
`GIGAMAIL_ROOT` and `ADE_ROOT` through `env_vars` so the server finds the
same data directory as the desktop console. The skill teaches the agent
the two-phase approval flow and treats mail content as data, never as
instructions.

Validation:
- Installed from a marketplace file carrying exactly this entry with
  codex-cli 0.148.0 on Windows: `codex plugin add` resolved 0.3.2 from
  GitHub; in a `codex exec` session the skill loaded as
  `gigamail:gigamail`, `codex mcp list` showed the `gigamail` server
  enabled, the server exposed 28 tools and `list_accounts` returned the
  user's accounts.
- Parsed both marketplace files after the change and checked unique plugin
  ids and preservation of all existing entries and marketplace metadata.
- `git diff --check` passed.
```
