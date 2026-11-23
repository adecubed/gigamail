"""gigamail-server --http: the MCP server reached from another computer.
Reading is free to whoever reaches it, so it serves only with a key, on
loopback unless told that TLS is done in front of it."""
import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import time

import pytest
import requests

from gigamail import remote_http


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_ROOT", str(tmp_path / "ade"))
    return tmp_path / "ade"


def test_only_the_fingerprint_of_the_key_is_kept(data_root):
    assert remote_http.stored_digest() == ""
    key = remote_http.new_key()
    assert len(key) >= 43
    text = remote_http.key_file().read_text(encoding="ascii")
    assert key not in text
    assert text.strip() == hashlib.sha256(key.encode()).hexdigest()
    if sys.platform != "win32":
        assert remote_http.key_file().stat().st_mode & 0o777 == 0o600
    digest = remote_http.stored_digest()
    assert remote_http.key_matches(key, digest)
    assert not remote_http.key_matches(key + "x", digest)
    assert not remote_http.key_matches("", digest)
    assert not remote_http.key_matches(key, "")


def test_a_new_key_replaces_the_old_one(data_root):
    old = remote_http.new_key()
    new = remote_http.new_key()
    digest = remote_http.stored_digest()
    assert remote_http.key_matches(new, digest)
    assert not remote_http.key_matches(old, digest)


def test_a_damaged_key_file_is_no_key(data_root):
    data_root.mkdir()
    remote_http.key_file().write_text("not a digest\n", encoding="ascii")
    assert remote_http.stored_digest() == ""
    with pytest.raises(remote_http.RefusedToServe):
        remote_http.check("127.0.0.1", False)


def test_no_key_no_server(data_root):
    with pytest.raises(remote_http.RefusedToServe, match="gigamail remote key"):
        remote_http.check("127.0.0.1", False)


def test_plain_http_stays_on_loopback_unless_tls_is_in_front(data_root):
    remote_http.new_key()
    for host in ("127.0.0.1", "localhost", "::1"):
        assert remote_http.check(host, False) == remote_http.stored_digest()
    for host in ("0.0.0.0", "203.0.113.7", "::"):
        with pytest.raises(remote_http.RefusedToServe, match="plain HTTP"):
            remote_http.check(host, False)
        assert remote_http.check(host, True)


def _call(gate, headers):
    sent, reached = [], []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    async def send(message):
        sent.append(message)

    asyncio.run(gate_call(gate, inner, {"type": "http", "headers": headers}, send))
    return sent, reached


async def gate_call(gate_cls, inner, scope, send):
    await gate_cls(inner)(scope, None, send)


def test_the_gate_answers_401_and_the_server_is_never_reached(data_root):
    key = remote_http.new_key()
    digest = remote_http.stored_digest()

    def gate(inner):
        return remote_http.BearerGate(inner, digest)

    for headers in ([], [(b"authorization", b"Bearer wrong")], [(b"authorization", key.encode())],
                    [(b"authorization", b"Basic " + key.encode())], [(b"x-key", key.encode())]):
        sent, reached = _call(gate, headers)
        assert reached == []
        assert sent[0]["status"] == 401
        assert (b"www-authenticate", b"Bearer") in sent[0]["headers"]
        assert json.loads(sent[1]["body"]) == {"error": "unauthorized"}
    for headers in ([(b"authorization", b"Bearer " + key.encode())],
                    [(b"authorization", b"bearer  " + key.encode() + b" ")]):
        sent, reached = _call(gate, headers)
        assert reached == ["http"] and sent == []


def test_the_gate_lets_the_servers_own_lifespan_through(data_root):
    remote_http.new_key()
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    asyncio.run(remote_http.BearerGate(inner, remote_http.stored_digest())({"type": "lifespan"}, None, None))
    assert reached == ["lifespan"]
    with pytest.raises(remote_http.RefusedToServe):
        remote_http.BearerGate(inner, "")


