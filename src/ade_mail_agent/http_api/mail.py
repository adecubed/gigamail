"""Posta: liste, cartelle, ricerca, indice locale, invio e azioni sul messaggio."""
import threading
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ade_mail_agent.core import (
    mail_memory,
    mail_router,
)

from .addresses import _remember_message_addresses, _save_address
from .common import _active_id

router = APIRouter()


# ── MAIL: LETTURA ────────────────────────────────────────────────────

@router.get("/mail")
def list_mail(top: int = 20, skip: int = 0, account_id: Optional[int] = None):
    aid = account_id or _active_id()
    result = mail_router.get_messages(aid, top=top, skip=skip)
    _remember_message_addresses(result)
    return result


@router.get("/mail/sent")
def list_sent(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="sent", top=top)


@router.get("/mail/spam")
def list_spam(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="spam", top=top)


@router.get("/mail/deleted")
def list_deleted(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="deleted", top=top)


@router.get("/mail/drafts")
def list_drafts(top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder="drafts", top=top)


@router.get("/mail/folder/{folder_id}")
def list_folder(folder_id: str, top: int = 20, account_id: Optional[int] = None):
    return mail_router.get_messages(account_id or _active_id(), folder=folder_id, top=top)


@router.get("/mail/unread")
def unread(top: int = 20, days: int = 5, folder: Optional[str] = None,
           account_id: Optional[int] = None):
    return mail_router.get_unread_messages(
        account_id or _active_id(), folder=folder or "inbox", top=top, days=days
    )


@router.get("/mail/unread_count")
def unread_count(account_id: Optional[int] = None):
    msgs = mail_router.get_unread_messages(account_id or _active_id(), top=99)
    return {"count": len(msgs)}


@router.get("/mail/folders")
def folders(account_id: Optional[int] = None):
    return mail_router.list_folders(account_id or _active_id())


class FolderRequest(BaseModel):
    name: str
    account_id: Optional[int] = None


@router.post("/mail/folders")
def create_folder(req: FolderRequest):
    return mail_router.create_folder(req.account_id or _active_id(), name=req.name)


@router.delete("/mail/folders/{folder_id}")
def delete_folder(folder_id: str, account_id: Optional[int] = None):
    return {"success": mail_router.delete_folder(account_id or _active_id(), folder_id=folder_id)}


@router.get("/mail/search/{query}")
def search(query: str, top: int = 10, account_id: Optional[int] = None):
    return mail_router.search_messages(account_id or _active_id(), query=query, top=top)


@router.get("/mail/sender_history")
def sender_history(email: str, account_id: Optional[int] = None):
    profile = mail_memory.get_sender_profile(email) or {}
    return {"profile": profile}


# ── MAIL MEMORY (indice locale) ──────────────────────────────────────

@router.get("/mail/memory/stats")
def memory_stats():
    return mail_memory.get_stats()


@router.get("/mail/memory/sender/{email}")
def memory_sender(email: str):
    return mail_memory.get_sender_profile(email) or {}


@router.get("/mail/memory/indexer_state")
def indexer_state(account_id: Optional[int] = None):
    aid = account_id or _active_id()
    return mail_memory.get_indexer_state(aid) if aid else {}


@router.post("/mail/memory/index")
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


@router.post("/mail/send")
def send_mail(req: SendRequest):
    result = mail_router.send_message(
        req.account_id or _active_id(),
        to=req.to, subject=req.subject, body=req.body,
        reply_to_id=req.reply_to_id, attachments=req.attachments,
        cc=req.cc, bcc=req.bcc,
    )
    _save_address(req.to)
    return result


@router.get("/mail/{message_id}")
def read_message(message_id: str, folder: str = "", account_id: Optional[int] = None):
    return mail_router.get_message(
        account_id or _active_id(), message_id=message_id, folder=folder
    )


@router.delete("/mail/{message_id}")
def delete_message(message_id: str, folder: str = "", account_id: Optional[int] = None):
    return {"success": mail_router.delete_message(
        account_id or _active_id(), message_id=message_id, folder=folder or None
    )}


@router.post("/mail/{message_id}/read")
def mark_read(message_id: str, folder: str = "inbox", account_id: Optional[int] = None):
    return {"success": mail_router.set_read_status(
        account_id or _active_id(), message_id=message_id, folder=folder, is_read=True
    )}


@router.post("/mail/{message_id}/unread")
def mark_unread(message_id: str, folder: str = "inbox", account_id: Optional[int] = None):
    return {"success": mail_router.set_read_status(
        account_id or _active_id(), message_id=message_id, folder=folder, is_read=False
    )}


@router.post("/mail/{message_id}/move")
def move_message(message_id: str, folder_id: str, source_folder: str = "",
                 account_id: Optional[int] = None):
    return {"success": mail_router.move_to_folder(
        account_id or _active_id(), message_id=message_id,
        folder_id=folder_id, source_folder=source_folder or None,
    )}


@router.post("/mail/{message_id}/spam")
def mark_spam(message_id: str, folder: str = "inbox", account_id: Optional[int] = None):
    return {"success": mail_router.move_to_folder(
        account_id or _active_id(), message_id=message_id,
        folder_id="spam", source_folder=folder,
    )}


@router.post("/mail/{message_id}/not_spam")
def not_spam(message_id: str, account_id: Optional[int] = None):
    return {"success": mail_router.move_to_folder(
        account_id or _active_id(), message_id=message_id,
        folder_id="inbox", source_folder="spam",
    )}
