"""
calendar.py — Gestione calendario via Microsoft Graph API.
"""

import requests
from .auth import get_token
from typing import Optional, List, Dict
from datetime import datetime, timedelta

GRAPH_URL = 'https://graph.microsoft.com/v1.0'


def _headers() -> dict:
    return {
        'Authorization': f'Bearer {get_token()}',
        'Content-Type': 'application/json',
        'Prefer': 'outlook.timezone="Europe/Rome"',
    }


def get_events(days_ahead: int = 7, days_back: int = 0) -> List[Dict]:
    """
    Ritorna eventi nella finestra [oggi-00:00 - days_back ... oggi + days_ahead]
    in orario locale Europe/Rome.

    days_back: quanti giorni di passato includere (0 = da inizio giornata di oggi).
    La finestra parte SEMPRE da mezzanotte di oggi (non dall'ora corrente), così
    gli appuntamenti di oggi già trascorsi restano visibili.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start - timedelta(days=max(0, days_back))
    end   = today_start + timedelta(days=days_ahead + 1)  # +1 per includere tutto l'ultimo giorno

    url = f'{GRAPH_URL}/me/calendarView'
    params = {
        'startDateTime': start.strftime('%Y-%m-%dT%H:%M:%S'),
        'endDateTime':   end.strftime('%Y-%m-%dT%H:%M:%S'),
        '$select': 'id,subject,start,end,location,attendees,bodyPreview,body',
        '$orderby': 'start/dateTime',
        '$top': 200,
    }

    events: List[Dict] = []
    res = requests.get(url, headers=_headers(), params=params, timeout=30)
    res.raise_for_status()
    data = res.json()
    events.extend(data.get('value', []))

    # Paginazione: segui @odata.nextLink finché presente (max 10 pagine di sicurezza)
    pages = 0
    next_link = data.get('@odata.nextLink')
    while next_link and pages < 10:
        r = requests.get(next_link, headers=_headers(), timeout=30)
        r.raise_for_status()
        d = r.json()
        events.extend(d.get('value', []))
        next_link = d.get('@odata.nextLink')
        pages += 1

    return events


def create_event(subject: str, start: str, end: str,
                 location: str = '', body: str = '',
                 attendees: List[str] = None) -> Dict:
    """
    Crea un evento nel calendario.
    start/end formato: '2025-04-01T10:00:00'
    """
    def _ensure_local(dt_str: str) -> str:
        import re as _re
        dt_str = str(dt_str or '').strip()
        dt_str = dt_str.replace('Z', '').replace('z', '')
        dt_str = _re.sub(r'[+-]\d{2}:\d{2}$', '', dt_str)
        if len(dt_str) == 16:
            dt_str += ':00'
        return dt_str

    payload = {
        'subject': subject,
        'start': {'dateTime': _ensure_local(start), 'timeZone': 'Europe/Rome'},
        'end':   {'dateTime': _ensure_local(end),   'timeZone': 'Europe/Rome'},
        'location': {'displayName': location},
        'body': {'contentType': 'Text', 'content': body},
    }
    if attendees:
        payload['attendees'] = [
            {'emailAddress': {'address': a}, 'type': 'required'}
            for a in attendees
        ]
    url = f'{GRAPH_URL}/me/events'
    res = requests.post(url, headers=_headers(), json=payload)
    res.raise_for_status()
    return res.json()


def update_event(event_id: str, **kwargs) -> Dict:
    """Aggiorna un evento esistente."""
    url = f'{GRAPH_URL}/me/events/{event_id}'
    payload = {}
    if 'subject' in kwargs:
        payload['subject'] = kwargs['subject']
    def _ensure_local(dt_str: str) -> str:
        import re as _re
        dt_str = str(dt_str or '').strip()
        dt_str = dt_str.replace('Z', '').replace('z', '')
        dt_str = _re.sub(r'[+-]\d{2}:\d{2}$', '', dt_str)
        if len(dt_str) == 16:
            dt_str += ':00'
        return dt_str
    if 'start' in kwargs:
        payload['start'] = {'dateTime': _ensure_local(kwargs['start']), 'timeZone': 'Europe/Rome'}
    if 'end' in kwargs:
        payload['end'] = {'dateTime': _ensure_local(kwargs['end']), 'timeZone': 'Europe/Rome'}
    if 'location' in kwargs:
        payload['location'] = {'displayName': kwargs['location']}
    if 'body' in kwargs:
        payload['body'] = {'contentType': 'Text', 'content': kwargs['body']}
    res = requests.patch(url, headers=_headers(), json=payload)
    res.raise_for_status()
    return res.json()


def delete_event(event_id: str) -> bool:
    """Cancella un evento."""
    url = f'{GRAPH_URL}/me/events/{event_id}'
    res = requests.delete(url, headers=_headers())
    return res.status_code == 204


def get_today_summary() -> str:
    """Ritorna stringa con riassunto appuntamenti di oggi."""
    all_events = get_events(days_ahead=1)
    # Filtra ai soli eventi che iniziano oggi
    today = datetime.now().date()
    events = []
    for e in all_events:
        dt_str = (e.get('start') or {}).get('dateTime') or ''
        try:
            if datetime.fromisoformat(dt_str[:19]).date() == today:
                events.append(e)
        except Exception:
            pass
    if not events:
        return 'Nessun appuntamento oggi.'
    lines = [f'Hai {len(events)} appuntamenti oggi:']
    for e in events:
        start = e['start']['dateTime'][:16].replace('T', ' alle ')
        lines.append(f'- {e["subject"]} — {start}')
    return '\n'.join(lines)