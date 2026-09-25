"""Calendario: backend scelto da calendar_router (Microsoft Graph o Google)."""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import (
    availability,
    calendar_router,
)

from .common import _human_action

router = APIRouter()


# ── CALENDARIO (backend via calendar_router) ─────────────────────────

@router.get("/calendar")
def calendar(days_ahead: int = 7, days_back: int = 0,
             days: Optional[int] = None):
    """`days` e' il nome che usa la console (finestra calendario: 60,
    vista agenda: 7). Il backend leggeva solo days_ahead e ignorava
    l'altro in silenzio: la console riceveva sempre 7 giorni, e un
    appuntamento fra dieci giorni in calendario non compariva."""
    return calendar_router.get_events(
        days_ahead=days if days is not None else days_ahead,
        days_back=days_back)


@router.get("/calendar/today")
def calendar_today():
    return calendar_router.get_events(days_ahead=1, days_back=0)


@router.get("/calendar/free_slots")
def calendar_free_slots(days_ahead: int = 7, duration_minutes: int = 60,
                        max_slots: int = 4):
    events = calendar_router.get_events(days_ahead=days_ahead + 1)
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


@router.post("/calendar")
def create_event(req: EventRequest):
    execute = calendar_router.bind_action("create_event")
    return _human_action("create_event", req.model_dump(),
                         f"Creare l'appuntamento {req.subject!r} del {req.start}?",
                         lambda a: execute(**a))


@router.patch("/calendar/{event_id}")
def update_event(event_id: str, req: dict):
    execute = calendar_router.bind_action("update_event")
    args = {"event_id": event_id, "changes": req or {}}
    return _human_action("update_event", args, f"Modificare l'appuntamento {event_id}?",
                         lambda a: execute(event_id=a["event_id"], **a["changes"]))


@router.delete("/calendar/{event_id}")
def delete_event(event_id: str):
    execute = calendar_router.bind_action("delete_event")
    return _human_action("delete_event", {"event_id": event_id},
                         f"Eliminare l'appuntamento {event_id}?",
                         lambda a: {"success": execute(event_id=a["event_id"])})


@router.get("/calendar/primary")
def calendar_primary():
    return {"account_id": core_accounts.get_calendar_primary()}


@router.post("/calendar/primary/{account_id}")
def set_calendar_primary(account_id: int):
    core_accounts.set_calendar_primary(account_id)
    return {"success": True}
