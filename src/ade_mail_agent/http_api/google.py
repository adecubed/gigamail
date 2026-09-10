"""Collegamento Google: login OAuth, identita', scelta del calendario.

Ricalca il flusso Microsoft in accounts.py (/auth/login -> /auth/complete),
con una differenza: Microsoft usa il device flow e mostra un codice, Google
usa il redirect su loopback e non mostra niente. La console apre l'URL e
poi interroga /google/auth/complete finche' non torna un esito.
"""

from fastapi import APIRouter, HTTPException

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import calendar_router, google_auth

router = APIRouter()


@router.get("/google/status")
def google_status():
    """Stato del collegamento Google, per disegnare la scheda in console."""
    identita = core_accounts.list_google_identities()
    return {
        "configured": google_auth.is_configured(),
        "connected": bool(identita),
        "identities": identita,
        "calendar_provider": calendar_router.provider(),
        "scopes": google_auth.SCOPES,
    }


@router.get("/google/auth/login")
def google_login():
    """Avvia il login e ritorna l'URL da aprire nel browser."""
    try:
        data = google_auth.get_login_url()
    except google_auth.NotConfigured as e:
        raise HTTPException(503, str(e)) from e
    return {"auth_url": data["auth_url"]}


@router.post("/google/auth/complete")
def google_complete():
    """Chiude il login. Non blocca: se l'utente non ha ancora autorizzato
    ritorna pending, e la console richiama tra un secondo."""
    try:
        esito = google_auth.complete_login()
    except google_auth.NotConfigured as e:
        raise HTTPException(503, str(e)) from e
    if not esito:
        return {"status": "pending"}
    return {"status": "ok", **esito}


@router.post("/google/auth/logout")
def google_logout(email: str = ""):
    """Revoca il token presso Google e cancella l'identita' locale."""
    ok = google_auth.logout(email or None)
    if not ok:
        raise HTTPException(404, "Nessuna identita Google da scollegare")
    return {"success": True}


@router.post("/google/calendar/primary")
def google_calendar_primary(email: str):
    """Quale account Google serve il calendario, se ce n'e' piu' di uno."""
    core_accounts.set_google_calendar_primary(email)
    return {"success": True}


@router.get("/calendar/provider")
def get_calendar_provider():
    return {"provider": calendar_router.provider()}


@router.post("/calendar/provider/{provider}")
def set_calendar_provider(provider: str):
    """Sposta il calendario tra Microsoft e Google. Scelta esplicita: non
    avviene mai da sola al collegamento di Google."""
    try:
        core_accounts.set_calendar_provider(provider)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"success": True, "provider": calendar_router.provider()}
