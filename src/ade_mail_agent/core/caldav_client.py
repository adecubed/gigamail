"""
caldav_client.py — Client CalDAV per ADE Mail.
Supporta lettura/scrittura eventi su server CalDAV (Aruba, Fastmail, NextCloud, ecc.)

Autodiscovery URL:
- Aruba:     https://syncdav.aruba.it/calendars/{email}/
- Generic:   https://{host}/.well-known/caldav
"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

try:
    import caldav
    from caldav import DAVClient
    from icalendar import Calendar, Event, vText, vDatetime
    _CALDAV_AVAILABLE = True
except ImportError:
    _CALDAV_AVAILABLE = False

# URL templates per provider noti
_PROVIDER_URLS = {
    "aruba.it":       "https://syncdav.aruba.it/calendars/{email}/",
    "arubapec.it":    "https://syncdav.aruba.it/calendars/{email}/",
    "postassl.it":    "https://syncdav.postassl.it/calendars/{email}/",
    "fastmail.com":   "https://caldav.fastmail.com/dav/principals/user/{email}/",
    "icloud.com":     "https://caldav.icloud.com/",
    "gmail.com":      None,  # Google non supporta CalDAV standard
}


def _detect_caldav_url(email: str) -> Optional[str]:
    """Rileva l'URL CalDAV basandosi sul dominio email."""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    for provider, url_template in _PROVIDER_URLS.items():
        if domain.endswith(provider):
            if url_template is None:
                return None
            return url_template.format(email=email)
    # Fallback generico: prova well-known
    return f"https://{domain}/.well-known/caldav"


def is_available() -> bool:
    return _CALDAV_AVAILABLE


def test_connection(url: str, username: str, password: str) -> dict:
    """
    Testa la connessione CalDAV.
    Ritorna {success, message, calendars: [{name, url}]}
    """
    if not _CALDAV_AVAILABLE:
        return {"success": False, "message": "caldav non installato"}
    try:
        client = DAVClient(url=url, username=username, password=password)
        principal = client.principal()
        cals = principal.calendars()
        calendar_list = []
        for cal in cals:
            try:
                name = str(cal.name) if cal.name else "Calendario"
                calendar_list.append({"name": name, "url": str(cal.url)})
            except Exception:
                pass
        return {
            "success": True,
            "message": f"Connesso — {len(calendar_list)} calendari trovati",
            "calendars": calendar_list,
        }
    except Exception as e:
        return {"success": False, "message": str(e), "calendars": []}


def get_events(url: str, username: str, password: str,
               days_ahead: int = 30, calendar_url: str = None) -> List[Dict]:
    """
    Legge eventi CalDAV per i prossimi N giorni.
    Ritorna lista di dict compatibili con il formato Microsoft Graph.
    """
    if not _CALDAV_AVAILABLE:
        return []
    try:
        client = DAVClient(url=url, username=username, password=password)
        principal = client.principal()

        if calendar_url:
            cal = client.calendar(url=calendar_url)
        else:
            cals = principal.calendars()
            if not cals:
                return []
            cal = cals[0]

        now = datetime.now(tz=timezone.utc)
        end = now + timedelta(days=days_ahead)

        results_raw = cal.date_search(start=now, end=end, expand=True)
        events = []
        for vevent in results_raw:
            try:
                ev = _parse_vevent(vevent)
                if ev:
                    events.append(ev)
            except Exception:
                continue
        return events
    except Exception as e:
        print(f"[CALDAV] get_events error: {e}")
        return []


def create_event(url: str, username: str, password: str,
                 subject: str, start: str, end: str,
                 location: str = "", body: str = "",
                 attendees: List[str] = None,
                 calendar_url: str = None) -> Optional[Dict]:
    """Crea un evento CalDAV."""
    if not _CALDAV_AVAILABLE:
        return None
    try:
        client = DAVClient(url=url, username=username, password=password)
        principal = client.principal()

        if calendar_url:
            cal = client.calendar(url=calendar_url)
        else:
            cals = principal.calendars()
            if not cals:
                return None
            cal = cals[0]

        import uuid
        uid = str(uuid.uuid4())
        start_dt = _parse_dt(start)
        end_dt   = _parse_dt(end)

        ical = Calendar()
        ical.add("prodid", "-//ADE Mail//caldav_client//IT")
        ical.add("version", "2.0")

        ev = Event()
        ev.add("uid",     uid)
        ev.add("summary", subject)
        ev.add("dtstart", start_dt)
        ev.add("dtend",   end_dt)
        if location:
            ev.add("location", location)
        if body:
            ev.add("description", body)
        if attendees:
            for a in attendees:
                ev.add("attendee", f"mailto:{a}")

        ical.add_component(ev)
        cal.save_event(ical.to_ical().decode("utf-8"))

        return {
            "id":      uid,
            "subject": subject,
            "start":   {"dateTime": start, "timeZone": "Europe/Rome"},
            "end":     {"dateTime": end,   "timeZone": "Europe/Rome"},
            "location": {"displayName": location},
            "body":    {"contentType": "Text", "content": body},
            "source":  "caldav",
        }
    except Exception as e:
        print(f"[CALDAV] create_event error: {e}")
        return None


