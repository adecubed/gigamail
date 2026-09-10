"""Calendario: backend scelto da calendar_router (Microsoft Graph o Google)."""

from fastapi import APIRouter
from pydantic import BaseModel

from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import (
    availability,
    calendar_router,
)

router = APIRouter()


# ── CALENDARIO (backend via calendar_router) ─────────────────────────

@router.get("/calendar")
def calendar(days_ahead: int = 7, days_back: int = 0):
    return calendar_router.get_events(days_ahead=days_ahead, days_back=days_back)


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
    return calendar_router.create_event(
        req.subject, req.start, req.end, body=req.body, location=req.location
    )


@router.patch("/calendar/{event_id}")
def update_event(event_id: str, req: dict):
    return calendar_router.update_event(event_id, **(req or {}))


@router.delete("/calendar/{event_id}")
def delete_event(event_id: str):
    return {"success": calendar_router.delete_event(event_id)}


@router.get("/calendar/primary")
def calendar_primary():
    return {"account_id": core_accounts.get_calendar_primary()}


@router.post("/calendar/primary/{account_id}")
def set_calendar_primary(account_id: int):
    core_accounts.set_calendar_primary(account_id)
    return {"success": True}
