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


@app.get("/health")
def health():
    from ade_mail_agent import __version__
    return {"status": "ok", "service": "gigamail-console", "version": __version__}


# Un router per dominio: stessi path di prima, nessun prefisso.
from . import (  # noqa: E402 — dopo app, per l'ordine di lettura
    accounts,
    addresses,
    agent,
    approvals,
    calendar,
    mail,
    mask,
    notify,
    rules,
)

for _r in (accounts, addresses, mail, calendar, mask, agent, approvals, rules, notify):
    app.include_router(_r.router)

# Nomi che restano raggiungibili dalla facciata (compatibilita').
from .accounts import IMAP_PROVIDERS, ImapAccountRequest  # noqa: E402,F401
from .common import _active_id, _who  # noqa: E402,F401


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
