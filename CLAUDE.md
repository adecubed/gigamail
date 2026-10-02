# Working on GigaMail

Rules for anyone (human or agent) changing this repository. They override
the style of the surrounding code: much of the existing code predates them.

## Language

- **Everything written into the repository is in English**: identifiers,
  module and file names, comments, docstrings, log messages, test names,
  test docstrings, database tables and columns, config and kv keys, URL
  schemes, commit messages, CHANGELOG, docs.
- **Text shown to the user follows their language**: build it with both
  versions and pick one with `policy.user_lang()` (`"it"` / `"en"`), as
  `watcher/telegram.say(tg, it, en)` does. This is the only place Italian
  belongs in new code.
- Prompts sent to the agent are code: write them in English and tell the
  agent which language to answer in.
- Much existing code is still Italian. Do not translate it as a side
  effect of another change: new code in an Italian file is still English,
  and translating a file is a separate commit that does only that.

## No real data

GigaMail is public and is used for real business. Never put into code,
tests, fixtures, docs, CHANGELOG or commit messages anything from a real
mailbox: people's names, email addresses, phone numbers, street
addresses, company names, property or apartment codes, Telegram chat ids,
message ids, prices from real listings. Use invented data on
`example.com` (`mario.rossi@example.com`, "Via Roma 10"). When a comment
needs the story behind a fix, tell it without names ("a client picked
17:00...").

Before handing over a change, grep the diff and the new files for real
names, addresses, numbers and non-`example.com` email addresses.

## Changes

- Every behaviour change comes with tests; run the whole suite
  (`.venv\Scripts\python.exe -m pytest -q`) and report the real result.
- A user-visible change gets an entry under `## Unreleased` in
  `CHANGELOG.md`.
- Trade-specific behaviour (real estate, ...) belongs in `extras/`, not in
  the core.
- Opening a store creates its database file: do not touch the
  appointments store unless `extensions.enabled("appointments")`, or the
  extension switches itself on (`extensions._migra_una_volta`).

## Git

- The maintainer commits and pushes. Do not commit or push: hand over a
  commit summary (imperative, one line) and a description, in English.
- `main` moves often: before handing over, check that the branch is not
  behind `origin/main`; if it is, say so before the maintainer pushes.
