# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""GigaMail Console API — backend HTTP sottile per la UI umana.

Stessi moduli core del server MCP, ZERO endpoint LLM/voce/bulk: nella
versione GigaMail l'intelligenza arriva dall'agente via MCP; questa API
serve solo la console (posta, calendario, identita, mask, audit).

Sicurezza:
- bind SOLO su 127.0.0.1
- se ADE_CONSOLE_TOKEN e' impostato, ogni richiesta deve presentare
  l'header X-ADE-Token con quel valore (Electron genera il token e lo
  inietta nelle finestre); senza variabile, nessun controllo (dev mode)
- porta: ADE_CONSOLE_PORT (default 8002 per compatibilita con la UI)
"""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# Letti all'import: i test fanno importlib.reload(http_api) per far
# rileggere il token dall'ambiente, e il middleware sta qui apposta.
CONSOLE_TOKEN = os.environ.get("ADE_CONSOLE_TOKEN", "")
PORT = int(os.environ.get("ADE_CONSOLE_PORT", "8002"))

app = FastAPI(title="GigaMail Console API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost", "file://", "null"],
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _require_token(request: Request, call_next):
    if CONSOLE_TOKEN and request.method != "OPTIONS":
        if request.headers.get("X-ADE-Token") != CONSOLE_TOKEN:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "token mancante o non valido"}, status_code=401)
    return await call_next(request)


def code_stamp() -> str:
    """The sources' fingerprint (core.code_stamp), kept as a name on this
    module for the health route and for tests that replace it here."""
    from gigamail.core import code_stamp as _mod
    return _mod.code_stamp()


# What this process loaded. The console leaves the backend running when
# its window closes; without this, a backend started before an update
# kept serving the old code to the new console.
_LOADED_STAMP = code_stamp()


def _src_dir() -> str:
    """La cartella da cui gira il codice (quella che contiene gigamail/).
    La console la confronta con la sua: senza, una console avviata da
    sorgente riusava il backend dell'app installata, rimasto acceso."""
    import gigamail
    return str(Path(gigamail.__file__).resolve().parent.parent)


_SRC_DIR = _src_dir()


@app.get("/health")
# async: runs on the event loop, not in the thread pool that the mail
# endpoints share. With Graph answering slowly (seen live: 502s), the sync
# version waited behind them, the console's 1s check timed out, the console
# took the port for free and started a second backend that could not bind.
async def health():
    from gigamail import __version__
    return {"status": "ok", "service": "gigamail-console", "version": __version__,
            "pid": os.getpid(), "stale": code_stamp() != _LOADED_STAMP,
            "src": _SRC_DIR}


@app.get("/console/human")
async def console_human(request: Request):
    """Whether this backend knows the click secret of the console asking.
    A console that finds a backend left running by an earlier launch asks
    this and replaces it when the answer is no: an old backend cannot tell
    the new console's clicks apart, and every send would ask Windows Hello."""
    from .console_click import is_console_click
    return {"known": is_console_click(request.headers)}


# Un router per dominio: stessi path di prima, nessun prefisso.
from . import (  # noqa: E402 — dopo app, per l'ordine di lettura
    accounts,
    addresses,
    agent,
    approvals,
    calendar,
    google,
    mail,
    mask,
    notify,
    rules,
    spam,
    zoom,
)

for _r in (accounts, addresses, mail, calendar, google, mask, agent, approvals, rules, notify, zoom, spam):
    app.include_router(_r.router)

# Nomi che restano raggiungibili dalla facciata (compatibilita').
from .accounts import IMAP_PROVIDERS, ImapAccountRequest  # noqa: E402,F401
from .common import _active_id, _who  # noqa: E402,F401


def main() -> None:
    import uvicorn

    from . import console_click
    # The console that starts this backend passes its click secret in the
    # environment and on stdin. The environment copy is dropped right away.
    da_env = console_click.read_from_env()
    da_stdin = console_click.read_from_stdin()
    console_click.set_secret(da_stdin or da_env)
    # One line in the console's terminal: when Approve or Send still ask
    # Windows Hello, this says why.
    try:
        hello = console_click.send_requires_hello()
    except Exception:
        hello = True
    print(f"[console] click secret: {'received' if console_click.has_secret() else 'NOT received'}"
          f" (env={'yes' if da_env else 'no'}, stdin={'yes' if da_stdin else 'no'});"
          f" Hello also for console clicks: {'on' if hello else 'off'}", flush=True)
    # The watcher is a separate process: after an update or a crash it is
    # gone, or running old code, while its rules are still active. A guard
    # brings it back, now and every minute, not a button someone has to
    # remember.
    from .rules import start_watch_guard
    start_watch_guard()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