def update_event(url: str, username: str, password: str,
                 event_uid: str, calendar_url: str = None, **kwargs) -> bool:
    """Aggiorna un evento CalDAV per UID."""
    if not _CALDAV_AVAILABLE:
        return False
    try:
        client = DAVClient(url=url, username=username, password=password)
        principal = client.principal()

        if calendar_url:
            cals = [client.calendar(url=calendar_url)]
        else:
            cals = principal.calendars()

        for cal in cals:
            try:
                results = cal.search(uid=event_uid)
                if not results:
                    continue
                vevent_obj = results[0]
                ical = vevent_obj.icalendar_instance
                for component in ical.walk():
                    if component.name == "VEVENT":
                        if "subject" in kwargs:
                            component["summary"] = vText(kwargs["subject"])
                        if "start" in kwargs:
                            component["dtstart"] = vDatetime(_parse_dt(kwargs["start"]))
                        if "end" in kwargs:
                            component["dtend"] = vDatetime(_parse_dt(kwargs["end"]))
                        if "location" in kwargs:
                            component["location"] = vText(kwargs["location"])
                        if "body" in kwargs:
                            component["description"] = vText(kwargs["body"])
                vevent_obj.data = ical.to_ical().decode("utf-8")
                vevent_obj.save()
                return True
            except Exception:
                continue
        return False
    except Exception as e:
        print(f"[CALDAV] update_event error: {e}")
        return False


def delete_event(url: str, username: str, password: str,
                 event_uid: str, calendar_url: str = None) -> bool:
    """Elimina un evento CalDAV per UID."""
    if not _CALDAV_AVAILABLE:
        return False
    try:
        client = DAVClient(url=url, username=username, password=password)
        principal = client.principal()

        if calendar_url:
            cals = [client.calendar(url=calendar_url)]
        else:
            cals = principal.calendars()

        for cal in cals:
            try:
                results = cal.search(uid=event_uid)
                if results:
                    results[0].delete()
                    return True
            except Exception:
                continue
        return False
    except Exception as e:
        print(f"[CALDAV] delete_event error: {e}")
        return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_dt(dt_str: str) -> datetime:
    """Converte stringa datetime in oggetto datetime aware."""
    dt_str = str(dt_str or "").strip()
    dt_str = dt_str.replace("Z", "+00:00")
    # Rimuovi offset se presente e aggiungi UTC
    dt_str = re.sub(r"[+-]\d{2}:\d{2}$", "", dt_str)
    if len(dt_str) == 16:
        dt_str += ":00"
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(tz=timezone.utc)


def _parse_vevent(vevent_obj) -> Optional[Dict]:
    """Converte un evento CalDAV nel formato dict di ADE Mail."""
    try:
        ical = vevent_obj.icalendar_instance
        for component in ical.walk():
            if component.name != "VEVENT":
                continue

            uid     = str(component.get("uid", ""))
            subject = str(component.get("summary", ""))
            dtstart = component.get("dtstart")
            dtend   = component.get("dtend")
            loc     = str(component.get("location", ""))
            desc    = str(component.get("description", ""))

            start_str = _dt_to_str(dtstart.dt if dtstart else None)
            end_str   = _dt_to_str(dtend.dt   if dtend   else None)

            attendees = []
            for att in component.get("attendee", []) if isinstance(component.get("attendee"), list) else ([component.get("attendee")] if component.get("attendee") else []):
                addr = str(att).replace("mailto:", "").replace("MAILTO:", "")
                if addr:
                    attendees.append({"emailAddress": {"address": addr, "name": ""}})

            return {
                "id":      uid,
                "subject": subject,
                "start":   {"dateTime": start_str, "timeZone": "Europe/Rome"},
                "end":     {"dateTime": end_str,   "timeZone": "Europe/Rome"},
                "location": {"displayName": loc},
                "body":    {"contentType": "Text", "content": desc},
                "bodyPreview": desc[:255],
                "attendees": attendees,
                "source":  "caldav",
            }
    except Exception:
        pass
    return None


def _dt_to_str(dt) -> str:
    """Converte datetime in stringa ISO."""
    if dt is None:
        return ""
    try:
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        else:
            # È un date, non datetime
            return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).isoformat()
    except Exception:
        return ""


def autodiscover(email: str, password: str) -> Optional[Dict]:
    """
    Autodiscovery CalDAV per un account email.
    Ritorna {url, calendars} o None se non supportato.
    """
    url = _detect_caldav_url(email)
    if not url:
        return None
    result = test_connection(url, email, password)
    if result["success"]:
        return {"url": url, "calendars": result["calendars"]}
    return None