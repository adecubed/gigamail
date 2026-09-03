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
import json
import os
import sqlite3
import threading
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import (
    ade_masker,
    availability,
    identity_reader,
    mail_memory,
    mail_router,
    ms_calendar,
    observer,
)
from ade_mail_agent.core import auth as core_auth

CONSOLE_TOKEN = os.environ.get("ADE_CONSOLE_TOKEN", "")
PORT = int(os.environ.get("ADE_CONSOLE_PORT", "8002"))

from ade_mail_agent.core.data_paths import data_root as _data_root  # noqa: E402

_ADE_MAIL_DIR = str(_data_root())
ADDR_DB = os.path.join(_ADE_MAIL_DIR, ".addresses.db")

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


def _active_id() -> Optional[int]:
    a = core_accounts.get_active_account()
    return a["id"] if a else None


# ── RUBRICA ──────────────────────────────────────────────────────────

def _init_addr_db():
    with sqlite3.connect(ADDR_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS addresses (
                email TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                count INTEGER DEFAULT 0,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _save_address(email_addr: str, name: str = "") -> None:
    email_addr = (email_addr or "").strip().lower()
    if not email_addr or "@" not in email_addr:
        return
    with sqlite3.connect(ADDR_DB) as conn:
        conn.execute("""
            INSERT INTO addresses (email, name, count, last_used)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE addresses.name END,
                count = addresses.count + 1,
                last_used = CURRENT_TIMESTAMP
        """, (email_addr, name or ""))


def _remember_message_addresses(messages) -> None:
    if not isinstance(messages, list):
        return
    for msg in messages:
        try:
            addr = ((msg or {}).get("from") or {}).get("emailAddress") or {}
            _save_address(addr.get("address") or "", addr.get("name") or "")
        except Exception:
            pass


_init_addr_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "gigamail-console"}


# ── ACCOUNT ──────────────────────────────────────────────────────────

@app.get("/accounts")
def list_accounts():
    out = []
    for a in core_accounts.get_accounts():
        out.append({k: a.get(k) for k in ("id", "name", "email", "type", "active")})
    return out


@app.get("/accounts/active")
def get_active():
    a = core_accounts.get_active_account()
    if not a:
        return {}
    return {k: a.get(k) for k in ("id", "name", "email", "type", "active")}


@app.post("/accounts/active/{account_id}")
def set_active(account_id: int):
    core_accounts.set_active_account(account_id)
    return {"success": True}


@app.delete("/accounts/{account_id}")
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


@app.get("/accounts/providers")
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


@app.post("/accounts/imap")
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

@app.get("/accounts/{account_id}/identity")
def get_identity(account_id: int):
    return core_accounts.get_identity(account_id)


class IdentityRequest(BaseModel):
    who_am_i: str = ""
    what_i_do: str = ""
    tone: str = ""
    key_info: str = ""
    file_paths: Optional[List[str]] = None


@app.post("/accounts/{account_id}/identity")
def set_identity(account_id: int, req: IdentityRequest):
    return core_accounts.set_identity(
        account_id, who_am_i=req.who_am_i, what_i_do=req.what_i_do,
        tone=req.tone, key_info=req.key_info, file_paths=req.file_paths or [],
    )


@app.get("/accounts/{account_id}/identity/files")
def identity_files(account_id: int):
    ident = core_accounts.get_identity(account_id)
    return identity_reader.list_all_files(ident.get("file_paths") or [])


# ── AUTH MICROSOFT (device flow: la console e' l'umano) ─────────────

_login_flow: dict = {}


@app.get("/auth/status")
def auth_status():
    return {"logged_in": core_auth.is_logged_in()}


@app.get("/auth/login")
def auth_login():
    global _login_flow
    data = core_auth.get_login_url()
    _login_flow = data["flow"]
    return {"verification_uri": data["verification_uri"], "user_code": data["user_code"]}


@app.post("/auth/complete")
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


@app.post("/auth/logout")
def auth_logout():
    core_auth.logout()
    return {"success": True}


# ── RUBRICA / AUTOCOMPLETE ───────────────────────────────────────────

@app.get("/addresses")
def get_addresses(q: str = ""):
    with sqlite3.connect(ADDR_DB) as conn:
        conn.row_factory = sqlite3.Row
        if q:
            like = f"%{q.strip()}%"
            rows = conn.execute(
                "SELECT email, name, count FROM addresses "
                "WHERE email LIKE ? OR name LIKE ? "
                "ORDER BY count DESC, last_used DESC LIMIT 12",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT email, name, count FROM addresses "
                "ORDER BY count DESC, last_used DESC LIMIT 20"
            ).fetchall()
        return [dict(r) for r in rows]


@app.get("/addresses/search")
def search_addresses(q: str = "", account_id: Optional[int] = None):
    q = (q or "").strip()
    if not q:
        return []
    local = get_addresses(q)
    if len(local) >= 5:
        return local
    try:
        aid = account_id or _active_id()
        seen = {r["email"] for r in local}
        for msg in (mail_router.search_messages(aid, query=q, top=30) or []):
            addr = ((msg or {}).get("from") or {}).get("emailAddress") or {}
            email_addr = str(addr.get("address") or "").strip().lower()
            name = str(addr.get("name") or "").strip()
            if email_addr and email_addr not in seen and (
                q.lower() in email_addr or q.lower() in name.lower()
            ):
                seen.add(email_addr)
                local.append({"email": email_addr, "name": name, "count": 0})
                _save_address(email_addr, name)
    except Exception:
        pass
    return local[:12]


# ── MAIL: LETTURA ────────────────────────────────────────────────────

@app.get("/mail")
def list_mail(top: int = 20, skip: int = 0, account_id: Optional[int] = None):
    aid = account_id or _active_id()
    result = mail_router.get_messages(aid, top=top, skip=skip)
    _remember_message_addresses(result)
    return result


@app.get("/mail/sent")
def list_sent(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="sent", top=top)


@app.get("/mail/spam")
def list_spam(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="spam", top=top)


@app.get("/mail/deleted")
def list_deleted(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="deleted", top=top)


@app.get("/mail/drafts")
def list_drafts(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="drafts", top=top)


@app.get("/mail/folder/{folder_id}")
def list_folder(folder_id: str, top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder=folder_id, top=top)


@app.get("/mail/unread")
def unread(top: int = 20, days: int = 5, folder: Optional[str] = None,
           account_id: Optional[int] = None):
    return mail_router.get_unread_messages(
        account_id or _active_id(), folder=folder or "inbox", top=top, days=days
    )


@app.get("/mail/unread_count")
def unread_count(account_id: Optional[int] = None):
    msgs = mail_router.get_unread_messages(account_id or _active_id(), top=99)
    return {"count": len(msgs)}


@app.get("/mail/folders")
def folders(account_id: Optional[int] = None):
    return mail_router.list_folders(account_id or _active_id())


class FolderRequest(BaseModel):
    name: str
    account_id: Optional[int] = None


@app.post("/mail/folders")
def create_folder(req: FolderRequest):
    return mail_router.create_folder(req.account_id or _active_id(), name=req.name)


@app.delete("/mail/folders/{folder_id}")
def delete_folder(folder_id: str, account_id: Optional[int] = None):
    return {"success": mail_router.delete_folder(account_id or _active_id(), folder_id=folder_id)}


@app.get("/mail/search/{query}")
def search(query: str, top: int = 10, account_id: Optional[int] = None):
    return mail_router.search_messages(account_id or _active_id(), query=query, top=top)


@app.get("/mail/sender_history")
def sender_history(email: str, account_id: Optional[int] = None):
    profile = mail_memory.get_sender_profile(email) or {}
    return {"profile": profile}


# ── MAIL MEMORY (indice locale) ──────────────────────────────────────

@app.get("/mail/memory/stats")
def memory_stats():
    return mail_memory.get_stats()


@app.get("/mail/memory/sender/{email}")
def memory_sender(email: str):
    return mail_memory.get_sender_profile(email) or {}


@app.get("/mail/memory/indexer_state")
def indexer_state(account_id: Optional[int] = None):
    aid = account_id or _active_id()
    return mail_memory.get_indexer_state(aid) if aid else {}


@app.post("/mail/memory/index")
def start_index(account_id: Optional[int] = None):
    aid = account_id or _active_id()
    if not aid:
        raise HTTPException(400, "Nessun account")
    threading.Thread(
        target=lambda: mail_memory.run_indexer(aid, mail_router),
        daemon=True, name=f"console-index-{aid}",
    ).start()
    return {"started": True, "account_id": aid}


# ── MAIL: AZIONI ─────────────────────────────────────────────────────

class SendRequest(BaseModel):
    to: str
    subject: str = ""
    body: str = ""
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    attachments: Optional[List[str]] = None
    reply_to_id: Optional[str] = None
    account_id: Optional[int] = None


@app.post("/mail/send")
def send_mail(req: SendRequest):
    result = mail_router.send_message(
        req.account_id or _active_id(),
        to=req.to, subject=req.subject, body=req.body,
        reply_to_id=req.reply_to_id, attachments=req.attachments,
        cc=req.cc, bcc=req.bcc,
    )
    _save_address(req.to)
    return result


@app.get("/mail/{message_id}")
def read_message(message_id: str, folder: str = "", account_id: Optional[int] = None):
    return mail_router.get_message(
        account_id or _active_id(), message_id=message_id, folder=folder
    )


@app.delete("/mail/{message_id}")
def delete_message(message_id: str, folder: str = "", account_id: Optional[int] = None):
    return {"success": mail_router.delete_message(
        account_id or _active_id(), message_id=message_id, folder=folder or None
    )}


@app.post("/mail/{message_id}/read")
def mark_read(message_id: str, folder: str = "inbox", account_id: Optional[int] = None):
    return {"success": mail_router.set_read_status(
        account_id or _active_id(), message_id=message_id, folder=folder, is_read=True
    )}


@app.post("/mail/{message_id}/unread")
def mark_unread(message_id: str, folder: str = "inbox", account_id: Optional[int] = None):
    return {"success": mail_router.set_read_status(
        account_id or _active_id(), message_id=message_id, folder=folder, is_read=False
    )}


@app.post("/mail/{message_id}/move")
def move_message(message_id: str, folder_id: str, source_folder: str = "",
                 account_id: Optional[int] = None):
    return {"success": mail_router.move_to_folder(
        account_id or _active_id(), message_id=message_id,
        folder_id=folder_id, source_folder=source_folder or None,
    )}


@app.post("/mail/{message_id}/spam")
def mark_spam(message_id: str, folder: str = "inbox", account_id: Optional[int] = None):
    return {"success": mail_router.move_to_folder(
        account_id or _active_id(), message_id=message_id,
        folder_id="spam", source_folder=folder,
    )}


@app.post("/mail/{message_id}/not_spam")
def not_spam(message_id: str, account_id: Optional[int] = None):
    return {"success": mail_router.move_to_folder(
        account_id or _active_id(), message_id=message_id,
        folder_id="inbox", source_folder="spam",
    )}


# ── CALENDARIO (Microsoft Graph; CalDAV in arrivo) ───────────────────

@app.get("/calendar")
def calendar(days_ahead: int = 7, days_back: int = 0):
    return ms_calendar.get_events(days_ahead=days_ahead, days_back=days_back)


@app.get("/calendar/today")
def calendar_today():
    return ms_calendar.get_events(days_ahead=1, days_back=0)


@app.get("/calendar/free_slots")
def calendar_free_slots(days_ahead: int = 7, duration_minutes: int = 60,
                        max_slots: int = 4):
    events = ms_calendar.get_events(days_ahead=days_ahead + 1)
    slots = availability.find_free_slots(
        events, days_ahead=days_ahead,
        duration_minutes=duration_minutes, max_slots=max_slots,
    )
    return {"count": len(slots), "slots": slots}


class EventRequest(BaseModel):
    subject: str
    start: str
    end: str
    body: str = ""
    location: str = ""


@app.post("/calendar")
def create_event(req: EventRequest):
    return ms_calendar.create_event(
        req.subject, req.start, req.end, body=req.body, location=req.location
    )


@app.patch("/calendar/{event_id}")
def update_event(event_id: str, req: dict):
    return ms_calendar.update_event(event_id, **(req or {}))


@app.delete("/calendar/{event_id}")
def delete_event(event_id: str):
    return {"success": ms_calendar.delete_event(event_id)}


@app.get("/calendar/primary")
def calendar_primary():
    return {"account_id": core_accounts.get_calendar_primary()}


@app.post("/calendar/primary/{account_id}")
def set_calendar_primary(account_id: int):
    core_accounts.set_calendar_primary(account_id)
    return {"success": True}


# ── MASK (privacy, non-LLM) ──────────────────────────────────────────

class MaskDetectRequest(BaseModel):
    text: str
    account_id: Optional[int] = None


@app.post("/mask/detect")
def mask_detect(req: MaskDetectRequest):
    user_masks = ade_masker.get_user_masks(req.account_id or _active_id() or 0)
    return {"entities": ade_masker.detect(req.text, user_masks=user_masks)}


class MaskRequest(BaseModel):
    text: str
    selected_values: Optional[List[str]] = None
    account_id: Optional[int] = None


@app.post("/mask")
def mask_text(req: MaskRequest):
    masked, mapping = ade_masker.mask(req.text, selected_values=req.selected_values)
    return {"masked_text": masked, "mapping": mapping}


class UnmaskRequest(BaseModel):
    masked_text: str
    mapping: dict


@app.post("/unmask")
def unmask_text(req: UnmaskRequest):
    return {"text": ade_masker.unmask(req.masked_text, req.mapping)}


@app.get("/mask/suggest")
def mask_suggest(selection: str):
    return {"type": ade_masker.suggest_type(selection)}


@app.get("/masks")
def get_masks(account_id: Optional[int] = None):
    return ade_masker.get_user_masks(account_id or _active_id() or 0)


class UserMaskRequest(BaseModel):
    value: str
    label_type: str = "MASK"
    account_id: Optional[int] = None


@app.post("/masks")
def add_mask(req: UserMaskRequest):
    return ade_masker.add_user_mask(
        req.account_id or _active_id() or 0, req.value, label_type=req.label_type
    )


@app.delete("/masks/{mask_id}")
def delete_mask(mask_id: int, account_id: Optional[int] = None):
    return {"success": ade_masker.delete_user_mask(
        account_id or _active_id() or 0, mask_id
    )}


# ── AGENTE (cio' che prima faceva l'LLM interno ora lo fa l'agente) ──

def _identity_context(aid: Optional[int]) -> str:
    if not aid:
        return ""
    ident = core_accounts.get_identity(aid)
    parts = []
    if ident.get("who_am_i"):
        parts.append(f"Chi sono: {ident['who_am_i']}")
    if ident.get("what_i_do"):
        parts.append(f"Cosa faccio: {ident['what_i_do']}")
    if ident.get("tone"):
        parts.append(f"Tono richiesto: {ident['tone']}")
    if ident.get("key_info"):
        parts.append(f"Info chiave: {ident['key_info']}")
    return "\n".join(parts)


def _run_agent(prompt: str) -> dict:
    try:
        return {"draft": agent_bridge.run(prompt), "engine": "agent"}
    except agent_bridge.AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e


_APPUNTAMENTO_KW = (
    "appuntament", "visita", "visitare", "vedere l", "sopralluogo", "incontr",
    "disponibil", "quando poss", "fissare", "calendario", "vederci",
)


def _slots_context(text: str, max_slots: int = 3) -> str:
    """Se il testo parla di appuntamenti, calcola gli slot liberi e li mette
    nel prompt: l'agente propone orari VERI, non inventati."""
    low = (text or "").lower()
    if not any(k in low for k in _APPUNTAMENTO_KW):
        return ""
    try:
        events = ms_calendar.get_events(days_ahead=8)
        slots = availability.find_free_slots(events, days_ahead=7,
                                             max_slots=max_slots)
    except Exception:
        return ""
    if not slots:
        return ""
    righe = "; ".join(s["label"] for s in slots)
    return ("\nDISPONIBILITA' REALE dal calendario (proponi SOLO questi "
            f"orari, senza inventarne altri): {righe}")


def _suggest_attachments(aid: Optional[int], text: str) -> list:
    """Propone allegati dai file di conoscenza dell'account in base al testo
    dell'istruzione/oggetto (es. 'manda la planimetria A.2.1'). La UI mostra
    i suggerimenti con checkbox: decide sempre l'utente."""
    if not aid or not (text or "").strip():
        return []
    try:
        ident = core_accounts.get_identity(aid)
        paths = ident.get("file_paths") or []
        if not paths:
            return []
        hits = identity_reader.find_relevant_files(paths, text, max_files=5)
        return [{"name": h["name"], "path": h["path"]} for h in hits]
    except Exception:
        return []


@app.get("/agent/status")
def agent_status():
    return agent_bridge.status()


class GenerateDraftRequest(BaseModel):
    instruction: str
    to: str = ""
    subject: str = ""


@app.post("/mail/generate_draft")
def generate_draft(req: GenerateDraftRequest, account_id: Optional[int] = None):
    aid = account_id or _active_id()
    prompt = (
        "Scrivi il TESTO di una email in italiano (solo il corpo, niente oggetto, "
        "nessun commento) seguendo l'istruzione dell'utente.\n"
        f"{_identity_context(aid)}\n"
        f"Destinatario: {req.to or 'non specificato'}\n"
        f"Oggetto: {req.subject or 'non specificato'}\n"
        f"{_slots_context(req.instruction + ' ' + req.subject)}\n"
        f"Istruzione: {req.instruction}"
    )
    out = _run_agent(prompt)
    # Gli allegati seguono ciò che l'agente ha SCRITTO (può aver cambiato
    # riferimento: es. immobile richiesto non disponibile -> ne propone un
    # altro), non solo l'istruzione iniziale.
    out["suggested_attachments"] = _suggest_attachments(
        aid, f"{out.get('draft', '')} {req.instruction} {req.subject}"
    )
    return out


class SmartDraftRequest(BaseModel):
    instruction: str = ""
    body_text: str = ""
    subject: str = ""
    sender: str = ""


@app.post("/mail/{message_id}/smart_draft")
def smart_draft(message_id: str, req: SmartDraftRequest,
                account_id: Optional[int] = None, folder: str = ""):
    aid = account_id or _active_id()
    body = req.body_text
    if not body:
        try:
            msg = mail_router.get_message(aid, message_id=message_id, folder=folder) or {}
            body = (msg.get("body", {}) or {}).get("content") or msg.get("bodyPreview") or ""
            req.subject = req.subject or msg.get("subject") or ""
        except Exception:
            pass
    obs = ""
    try:
        obs = observer.get_context_for_prompt(aid or 0, sender=req.sender, subject=req.subject)
    except Exception:
        pass
    prompt = (
        "Scrivi la RISPOSTA a questa email in italiano (solo il corpo, nessun "
        "commento). Rispetta il tono e le correzioni abituali dell'utente.\n"
        f"{_identity_context(aid)}\n"
        f"{obs}\n"
        f"Mittente: {req.sender}\nOggetto: {req.subject}\n"
        f"--- EMAIL RICEVUTA ---\n{body[:6000]}\n--- FINE EMAIL ---\n"
        f"{_slots_context(req.instruction + ' ' + req.subject + ' ' + body[:2000])}\n"
        f"Istruzione dell'utente: {req.instruction or 'rispondi in modo appropriato'}"
    )
    out = _run_agent(prompt)
    out["suggested_attachments"] = _suggest_attachments(
        aid, f"{out.get('draft', '')} {req.instruction} {req.subject} {body[:1000]}"
    )
    return out


class MailAskRequest(BaseModel):
    question: str
    account_id: Optional[int] = None


@app.post("/mail_ask")
def mail_ask(req: MailAskRequest):
    """La domanda va all'agente, che usa i suoi tool MCP ade-mail per
    cercare e leggere la posta prima di rispondere."""
    prompt = (
        "Domanda dell'utente sulla sua posta (usa i tool ade-mail per cercare "
        "e leggere le mail rilevanti prima di rispondere; rispondi in "
        f"italiano, conciso): {req.question}"
    )
    try:
        return {"answer": agent_bridge.run(prompt), "engine": "agent"}
    except agent_bridge.AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e


class SenderSummaryRequest(BaseModel):
    sender: str
    account_id: Optional[int] = None


@app.post("/mail/sender_summary")
def sender_summary(req: SenderSummaryRequest):
    profile = mail_memory.get_sender_profile(req.sender) or {}
    prompt = (
        f"Riassumi in 3-4 frasi il rapporto con questo mittente ({req.sender}) "
        "usando i tool ade-mail (sender_history, search_mail) per recuperare "
        f"lo storico. Profilo noto: {json.dumps(profile, ensure_ascii=False)[:800]}"
    )
    try:
        return {"summary": agent_bridge.run(prompt), "engine": "agent"}
    except agent_bridge.AgentUnavailable as e:
        raise HTTPException(503, str(e)) from e


# ── OBSERVER + AUDIT ─────────────────────────────────────────────────

@app.get("/observer/stats")
def observer_stats(account_id: Optional[int] = None):
    aid = account_id or _active_id() or 0
    return observer.get_stats(aid)


# ── APPROVAZIONI (il canale fuori banda) ─────────────────────────────
# Questi endpoint sono il punto in cui un UMANO autorizza un'azione
# distruttiva richiesta dall'agente. Vivono qui, dietro il token della
# console, e non esistono come tool MCP: l'agente puo' creare richieste
# e leggerne lo stato, ma non puo' approvarle.

@app.get("/approvals")
def list_approvals():
    """Richieste in attesa di approvazione umana."""
    return policy.store().list_pending()


@app.get("/approvals/{request_id}")
def get_approval(request_id: str):
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    return rec


def _who() -> str:
    import getpass
    try:
        return f"console:{getpass.getuser()}"
    except Exception:
        return "console"


@app.post("/approvals/{request_id}/approve")
def approve_request(request_id: str):
    """Approva SOLO dopo una verifica dell'utente fisico (Windows Hello /
    Touch ID). Il token di sessione della console sta in un file: un
    processo puo' leggerlo e chiamare questo endpoint. Il prompt OS e'
    cio' che un processo non puo' superare — quindi sta qui, non nella
    finestra. Senza backend di consenso: 503, nessuna approvazione."""
    from ade_mail_agent import consent
    rec = policy.store().get(request_id)
    if not rec:
        raise HTTPException(404, "Richiesta inesistente")
    reason = f"GigaMail: approvare {rec['tool']} ({request_id})?"
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if not ok:
        raise HTTPException(403, "Verifica utente non superata o annullata")
    if not policy.store().approve(request_id, by=_who()):
        raise HTTPException(409, "Richiesta non approvabile (già decisa o scaduta)")
    return {"success": True, "request_id": request_id, "status": "approved"}


@app.post("/approvals/{request_id}/reject")
def reject_request(request_id: str):
    if not policy.store().reject(request_id, by=_who()):
        raise HTTPException(409, "Richiesta non rifiutabile (già decisa o scaduta)")
    return {"success": True, "request_id": request_id, "status": "rejected"}


@app.get("/audit")
def audit_log(limit: int = 100):
    """Ultime azioni compiute dall'agente (per la vista console)."""
    from ade_mail_agent.core.data_paths import app_root
    path = os.path.join(str(app_root()), "agent_audit.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


# ── AUTOMAZIONI (0.2.1): regole, watcher, notifiche ──────────────────
# La console e' la UI umana delle regole di risposta. Stesso vincolo degli
# approvals: creare o riattivare una regola e' una PRE-approvazione, quindi
# passa da consent.require_human (Hello) qui nel backend — il token della
# console sta in un file, il prompt OS no. Pausa/elimina sono liberi.
# Il token Telegram NON passa da qui: solo CLI (`gigamail telegram setup`).

class RuleCreate(BaseModel):
    account_id: Optional[int] = None
    trigger_kind: str            # senders | folder
    trigger_values: List[str]
    reply_style: str = ""
    doc_paths: List[str] = []
    mode: str = "semi"           # semi | auto
    first_contact: str = "semi"
    daily_cap: int = 10
    cooldown_hours: float = 4.0
    expiry_days: float = 30.0


def _require_human_or_http(reason: str) -> None:
    from ade_mail_agent import consent
    try:
        ok = consent.require_human(reason)
    except consent.ConsentUnavailable as e:
        raise HTTPException(503, str(e)) from e
    if not ok:
        raise HTTPException(403, "Verifica utente non superata o annullata")


def _rule_view(r: dict) -> dict:
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    d = dict(r)
    d["sent_today"] = rs.sent_today(r["rule_id"])
    d["state"] = ("paused" if r["paused"] else
                  "expired" if r["expired"] else "active")
    return d


@app.get("/rules")
def list_rules():
    from ade_mail_agent.core import rules as rules_mod
    return [_rule_view(r) for r in rules_mod.store().list_all()]


@app.post("/rules")
def create_rule(body: RuleCreate):
    """Crea una regola. Hello obbligatorio: e' una pre-approvazione."""
    import time as _t

    from ade_mail_agent.core import rules as rules_mod
    aid = body.account_id or _active_id()
    if not aid:
        raise HTTPException(400, "Nessun account")
    if body.trigger_kind not in rules_mod.TRIGGER_KINDS:
        raise HTTPException(400, "trigger_kind non valido")
    if body.mode not in rules_mod.MODES or body.first_contact not in rules_mod.MODES:
        raise HTTPException(400, "mode/first_contact non validi")
    values = [v.strip().lower() if body.trigger_kind == "senders" else v.strip()
              for v in body.trigger_values if v and v.strip()]
    if not values:
        raise HTTPException(400, "trigger vuoto")
    docs = []
    for pth in body.doc_paths or []:
        pth = os.path.abspath(pth)
        if not os.path.exists(pth):
            raise HTTPException(400, f"Documento inesistente: {pth}")
        docs.append(pth)
    _require_human_or_http(
        f"GigaMail: creare la regola {body.mode.upper()} per {', '.join(values)}?")
    rule_id = rules_mod.store().create(
        account_id=aid, trigger_kind=body.trigger_kind, trigger_values=values,
        reply_style=body.reply_style, doc_paths=docs, mode=body.mode,
        first_contact=body.first_contact, daily_cap=body.daily_cap,
        cooldown_hours=body.cooldown_hours, expiry_days=body.expiry_days,
        created_by=_who(), hello_verified_at=_t.time())
    policy.audit("rule", {"rule_id": rule_id, "mode": body.mode, "trigger": values},
                 "rule_created", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@app.post("/rules/{rule_id}/pause")
def pause_rule(rule_id: str):
    from ade_mail_agent.core import rules as rules_mod
    if not rules_mod.store().pause(rule_id, "pausa dalla console"):
        raise HTTPException(404, "Regola inesistente")
    policy.audit("rule", {"rule_id": rule_id}, "rule_paused", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@app.post("/rules/{rule_id}/resume")
def resume_rule(rule_id: str):
    """Riattivare = ri-approvare: Hello."""
    import time as _t

    from ade_mail_agent.core import rules as rules_mod
    if not rules_mod.store().get(rule_id):
        raise HTTPException(404, "Regola inesistente")
    _require_human_or_http(f"GigaMail: riattivare la regola {rule_id}?")
    rules_mod.store().resume(rule_id, _t.time())
    policy.audit("rule", {"rule_id": rule_id}, "rule_resumed", detail=_who())
    return _rule_view(rules_mod.store().get(rule_id))


@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    from ade_mail_agent.core import rules as rules_mod
    if not rules_mod.store().delete(rule_id):
        raise HTTPException(404, "Regola inesistente")
    policy.audit("rule", {"rule_id": rule_id}, "rule_deleted", detail=_who())
    return {"success": True}


@app.get("/rules/{rule_id}/activity")
def rule_activity(rule_id: str, limit: int = 30):
    """Le mail che la regola ha guardato, con esito."""
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    with rs._conn() as conn:
        rows = conn.execute(
            "SELECT message_id, sender, status, reason, request_id, ts"
            " FROM handled WHERE rule_id=? ORDER BY ts DESC LIMIT ?",
            (rule_id, int(limit))).fetchall()
    return [dict(r) for r in rows]


# --- watcher: processo separato, avviato/fermato dal backend ---------------

def _watch_state() -> dict:
    """Delega al watcher: la console non tiene una sua idea di "attivo"."""
    from ade_mail_agent.watcher import running_state
    return running_state()


def _pid_alive(pid: int) -> bool:
    from ade_mail_agent.watcher import pid_alive
    return pid_alive(pid)

@app.get("/watch/status")
def watch_status():
    return _watch_state()


@app.post("/watch/start")
def watch_start(interval: int = 60):
    """Avvia `gigamail watch` come processo staccato (sopravvive alla
    console), log in app_root()/watch.log."""
    import subprocess
    import sys as _sys

    from ade_mail_agent.core.data_paths import app_root
    st = _watch_state()
    if st["running"]:
        return st
    log_path = os.path.join(str(app_root()), "watch.log")
    log = open(log_path, "a", encoding="utf-8")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [_sys.executable, "-u", "-m", "ade_mail_agent.cli", "watch",
         "--verbose", "--interval", str(max(int(interval), 10))],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        env=dict(os.environ), **kwargs)
    from ade_mail_agent.core import rules as rules_mod
    rules_mod.store().kv_set("watch_pid", str(proc.pid))
    policy.audit("watch", {"pid": proc.pid, "interval": interval}, "watch_started",
                 detail=_who())
    return {"running": True, "pid": proc.pid, "interval": interval,
            "last_tick_age_seconds": None, "active_rules": st["active_rules"]}


@app.post("/watch/stop")
def watch_stop():
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    pid = int(rs.kv_get("watch_pid", "0") or 0)
    if pid and _pid_alive(pid):
        try:
            if os.name == "nt":
                import subprocess
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=15)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
        except Exception as e:
            raise HTTPException(500, f"stop fallito: {e}") from e
    rs.kv_set("watch_pid", "0")
    rs.kv_set("watch_heartbeat", "0")
    policy.audit("watch", {"pid": pid}, "watch_stopped", detail=_who())
    return _watch_state()


@app.get("/watch/log")
def watch_log(lines: int = 60):
    from ade_mail_agent.core.data_paths import app_root
    path = os.path.join(str(app_root()), "watch.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ln.rstrip("\n") for ln in f.readlines()[-int(lines):]]


# --- notifiche / agente -----------------------------------------------------

@app.get("/notify/status")
def notify_status():
    from ade_mail_agent import consent
    from ade_mail_agent.core import desktop_notify, telegram_channel
    tg = telegram_channel.load_config()
    return {
        "agent": agent_bridge.status(),
        "consent_backend": consent.backend_name(),
        "desktop": {
            "enabled": desktop_notify.enabled(),
            "buttons": desktop_notify.actions_supported(),
            "platform": os.name,
        },
        "telegram": {
            "configured": bool(tg),
            "chat_id": tg["chat_id"] if tg else None,
            "approve": bool(tg and tg.get("approve")),
        },
        "command": bool(policy._notify_command()),
        "lang": policy.user_lang(),
    }


@app.post("/notify/desktop-setup")
def notify_desktop_setup():
    """Rende cliccabili i bottoni della toast (HKLM, prompt UAC)."""
    from ade_mail_agent.core import desktop_notify
    if os.name != "nt":
        return {"buttons": False, "note": "solo Windows"}
    desktop_notify._win_register_aumid()
    ok = desktop_notify.register_protocol_machine()
    policy.audit("notify", {"buttons": ok}, "desktop_setup", detail=_who())
    return {"buttons": ok}


# ── ONBOARDING ───────────────────────────────────────────────────────
# La console apre la guida iniziale al primo avvio (nessun account, flag
# non ancora scritto) e la puo' riaprire quando vuole; il flag vive nel
# KV di %APPDATA%/ADE, non nel localStorage di Electron, cosi' un
# reinstall della console non la ripropone a chi ha gia' tutto.

@app.get("/onboarding")
def onboarding_status():
    from ade_mail_agent.core import rules as rules_mod
    done = rules_mod.store().kv_get("onboarding_done", "") == "1"
    return {"done": done, "accounts": len(core_accounts.get_accounts()),
            "platform": os.name}


@app.post("/onboarding/done")
def onboarding_done():
    from ade_mail_agent.core import rules as rules_mod
    rules_mod.store().kv_set("onboarding_done", "1")
    return {"done": True}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
