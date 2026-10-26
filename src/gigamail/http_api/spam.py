"""Spam filters: block mails by subject, sender or text, from the console."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gigamail.core import spam_filters

from . import console_click
from .common import _active_id

router = APIRouter()


class SpamFilterCreate(BaseModel):
    field: str = "subject"       # subject | from | body
    contains: str
    action: str = "spam"         # spam | trash
    account_id: Optional[int] = None   # None: every account
    all_accounts: bool = False
    apply_now: bool = True


def _console_only(request: Request) -> None:
    """Filters hide mail: only a click in the console (or the CLI) makes
    one. The agent, or a mail it reads, cannot."""
    if not console_click.is_console_click(request.headers):
        raise HTTPException(403, "only from the console")


@router.get("/spam_filters")
def list_filters(account_id: Optional[int] = None):
    return spam_filters.list_all(account_id)


@router.post("/spam_filters")
def create_filter(req: SpamFilterCreate, request: Request):
    _console_only(request)
    aid = None if req.all_accounts else (req.account_id or _active_id())
    try:
        entry = spam_filters.add(req.field, req.contains, req.action, aid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    moved = 0
    if req.apply_now:
        try:
            moved = spam_filters.run(aid) if aid is not None else spam_filters.run_all()
        except Exception:
            moved = 0
    return {"filter": entry, "moved": moved}


@router.delete("/spam_filters/{filter_id}")
def delete_filter(filter_id: str, request: Request):
    _console_only(request)
    if not spam_filters.remove(filter_id):
        raise HTTPException(404, "filter not found")
    return {"success": True}


@router.post("/spam_filters/run")
def run_filters(request: Request, account_id: Optional[int] = None):
    _console_only(request)
    aid = account_id or _active_id()
    return {"moved": spam_filters.run(aid)}
