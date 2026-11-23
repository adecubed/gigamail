# GigaMail on a server, used from your PC

A first step, for people at ease with a terminal. GigaMail normally runs
on the computer where your agent runs: the client starts `gigamail-server`
and talks to it over stdio. With `gigamail-server --http` the same tools
are served over HTTP, so GigaMail can live on a machine that is always on
(a rented server) and be used from Codex or Claude Code on your PC.

What moves to the server: the mail archive, the accounts and their
credentials, the approval queue. What stays the same: sending, replying,
deleting and calendar writes wait for your approval, which no caller can
give.

What is new is who can **read**. Reading, searching and attachments need
no approval: locally only your own agent can reach the server, on a
network whoever reaches the address can. So the HTTP mode does not start
without a key, and listens on the machine itself unless you say that TLS
is done in front of it.

## On the server

```bash
pip install "gigamail[all]"

gigamail login                # Microsoft 365, device flow
gigamail accounts add-imap    # any IMAP provider

gigamail remote key           # prints the key, once: keep it
gigamail-server --http        # http://127.0.0.1:8765/mcp
```

Mailbox credentials are typed in the server's terminal: they never pass
through the agent. `gigamail remote key` keeps only the key's SHA-256;
running it again makes a new key, and the old one stops working at the
server's next start.

Without a key the server refuses to start. `--port` changes the port.

## Reaching it from your PC

The server speaks plain HTTP on 127.0.0.1. Pick one way to get there:

- **An SSH tunnel**, nothing exposed to the internet:
  `ssh -N -L 8765:127.0.0.1:8765 you@your-server`, and the address on your
  PC is `http://127.0.0.1:8765/mcp`.
- **A reverse proxy with TLS** on the server (Caddy, nginx, a tunnel
  service) that forwards `https://mail.example.com` to `127.0.0.1:8765`.
  Start the server with the public name, or it answers 421:
  `gigamail-server --http --allowed-host mail.example.com`.

`--host` with an address that is not loopback is refused, because the key
and the mail would cross the network unencrypted. If TLS really is done
before requests get there (a proxy in another container), add
`--behind-proxy`.

## Connecting the agent

**Codex** (and the ChatGPT desktop app), in `~/.codex/config.toml`, with
the key in an environment variable on your PC:

```toml
[mcp_servers.gigamail]
url = "https://mail.example.com/mcp"
bearer_token_env_var = "GIGAMAIL_REMOTE_KEY"
```

**Claude Code**:

```bash
claude mcp add --transport http gigamail https://mail.example.com/mcp \
  --header "Authorization: Bearer <key>"
```

If GigaMail is also installed on the PC, its local server is already
called `gigamail`: give the remote one another name.

## Approving

There is no console on the server. A request waits until you approve it:

- from the server's terminal: `gigamail approvals list`, then
  `gigamail approvals approve <request_id>`. On Linux this asks for the
  PIN set with `gigamail approvals pin`;
- from Telegram: `gigamail telegram setup --approve` once (it asks for
  the same PIN), and `gigamail watch` running. Without `--approve`
  Telegram only notifies and rejects. Telegram approval is opt-in and the
  weakest channel (see [SECURITY.md](SECURITY.md)). Give the server a bot
  of its own: if a GigaMail on another computer uses the same bot, each
  one takes the other's taps and answers "unknown request".

One thing gets stronger: an agent on your PC has no shell on the server,
so it cannot try `gigamail approvals approve` itself, as long as the PC
holds no way into the server that the agent can use.

## What to know before you rely on it

- **The key is the whole lock on reading.** Anyone who has it and reaches
  the address reads the mailbox. Keep it out of files your agent reads,
  and make a new one if in doubt.
- **The server holds everything.** On a PC the accounts key is tied to
  your login (DPAPI, Keychain, Secret Service). A server without a desktop
  session has none of those: the key that encrypts the accounts is a file
  next to the data. Who reads the data folder, a backup or a disk snapshot
  has both. Protect the machine.
- **One key, one user.** No OAuth, no per-client keys, no limit on how
  much a caller reads, no approval page yet. Approvals that are given only
  at the PC (rules and identity changed by the agent, file and internet
  searches) can be given only from the server's terminal.
- The desktop console does not connect to a remote GigaMail yet. What is
  set only from the console (data masks, spam filters) cannot be set on a
  server; identity, signature, documents, rules and extensions have their
  commands (`gigamail identity`, `gigamail rules`, `gigamail extensions`).

Problems? [github.com/adecubed/gigamail/issues](https://github.com/adecubed/gigamail/issues)
