"""Account (lista, attivo, IMAP con verifica), identita' e file di conoscenza, login Microsoft."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import auth as core_auth
from ade_mail_agent.core import (
    identity_reader,
)

router = APIRouter()


# ── ACCOUNT ──────────────────────────────────────────────────────────

@router.get("/accounts")
def list_accounts():
    out = []
    for a in core_accounts.get_accounts():
        out.append({k: a.get(k) for k in ("id", "name", "email", "type", "active")})
    return out


@router.get("/accounts/active")
def get_active():
    a = core_accounts.get_active_account()
    if not a:
        return {}
    return {k: a.get(k) for k in ("id", "name", "email", "type", "active")}


@router.post("/accounts/active/{account_id}")
def set_active(account_id: int):
    core_accounts.set_active_account(account_id)
    return {"success": True}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    core_accounts.delete_account(account_id)
    return {"success": True}


# Provider IMAP noti: la console manda la chiave, qui si risolvono gli host.
# Outlook/Microsoft 365 via IMAP usa SMTP 587 + STARTTLS (send_message lo
# gestisce: 465 = SSL implicito, altro = STARTTLS).
IMAP_PROVIDERS = {
    "aruba":   {"name": "Aruba", "imap_host": "imaps.aruba.it", "imap_port": 993,
                "smtp_host": "smtps.aruba.it", "smtp_port": 465},
    "gmail":   {"name": "Gmail", "imap_host": "imap.gmail.com", "imap_port": 993,
                "smtp_host": "smtp.gmail.com", "smtp_port": 465},
    "outlook": {"name": "Outlook / Microsoft 365", "imap_host": "outlook.office365.com",
                "imap_port": 993, "smtp_host": "smtp.office365.com", "smtp_port": 587},
    "libero":  {"name": "Libero", "imap_host": "imapmail.libero.it", "imap_port": 993,
                "smtp_host": "smtp.libero.it", "smtp_port": 465},
}


@router.get("/accounts/providers")
def imap_providers():
    out = [{"key": k, **v} for k, v in IMAP_PROVIDERS.items()]
    out.append({"key": "custom", "name": "Altro (manuale)", "imap_host": "",
                "imap_port": 993, "smtp_host": "", "smtp_port": 465})
    return out


class ImapAccountRequest(BaseModel):
    name: str
    email: str
    password: str
    provider: Optional[str] = None      # chiave di IMAP_PROVIDERS, oppure "custom"
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None


def _resolve_imap_hosts(req: ImapAccountRequest) -> dict:
    """Host espliciti vincono; altrimenti vengono dal provider. Un provider
    sconosciuto o un 'custom' senza host e' un errore dell'utente (400),
    non un account salvato a meta'."""
    base = dict(IMAP_PROVIDERS.get((req.provider or "").lower(), {}))
    if req.provider and not base and req.provider.lower() != "custom":
        raise HTTPException(400, f"provider sconosciuto: {req.provider}")
    hosts = {
        "imap_host": (req.imap_host or base.get("imap_host") or "").strip(),
        "imap_port": int(req.imap_port or base.get("imap_port") or 993),
        "smtp_host": (req.smtp_host or base.get("smtp_host") or "").strip(),
        "smtp_port": int(req.smtp_port or base.get("smtp_port") or 465),
    }
    if not hosts["imap_host"] or not hosts["smtp_host"]:
        raise HTTPException(400, "host IMAP e SMTP obbligatori (o scegli un provider)")
    return hosts


def _verify_imap_login(host: str, port: int, email: str, password: str) -> None:
    """Prova il login IMAP prima di salvare: una password sbagliata deve
    fallire qui, nell'onboarding, non alla prima sincronizzazione."""
    from ade_mail_agent.core import imap_client
    try:
        conn = imap_client._connect(host, port, email, password)
    except Exception as e:
        msg = str(e) or e.__class__.__name__
        low = msg.lower()
        if "authenticat" in low or "login" in low or "credential" in low or "password" in low:
            raise HTTPException(400, f"login rifiutato da {host}: controlla email e password "
                                     f"(Gmail/Outlook richiedono una password per le app)") from e
        raise HTTPException(400, f"impossibile raggiungere {host}:{port}: {msg}") from e
    try:
        conn.logout()
    except Exception:
        pass


@router.post("/accounts/imap")
def add_imap(req: ImapAccountRequest):
    name = (req.name or "").strip()
    email = (req.email or "").strip()
    if not name or not email or not req.password:
        raise HTTPException(400, "nome, email e password obbligatori")
    hosts = _resolve_imap_hosts(req)
    _verify_imap_login(hosts["imap_host"], hosts["imap_port"], email, req.password)
    acc_id = core_accounts.add_imap_account(name, email, req.password, **hosts)
    # Il primo account diventa attivo: senza, la console resta senza
    # selezione finche' l'utente non ne sceglie uno a mano.
    if len(core_accounts.get_accounts()) == 1:
        core_accounts.set_active_account(acc_id)
    return {"success": True, "account_id": acc_id}


# ── IDENTITA + FILE DI CONOSCENZA ────────────────────────────────────

@router.get("/accounts/{account_id}/identity")
def get_identity(account_id: int):
    return core_accounts.get_identity(account_id)


class IdentityRequest(BaseModel):
    who_am_i: str = ""
    what_i_do: str = ""
    tone: str = ""
    key_info: str = ""
    file_paths: Optional[List[str]] = None


@router.post("/accounts/{account_id}/identity")
def set_identity(account_id: int, req: IdentityRequest):
    return core_accounts.set_identity(
        account_id, who_am_i=req.who_am_i, what_i_do=req.what_i_do,
        tone=req.tone, key_info=req.key_info, file_paths=req.file_paths or [],
    )


@router.get("/accounts/{account_id}/identity/files")
def identity_files(account_id: int):
    ident = core_accounts.get_identity(account_id)
    return identity_reader.list_all_files(ident.get("file_paths") or [])


# ── AUTH MICROSOFT (device flow: la console e' l'umano) ─────────────

_login_flow: dict = {}


@router.get("/auth/status")
def auth_status():
    return {"logged_in": core_auth.is_logged_in()}


@router.get("/auth/login")
def auth_login():
    global _login_flow
    data = core_auth.get_login_url()
    _login_flow = data["flow"]
    return {"verification_uri": data["verification_uri"], "user_code": data["user_code"]}


@router.post("/auth/complete")
def auth_complete():
    global _login_flow
    if not _login_flow:
        raise HTTPException(400, "Nessun login flow attivo")
    result = core_auth.complete_login(_login_flow)
    _login_flow = {}
    if result:
        # usa token e claims dell'account APPENA loggato (multi-account safe)
        claims = result.get("id_token_claims", {}) if isinstance(result, dict) else {}
        import requests as _rq
        me = _rq.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {result['access_token']}"}, timeout=15,
        ).json()
        email_addr = (me.get("mail") or me.get("userPrincipalName")
                      or claims.get("preferred_username") or "microsoft_user")
        name = me.get("displayName") or claims.get("name") or "Account Microsoft"
        with open(core_auth.TOKEN_PATH, "r", encoding="utf-8") as f:
            token_cache = f.read()
        acc_id = core_accounts.add_microsoft_account(name, email_addr, token_cache)
        core_accounts.set_active_account(acc_id)
    return {"success": bool(result)}


@router.post("/auth/logout")
def auth_logout():
    core_auth.logout()
    return {"success": True}
