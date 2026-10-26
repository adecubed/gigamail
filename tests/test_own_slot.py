"""A conversation's own appointment does not take up that conversation's
slot.

A client picked Tuesday 17:00 from the times we had offered. GigaMail put
the appointment in the calendar; a minute later the reply draft looked for
free slots, found 17:00 busy and told the client the calendar was already
taken. Taken by that very client.
"""
from datetime import datetime, timedelta

import pytest

from gigamail.core import appointments
from gigamail.watcher import drafting

SUBJECT = ("Re: Nuovo messaggio di Luca sul tuo immobile, Trilocale in Via "
           "Roma, 10, Milano")
SENDER = "luca.bianchi@example.com"


def _msg():
    return {"id": "3578", "subject": SUBJECT,
            "from": {"emailAddress": {"name": "Luca", "address": SENDER}},
            "body_text": "domani alle 17 puo' essere un buon momento"}


@pytest.fixture()
def calendar(monkeypatch, tmp_path):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "appointments")
    appointments.set_store(appointments.AppointmentStore(tmp_path / "a.db"))
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        hour=17, minute=0, second=0, microsecond=0)
    event = {"id": "ev-contact",
             "start": {"dateTime": tomorrow.isoformat(), "timeZone": "Europe/Rome"},
             "end": {"dateTime": (tomorrow + timedelta(hours=1)).isoformat(),
                     "timeZone": "Europe/Rome"}}
    other = {"id": "ev-other",
             "start": {"dateTime": (tomorrow + timedelta(days=1)).isoformat(),
                       "timeZone": "Europe/Rome"},
             "end": {"dateTime": (tomorrow + timedelta(days=1, hours=1)).isoformat(),
                     "timeZone": "Europe/Rome"}}
    monkeypatch.setattr(drafting.calendar_router, "get_events",
                        lambda **kw: [event, other])
    seen = []

    def slots(events, **kw):
        seen.append([e["id"] for e in events])
        return [{"start": tomorrow.isoformat(), "end": "", "label": "martedi' alle 17:00"}]
    monkeypatch.setattr(drafting.availability, "find_free_slots", slots)
    yield {"start": tomorrow, "seen": seen}
    appointments.set_store(None)


def _confirm(start):
    appointments.store().upsert(
        2, appointments.thread_key(SUBJECT, SENDER), "ev-contact", "confermato",
        start.isoformat(timespec="minutes"),
        (start + timedelta(hours=1)).isoformat(timespec="minutes"), "Luca")


def test_the_conversation_event_does_not_take_the_slot(calendar):
    _confirm(calendar["start"])
    drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 2, _msg())
    assert calendar["seen"] == [["ev-other"]]       # its own event left out


def test_the_prompt_says_the_appointment_is_set(calendar):
    _confirm(calendar["start"])
    prompt = drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 2, _msg())
    assert "APPOINTMENT ALREADY SET" in prompt
    assert "CONFIRM IT" in prompt


def test_without_a_confirmed_appointment_nothing_changes(calendar):
    prompt = drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 2, _msg())
    assert calendar["seen"] == [["ev-contact", "ev-other"]]
    assert "APPOINTMENT ALREADY SET" not in prompt


def test_a_mere_proposal_frees_nothing(calendar):
    """Only a confirmed appointment has an event to leave out."""
    appointments.store().upsert(
        2, appointments.thread_key(SUBJECT, SENDER), "", "proposto",
        calendar["start"].isoformat(timespec="minutes"), "", "Luca")
    prompt = drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 2, _msg())
    assert calendar["seen"] == [["ev-contact", "ev-other"]]
    assert "APPOINTMENT ALREADY SET" not in prompt


def test_without_the_extension_the_store_is_not_opened(monkeypatch):
    """Opening the store creates .appointments.db, and that file switches the
    appointments extension on for someone who never enabled it."""
    monkeypatch.setattr(drafting.extensions, "enabled", lambda name: False)
    monkeypatch.setattr(appointments, "store",
                        lambda: pytest.fail("appointments store opened"))
    assert drafting._thread_appointment(2, SUBJECT, SENDER) is None
