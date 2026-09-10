"""Normalizzazione degli eventi Google verso la forma Microsoft Graph.

Il test che conta davvero e' test_offset_di_fuso_non_arriva_ad_availability:
availability._parse_graph_dt toglie i millisecondi e la Z, ma NON un
offset '+02:00'. Se google_calendar lasciasse passare l'offset,
find_free_slots confronterebbe datetime aware e naive e morirebbe con un
TypeError, per giunta solo negli account Google e solo in certe stagioni.
"""

from datetime import datetime

import pytest

from ade_mail_agent.core import availability, google_calendar


def _evento_google(**over):
    ev = {
        "id": "abc123",
        "summary": "Sopralluogo Via Treviglio",
        "status": "confirmed",
        "location": "Milano",
        "description": "Portare le planimetrie",
        "start": {"dateTime": "2026-08-12T15:00:00+02:00", "timeZone": "Europe/Rome"},
        "end": {"dateTime": "2026-08-12T16:00:00+02:00", "timeZone": "Europe/Rome"},
        "htmlLink": "https://calendar.google.com/x",
        "attendees": [{"email": "cliente@example.com", "displayName": "Cliente"}],
    }
    ev.update(over)
    return ev


def test_forma_graph_completa():
    g = google_calendar._to_graph(_evento_google())
    assert g["id"] == "abc123"
    assert g["subject"] == "Sopralluogo Via Treviglio"
    assert g["location"]["displayName"] == "Milano"
    assert g["body"]["content"] == "Portare le planimetrie"
    assert g["attendees"][0]["emailAddress"]["address"] == "cliente@example.com"
    assert g["provider"] == "google"


def test_offset_di_fuso_non_arriva_ad_availability():
    """L'offset va risolto qui, non lasciato al consumatore."""
    g = google_calendar._to_graph(_evento_google())
    assert "+" not in g["start"]["dateTime"]
    assert "Z" not in g["start"]["dateTime"]

    # E il risultato deve essere davvero masticabile da availability.
    inizio = availability._parse_graph_dt(g["start"])
    fine = availability._parse_graph_dt(g["end"])
    assert inizio is not None and fine is not None
    assert inizio.tzinfo is None, "un datetime aware fa esplodere find_free_slots"
    assert (fine - inizio).seconds == 3600


def test_orario_utc_convertito_a_locale():
    """13:00 UTC in agosto sono le 15:00 a Roma."""
    ev = _evento_google(start={"dateTime": "2026-08-12T13:00:00Z"},
                        end={"dateTime": "2026-08-12T14:00:00Z"})
    g = google_calendar._to_graph(ev)
    if google_calendar._TZ is None:
        pytest.skip("tzdata non disponibile su questa installazione")
    assert g["start"]["dateTime"] == "2026-08-12T15:00:00"
    assert g["start"]["timeZone"] == "Europe/Rome"


def test_evento_giornata_intera():
    ev = _evento_google(start={"date": "2026-08-12"}, end={"date": "2026-08-13"})
    g = google_calendar._to_graph(ev)
    assert g["isAllDay"] is True
    assert g["start"]["dateTime"] == "2026-08-12T00:00:00"
    assert availability._parse_graph_dt(g["start"]) == datetime(2026, 8, 12)


def test_evento_senza_titolo_non_rompe_il_riassunto():
    g = google_calendar._to_graph(_evento_google(summary=None))
    assert g["subject"] == "(senza titolo)"


def test_slot_liberi_calcolati_su_eventi_google():
    """Prova end-to-end della forma: gli eventi Google devono passare
    dentro find_free_slots senza adattatori."""
    eventi = [google_calendar._to_graph(_evento_google())]
    slots = availability.find_free_slots(
        eventi, now=datetime(2026, 8, 10, 9, 0), days_ahead=5,
        duration_minutes=60, min_notice_hours=0, max_slots=10,
    )
    assert slots, "nessuno slot: la forma dell'evento non e' stata capita"
    occupato = datetime(2026, 8, 12, 15, 0)
    assert all(datetime.fromisoformat(s["start"]) != occupato for s in slots)


def test_ensure_local_ripulisce_quello_che_manda_l_agente():
    assert google_calendar._ensure_local("2026-08-12T15:00") == "2026-08-12T15:00:00"
    assert google_calendar._ensure_local("2026-08-12T15:00:00Z") == "2026-08-12T15:00:00"
    assert google_calendar._ensure_local("2026-08-12T15:00:00+02:00") == "2026-08-12T15:00:00"
