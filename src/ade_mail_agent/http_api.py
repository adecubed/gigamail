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
import json
import sqlite3
import threading
from typing import Optional, List

import ade_mail_agent  # noqa: F401 — shim sys.path per core/

import accounts as core_accounts
import auth as core_auth
import mail_router
import mail_memory
import ms_calendar
import observer
import ade_masker
import identity_reader
from ade_mail_agent import agent_bridge
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

CONSOLE_TOKEN = os.environ.get("ADE_CONSOLE_TOKEN", "")
PORT = int(os.environ.get("ADE_CONSOLE_PORT", "8002"))

_ADE_MAIL_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "ADE", "mail"
)
os.makedirs(_ADE_MAIL_DIR, exist_ok=True)
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


@app.get("/accounts/providers")
def imap_providers():
    return [
        {"name": "Aruba", "imap_host": "imaps.aruba.it", "imap_port": 993,
         "smtp_host": "smtps.aruba.it", "smtp_port": 465},
        {"name": "Gmail", "imap_host": "imap.gmail.com", "imap_port": 993,
         "smtp_host": "smtp.gmail.com", "smtp_port": 465},
        {"name": "Libero", "imap_host": "imapmail.libero.it", "imap_port": 993,
         "smtp_host": "smtp.libero.it", "smtp_port": 465},
        {"name": "Altro (manuale)", "imap_host": "", "imap_port": 993,
         "smtp_host": "", "smtp_port": 465},
    ]


class ImapAccountRequest(BaseModel):
    name: str
    email: str
    password: str
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 465


@app.post("/accounts/imap")
def add_imap(req: ImapAccountRequest):
    acc_id = core_accounts.add_imap_account(
        req.name, req.email, req.password,
        imap_host=req.imap_host, imap_port=req.imap_port,
        smtp_host=req.smtp_host, smtp_port=req.smtp_port,
    )
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
        raise HTTPException(503, str(e))


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
        f"Istruzione: {req.instruction}"
    )
    out = _run_agent(prompt)
    out["suggested_attachments"] = _suggest_attachments(
        aid, f"{req.instruction} {req.subject}"
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
        f"Istruzione dell'utente: {req.instruction or 'rispondi in modo appropriato'}"
    )
    out = _run_agent(prompt)
    out["suggested_attachments"] = _suggest_attachments(
        aid, f"{req.instruction} {req.subject} {body[:1000]}"
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
        raise HTTPException(503, str(e))


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
        raise HTTPException(503, str(e))


# ── OBSERVER + AUDIT ─────────────────────────────────────────────────

@app.get("/observer/stats")
def observer_stats(account_id: Optional[int] = None):
    aid = account_id or _active_id() or 0
    return observer.get_stats(aid)


@app.get("/audit")
def audit_log(limit: int = 100):
    """Ultime azioni compiute dall'agente (per la vista console)."""
    root = os.environ.get("ADE_ROOT") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "ADE"
    )
    path = os.path.join(root, "agent_audit.jsonl")
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


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