def test_the_gate_stops_what_is_neither_http_nor_lifespan(data_root):
    key = remote_http.new_key()
    reached, sent = [], []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    async def send(message):
        sent.append(message)

    gate = remote_http.BearerGate(inner, remote_http.stored_digest())
    headers = [(b"authorization", b"Bearer " + key.encode())]
    asyncio.run(gate({"type": "websocket", "headers": headers}, None, send))
    asyncio.run(gate({"type": "something-new", "headers": headers}, None, send))
    assert reached == []
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_host_names_the_server_answers_to():
    assert remote_http._transport_security("127.0.0.1", []) is None  # the library's loopback default
    off = remote_http._transport_security("0.0.0.0", [])
    assert off.enable_dns_rebinding_protection is False
    named = remote_http._transport_security("127.0.0.1", ["mail.example.com"])
    assert named.enable_dns_rebinding_protection is True
    assert "mail.example.com" in named.allowed_hosts and "127.0.0.1:*" in named.allowed_hosts
    assert "https://mail.example.com" in named.allowed_origins


def test_server_without_options_is_stdio_as_before(data_root, monkeypatch):
    from gigamail import server
    ran = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: ran.append((a, k)))
    monkeypatch.setattr(server, "_announce_update", lambda: None)
    server.main([])
    # whatever a client puts on the command line, as before there were options
    server.main(["--something", "else", "-p", "x"])
    assert ran == [((), {}), ((), {})]
    with pytest.raises(SystemExit):
        server.main(["--http", "--htpp-typo"])


def test_server_refuses_http_without_a_key_before_doing_anything(data_root, monkeypatch, capsys):
    from gigamail import server
    monkeypatch.setattr(server, "_announce_update", lambda: pytest.fail("ran before the refusal"))
    with pytest.raises(SystemExit) as stop:
        server.main(["--http"])
    assert stop.value.code == 2
    assert "gigamail remote key" in capsys.readouterr().err


def test_cli_shows_the_key_once(data_root, capsys):
    from gigamail import cli
    assert cli.main(["remote", "key"]) == 0
    key = capsys.readouterr().out.splitlines()[0]
    assert remote_http.key_matches(key, remote_http.stored_digest())


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _first_message(response):
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return response.json()


def test_live_server_serves_the_tools_only_to_the_key(data_root):
    """The real server in its own process, reached over HTTP as Codex or
    Claude Code would: no key, a wrong key and another Host get nothing;
    the key gets the handshake and the tool list."""
    key = remote_http.new_key()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, GIGAMAIL_ROOT=str(data_root), GIGAMAIL_OS_KEYRING="0")
    proc = subprocess.Popen(
        [sys.executable, "-m", "gigamail.server", "--http", "--port", str(port),
         "--allowed-host", "mail.example.com"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}/mcp"
    http = requests.Session()
    http.trust_env = False  # never through a proxy of whoever runs the tests
    try:
        for _ in range(120):
            try:
                if http.post(url, json=INIT, headers=HEADERS, timeout=2).status_code == 401:
                    break
            except requests.ConnectionError:
                if proc.poll() is not None:
                    pytest.fail("server stopped: " + proc.stderr.read().decode(errors="replace"))
                time.sleep(0.25)
        else:
            pytest.fail("server did not start")
        assert http.get(url, headers=HEADERS, timeout=5).status_code == 401
        wrong = dict(HEADERS, Authorization="Bearer " + key[:-1] + ("A" if key[-1] != "A" else "B"))
        assert http.post(url, json=INIT, headers=wrong, timeout=5).status_code == 401
        auth = dict(HEADERS, Authorization=f"Bearer {key}")
        foreign = http.post(url, json=INIT, headers=dict(auth, Host="other.example.com"), timeout=5)
        assert foreign.status_code == 421
        named = http.post(url, json=INIT, headers=dict(auth, Host="mail.example.com"), timeout=10)
        assert named.status_code == 200
        r = http.post(url, json=INIT, headers=auth, timeout=10)
        assert r.status_code == 200
        assert _first_message(r)["result"]["serverInfo"]["name"] == "gigamail"
        session = dict(auth, **{"Mcp-Session-Id": r.headers["mcp-session-id"],
                                "MCP-Protocol-Version": "2025-06-18"})
        http.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                  headers=session, timeout=10)
        tools = http.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                          headers=session, timeout=20)
        names = {t["name"] for t in _first_message(tools)["result"]["tools"]}
        assert {"list_accounts", "send_mail"} <= names
        # the session id alone, without the key, opens nothing
        stolen = {k: v for k, v in session.items() if k != "Authorization"}
        assert http.post(url, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                         headers=stolen, timeout=5).status_code == 401
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
