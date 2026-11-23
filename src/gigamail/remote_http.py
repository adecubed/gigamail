"""gigamail-server over HTTP, for an agent that runs on another computer.

The MCP server is stdio by design: the client starts it and nobody else
can reach it. `gigamail-server --http` serves the same tools over MCP's
Streamable HTTP transport instead, so that GigaMail can live on a machine
that is always on (a rented server) and be used from Codex or Claude Code
on a PC. Off unless asked for.

What changes with a network address is who can READ. Sending, deleting and
calendar writes already wait for a human approval that no caller can give;
reading, searching and attachments are free to whoever reaches the server.
So this module refuses to serve without the three things that decide that:

- a key. Every request must carry `Authorization: Bearer <key>`. The key is
  made by `gigamail remote key`, shown once, and only its SHA-256 is kept
  (remote_key.sha256 in the data folder). No key file, no server.
- a loopback address by default. On 127.0.0.1 the server is reachable from
  the machine itself only: a reverse proxy or a tunnel in front of it does
  the TLS. Any other address must be asked for with --behind-proxy, which
  is the operator saying that TLS is done before the request gets here:
  this module speaks plain HTTP, and plain HTTP on a network shows the key
  and the mail to whoever carries the packets.
- the Host names it answers to, when a proxy forwards a public name
  (--allowed-host): the MCP library rejects the others.

Not here yet, on purpose: OAuth, per-client keys, a read budget, an
approval page. Approvals on a server are given from its terminal
(`gigamail approvals`) or from Telegram.
"""
import hashlib
import hmac
import json
import os
import secrets
import sys
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PATH = "/mcp"
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


class RefusedToServe(Exception):
    """A condition for serving over HTTP is missing. The message says which
    and what to run."""


def key_file() -> Path:
    from gigamail.core.data_paths import app_root
    return app_root() / "remote_key.sha256"


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key() -> str:
    """Make a key, keep its SHA-256 and return the key: the only time it
    exists in clear on this machine. A previous key stops working."""
    key = secrets.token_urlsafe(32)
    path = key_file()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(_digest(key) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def stored_digest() -> str:
    """The SHA-256 of the current key, or "" when none was made (or the
    file does not hold one)."""
    try:
        value = key_file().read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeDecodeError):
        return ""
    return value if len(value) == 64 and all(c in "0123456789abcdef" for c in value) else ""


def key_matches(presented: str, digest: str) -> bool:
    return bool(digest) and hmac.compare_digest(_digest(presented), digest)


class BearerGate:
    """ASGI middleware: an HTTP request without the key gets 401 and never
    reaches the MCP server. The digest is read once, at start: a new key
    takes a restart, so a key cannot be swapped under a running server."""

    def __init__(self, app, digest: str):
        if not digest:
            raise RefusedToServe("no key")
        self._app = app
        self._digest = digest

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)  # the server's own start and stop
            return
        if scope["type"] != "http":
            # A websocket (or anything a later ASGI server invents) is not a
            # request this gate knows how to check: it goes no further.
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        presented = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                scheme, _, rest = value.decode("latin-1").partition(" ")
                if scheme.lower() == "bearer":
                    presented = rest.strip()
                break
        if not key_matches(presented, self._digest):
            body = json.dumps({"error": "unauthorized"}).encode("ascii")
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ]})
            await send({"type": "http.response.body", "body": body})
            return
        await self._app(scope, receive, send)


def _transport_security(host: str, allowed_hosts: list[str]):
    """Which Host and Origin headers the MCP library accepts. On loopback
    with no public name: the library's own default (loopback names only).
    With public names: those and loopback. On another address with no name
    given the check is off: the key is what stands at the door, and a
    browser page cannot send it."""
    from mcp.server.transport_security import TransportSecuritySettings
    names = [h.strip() for h in allowed_hosts if h.strip()]
    if not names:
        if host in _LOOPBACK:
            return None
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for name in names:
        hosts += [name, f"{name}:*"]
        origins += [f"https://{name}", f"https://{name}:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def check(host: str, behind_proxy: bool) -> str:
    """The key's digest, when every condition for serving holds; raises
    RefusedToServe with what is missing otherwise."""
    digest = stored_digest()
    if not digest:
        raise RefusedToServe(
            "gigamail-server --http needs a key and there is none: without one, anyone who "
            "reaches this address reads the mailbox. Run `gigamail remote key`, keep the key "
            "it prints, then start the server again.")
    if host not in _LOOPBACK and not behind_proxy:
        raise RefusedToServe(
            f"gigamail-server --http speaks plain HTTP and will not listen on {host}: the key "
            "and the mail would cross the network unencrypted. Leave --host at 127.0.0.1 and "
            "put a reverse proxy or a tunnel with TLS in front of it; if TLS is already done "
            "before requests get here (a proxy in another container), say so with --behind-proxy.")
    return digest


def build_app(mcp, host: str, digest: str, allowed_hosts: list[str]):
    app = mcp.streamable_http_app(
        streamable_http_path=PATH, host=host,
        transport_security=_transport_security(host, allowed_hosts))
    return BearerGate(app, digest)


def serve(mcp, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          behind_proxy: bool = False, allowed_hosts: list[str] | None = None) -> None:
    digest = check(host, behind_proxy)
    import uvicorn
    app = build_app(mcp, host, digest, allowed_hosts or [])
    print(f"gigamail-server: MCP over HTTP on http://{host}:{port}{PATH} (key required)",
          file=sys.stderr, flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
