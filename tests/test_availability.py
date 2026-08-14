"""Slot liberi: la disponibilita' proposta ai clienti deve essere corretta
in modo deterministico (niente calcoli lasciati all'agente)."""
from datetime import datetime, timedelta

from ade_mail_agent.core import availability


def _ev(start: str, end: str, tz: str = "Europe/Rome") -> dict:
    return {"start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz}}


# lunedì 17 agosto 2026, ore 08:00
NOW = datetime(2026, 8, 17, 8, 0)


def test_slot_liberi_su_agenda_vuota():
    slots = availability.find_free_slots([], now=NOW, min_notice_hours=0,
                                         max_slots=3)
    assert len(slots) == 3
    assert slots[0]["start"].startswith("2026-08-17T09:30")


def test_rispetta_preavviso_minimo():
    slots = availability.find_free_slots([], now=NOW, min_notice_hours=24,
                                         max_slots=2)
    for s in slots:
        assert datetime.fromisoformat(s["start"]) >= NOW + timedelta(hours=24)


def test_evita_sovrapposizione_con_impegni():
    busy = [_ev("2026-08-18T09:00:00", "2026-08-18T13:00:00")]
    slots = availability.find_free_slots(busy, now=NOW, min_notice_hours=0,
                                         days_ahead=1, max_slots=10)
    for s in slots:
        start = datetime.fromisoformat(s["start"])
        end = datetime.fromisoformat(s["end"])
        if start.date() == datetime(2026, 8, 18).date():
            assert end <= datetime(2026, 8, 18, 9, 0) or \
                   start >= datetime(2026, 8, 18, 13, 0)


def test_buffer_prima_e_dopo_impegno():
    """Con buffer 15', uno slot che finisce alle 09:00 esatte quando alle
    09:00 inizia un impegno NON e' valido."""
    busy = [_ev("2026-08-18T09:30:00", "2026-08-18T10:30:00")]
    slots = availability.find_free_slots(
        busy, now=NOW, min_notice_hours=0, days_ahead=1,
        buffer_minutes=15, max_slots=10, duration_minutes=60,
    )
    for s in slots:
        end = datetime.fromisoformat(s["end"])
        start = datetime.fromisoformat(s["start"])
        if start.date() == datetime(2026, 8, 18).date():
            assert end + timedelta(minutes=15) <= datetime(2026, 8, 18, 9, 30) \
                   or start >= datetime(2026, 8, 18, 10, 45)


def test_salta_weekend():
    # venerdì 21 -> i successivi devono essere lunedì 24, non sab/dom
    friday = datetime(2026, 8, 21, 17, 0)
    slots = availability.find_free_slots([], now=friday, min_notice_hours=0,
                                         days_ahead=4, max_slots=4)
    for s in slots:
        assert datetime.fromisoformat(s["start"]).weekday() < 5


def test_orari_di_lavoro_rispettati():
    slots = availability.find_free_slots([], now=NOW, min_notice_hours=0,
                                         work_start="10:00", work_end="12:00",
                                         duration_minutes=60, max_slots=5)
    for s in slots:
        start = datetime.fromisoformat(s["start"])
        end = datetime.fromisoformat(s["end"])
        assert start.hour >= 10 and (end.hour < 12 or
                                     (end.hour == 12 and end.minute == 0))


def test_giornata_piena_nessuno_slot_quel_giorno():
    busy = [_ev("2026-08-18T09:00:00", "2026-08-18T19:00:00")]
    slots = availability.find_free_slots(busy, now=NOW, min_notice_hours=0,
                                         days_ahead=1, max_slots=10)
    giorni = {datetime.fromisoformat(s["start"]).date() for s in slots}
    assert datetime(2026, 8, 18).date() not in giorni


def test_etichetta_italiana():
    label = availability.etichetta_slot(datetime(2026, 8, 18, 15, 0))
    assert label == "martedì 18 agosto alle 15:00"


def test_eventi_utc_convertiti_in_locale():
    """Graph puo' restituire UTC: 07:00Z = 09:00 a Roma (ora legale)."""
    busy = [_ev("2026-08-18T07:00:00", "2026-08-18T16:00:00", tz="UTC")]
    slots = availability.find_free_slots(busy, now=NOW, min_notice_hours=0,
                                         days_ahead=1, max_slots=10)
    for s in slots:
        start = datetime.fromisoformat(s["start"])
        if start.date() == datetime(2026, 8, 18).date():
            assert start.hour < 9 or start.hour >= 18


def test_evento_malformato_ignorato_senza_crash():
    busy = [{"start": {}, "end": {}}, {"start": {"dateTime": "boh"}, "end": {}}]
    slots = availability.find_free_slots(busy, now=NOW, min_notice_hours=0,
                                         max_slots=2)
    assert len(slots) == 2
