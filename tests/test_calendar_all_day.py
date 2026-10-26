"""Eventi di un giorno intero: chi li crea passa primo e ultimo giorno
compresi; Graph e Google ricevono la fine esclusiva, il giorno dopo."""

from gigamail.core import calendar_dates, google_calendar, ms_calendar


def test_range_giorno_singolo_e_piu_giorni():
    assert calendar_dates.all_day_range("2026-10-16") == ("2026-10-16", "2026-10-17")
    assert calendar_dates.all_day_range("2026-10-16T09:00:00", "2026-10-16T19:00:00") == ("2026-10-16", "2026-10-17")
    assert calendar_dates.all_day_range("2026-10-30", "2026-11-02") == ("2026-10-30", "2026-11-03")
    # fine prima dell'inizio: un giorno solo, non un evento rovesciato
    assert calendar_dates.all_day_range("2026-10-16", "2026-10-10") == ("2026-10-16", "2026-10-17")


class _Risposta:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_graph_riceve_isallday_e_mezzanotti(monkeypatch):
    inviati = {}
    monkeypatch.setattr(ms_calendar, "_headers", lambda: {})
    monkeypatch.setattr(ms_calendar.requests, "post",
                        lambda url, headers=None, json=None: inviati.update(json) or _Risposta(json))
    ms_calendar.create_event("fuori ufficio", "2026-10-16", "2026-10-16", all_day=True)
    assert inviati["isAllDay"] is True
    assert inviati["start"]["dateTime"] == "2026-10-16T00:00:00"
    assert inviati["end"]["dateTime"] == "2026-10-17T00:00:00"


def test_graph_patch_da_giorno_intero_a_orario(monkeypatch):
    inviati = {}
    monkeypatch.setattr(ms_calendar, "_headers", lambda: {})
    monkeypatch.setattr(ms_calendar.requests, "patch",
                        lambda url, headers=None, json=None: inviati.update(json) or _Risposta(json))
    ms_calendar.update_event("ev1", start="2026-10-16T09:00", end="2026-10-16T10:00", all_day=False)
    assert inviati["isAllDay"] is False
    assert inviati["start"]["dateTime"] == "2026-10-16T09:00:00"


def test_google_riceve_date_senza_orario(monkeypatch):
    inviati = {}
    monkeypatch.setattr(google_calendar, "auth_headers", lambda email=None: {})
    monkeypatch.setattr(google_calendar, "check", lambda res: None)
    monkeypatch.setattr(google_calendar.requests, "post",
                        lambda url, headers=None, json=None, params=None, timeout=None:
                        inviati.update(json) or _Risposta({"id": "g1", "start": {"date": "2026-10-16"},
                                                           "end": {"date": "2026-10-17"}}))
    ev = google_calendar.create_event("fuori ufficio", "2026-10-16", "2026-10-16", all_day=True)
    assert inviati["start"] == {"date": "2026-10-16"}
    assert inviati["end"]["date"] == "2026-10-17"
    assert ev["isAllDay"] is True
