# GigaMail for Claude

Your real inbox and calendar for Claude, with a human on the send button.

GigaMail exposes your mailboxes (Microsoft 365 via Graph, or any IMAP
provider) and your calendar to Claude as 29 typed MCP tools. Reading,
searching, attachment text, sender history, free-slot computation and
drafting are free. Send, reply, delete and calendar writes return an inert
request id and run only after you approve them out of band, from the
GigaMail desktop console or CLI behind Windows Hello / Touch ID, with the
arguments stored at request time. Mail content is treated as data, never
as instructions.

This plugin adds the `gigamail` MCP server and the `gigamail` skill, which
teaches Claude how the approval gate works.

## Requirements

- **Claude Code, or Cowork running on your computer.** The server is local
  (stdio): it does not run on claude.ai in the browser.
- **The GigaMail server, installed separately** (Python 3.10+). The plugin
  does not ship it:

  ```bash
  pip install "gigamail[all]"
  ```

- **A connected mailbox**, from the CLI. Credentials never pass through
  Claude:

  ```bash
  gigamail login                # Microsoft 365
  gigamail accounts add-imap    # any IMAP provider
  ```

If `gigamail-server` is not on Claude's PATH, set the `GIGAMAIL_SERVER`
environment variable to its absolute path.

## Install

```bash
claude plugin marketplace add adecubed/gigamail
claude plugin install gigamail@gigamail
```

Start a new session afterwards: MCP tools load at startup.

## Data

GigaMail runs on your machine and reads and stores personal data: mail,
contacts and the notes kept on them. Mail cache, credentials, approvals
and audit log stay in a local data directory (`%APPDATA%\ADE` on Windows,
`~/.ade` elsewhere). GigaMail's authors run no service: nothing is sent to
them, and no telemetry. Mail text the tools return reaches the model you
use, like any other tool output.

Services the server talks to, all from your machine:

- **Your mail and calendar provider**: Microsoft Graph, Google APIs, or
  the IMAP / SMTP / CalDAV servers you configure.
- **OpenAI embeddings, only if `OPENAI_API_KEY` is set** in the server's
  environment: mail text is sent to `api.openai.com` to build the search
  memory. Claude Code passes its whole environment to the server, so unset
  the variable (or use a local Ollama instead) if you do not want that.
- **Telegram and Zoom, only if you turn them on**: approvals and
  notifications through your own Telegram bot; Zoom links for meetings.

Source, docs and licence (AGPL-3.0-or-later):
https://github.com/adecubed/gigamail
