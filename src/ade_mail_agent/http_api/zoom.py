"""Collegamento Zoom dalla console: credenziali, verifica, scollegamento.

Le stesse operazioni di `gigamail zoom setup`, ma dove l'utente le cerca:
nella console, accanto a Google. Il Client Secret arriva in POST sul
backend locale, come la password di un account IMAP, e non torna mai
indietro: lo stato dice solo se Zoom e' collegato e con quale Account ID.
"""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import video_call, zoom
from ade_mail_agent.policy import audit

from .common import _who

router = APIRouter()


class ZoomSetupRequest(BaseModel):
    account_id: str
    client_id: str
    client_secret: str


class ZoomLinkRequest(BaseModel):
    url: str = ""


# Un link di riunione Zoom, non un indirizzo qualsiasi: finisce in una mail
# a un cliente, e un indirizzo altrui spedito per errore non si richiama.
_LINK_ZOOM = re.compile(
    r"^https://[a-z0-9.-]*zoom\.us/(j/\d+|my/[a-z0-9._-]+)(\?\S*)?$",
    re.IGNORECASE)


def _mascherato(valore: str) -> str:
    testo = str(valore or "")
    return ("…" + testo[-4:]) if len(testo) > 4 else ("…" if testo else "")


@router.get("/zoom/status")
def zoom_status():
    """Per disegnare la scheda: nessun segreto, e il Client ID solo in coda."""
    cfg = zoom.config()
    return {
        "configured": cfg is not None,
        "account_id": cfg["account_id"] if cfg else "",
        "client_id": _mascherato(cfg["client_id"]) if cfg else "",
        "link": video_call.link_fisso(),
    }


@router.post("/zoom/link")
def zoom_link(req: ZoomLinkRequest):
    """Il link personale: l'alternativa all'app Server-to-Server per chi
    vuole un solo link, sempre quello. Una stringa vuota lo toglie."""
    url = (req.url or "").strip()
    if url and not _LINK_ZOOM.match(url):
        raise HTTPException(
            400, "Non sembra un link di riunione Zoom (https://.../j/... o /my/...)")
    core_accounts.set_setting("zoom_link_fisso", url)
    audit("zoom", {"link": bool(url)},
          "zoom_link_saved" if url else "zoom_link_removed", detail=_who())
    return {"success": True, "link": url}


@router.post("/zoom/setup")
def zoom_setup(req: ZoomSetupRequest):
    """Salva e verifica subito con Zoom. Credenziali rifiutate non restano
    salvate: si torna a quelle di prima, o a nessuna. Altrimenti la scheda
    direbbe "collegato" e il primo cliente scoprirebbe che non lo e'."""
    account_id = (req.account_id or "").strip()
    client_id = (req.client_id or "").strip()
    segreto = (req.client_secret or "").strip()
    if not (account_id and client_id and segreto):
        raise HTTPException(400, "Account ID, Client ID e Client Secret sono obbligatori")
    precedente = zoom.config()
    zoom.salva_config(account_id, client_id, segreto)
    try:
        email = zoom.verifica()
    except Exception as e:
        if precedente:
            zoom.salva_config(precedente["account_id"], precedente["client_id"],
                              precedente["client_secret"])
        else:
            zoom.rimuovi_config()
        raise HTTPException(400, f"Zoom rifiuta le credenziali: {e}") from e
    audit("zoom", {"zoom_account": account_id}, "zoom_configured", detail=_who())
    return {"success": True, "email": email}


@router.post("/zoom/test")
def zoom_test():
    if not zoom.configurato():
        raise HTTPException(404, "Zoom non collegato")
    try:
        return {"success": True, "email": zoom.verifica()}
    except Exception as e:
        raise HTTPException(502, f"Zoom non risponde come dovrebbe: {e}") from e


@router.post("/zoom/remove")
def zoom_remove():
    zoom.rimuovi_config()
    audit("zoom", {}, "zoom_removed", detail=_who())
    return {"success": True}
