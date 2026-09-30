"""
google_calendar.py — Calendario via Google Calendar API v3.

Gemello di ms_calendar.py. La regola che governa questo modulo: TUTTO cio'
che esce di qui ha la forma di un evento Microsoft Graph.

Non e' pigrizia. availability.py dichiara nel proprio docstring di ricevere
"eventi in formato Microsoft Graph (start/end con dateTime)", e la stessa
forma la leggono find_free_slots, la finestra calendario della console e il
ponte verso l'agente. Normalizzare qui costa una funzione; cambiare la
forma costerebbe una revisione di tutti i consumatori.

Dettaglio non ovvio ma decisivo: availability._parse_graph_dt toglie i
millisecondi e la Z finale, ma NON l'offset di fuso. Un '+02:00' di Google
produrrebbe un datetime aware che, confrontato con i naive del calcolo
slot, solleva TypeError. Per questo qui si converte sempre a ora locale
Europe/Rome naive, esattamente come fa Graph.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from .google_auth import auth_headers, check

API = 'https://www.googleapis.com/calendar/v3'
TZ_NAME = 'Europe/Rome'

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(TZ_NAME)
except Exception:  # pragma: no cover - solo su installazioni senza tzdata
    _TZ = None


def _to_local_naive(raw: str) -> Optional[datetime]:
    """RFC3339 di Google -> datetime naive in ora locale Europe/Rome."""
    if not raw:
        return None
    txt = str(raw).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(_TZ).replace(tzinfo=None) if _TZ else dt.replace(tzinfo=None)
    return dt


def _graph_node(node: Dict) -> Dict:
    """{'dateTime': ...} oppure {'date': ...} di Google -> nodo Graph."""
    node = node or {}
    if node.get('dateTime'):
        dt = _to_local_naive(node['dateTime'])
        if dt:
            return {'dateTime': dt.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': TZ_NAME}
    if node.get('date'):
        # Evento di un giorno intero: Graph lo rappresenta comunque con un
        # dateTime a mezzanotte.
        return {'dateTime': f"{node['date']}T00:00:00", 'timeZone': TZ_NAME}
    return {'dateTime': '', 'timeZone': TZ_NAME}


def _to_graph(ev: Dict) -> Dict:
    """Evento Google -> forma Microsoft Graph, campo per campo."""
    body_text = ev.get('description') or ''
    attendees = [
        {'emailAddress': {'address': a.get('email', ''),
                          'name': a.get('displayName', '')},
         'type': 'optional' if a.get('optional') else 'required'}
        for a in (ev.get('attendees') or []) if a.get('email')
    ]
    return {
        'id': ev.get('id'),
        'subject': ev.get('summary') or '(senza titolo)',
        'start': _graph_node(ev.get('start')),
        'end': _graph_node(ev.get('end')),
        'location': {'displayName': ev.get('location') or ''},
        'bodyPreview': body_text[:255],
        'body': {'contentType': 'Text', 'content': body_text},
        'attendees': attendees,
        'isAllDay': bool((ev.get('start') or {}).get('date')),
        'webLink': ev.get('htmlLink', ''),
        'provider': 'google',
    }


def _rfc3339(dt: datetime) -> str:
    """Naive locale -> RFC3339 con offset, come lo vuole Google."""
    if _TZ is not None:
        return dt.replace(tzinfo=_TZ).isoformat()
    return dt.isoformat() + 'Z'


def get_events(days_ahead: int = 7, days_back: int = 0,
               calendar_id: str = 'primary', email: str = None) -> List[Dict]:
    """
    Eventi nella finestra [oggi-00:00 - days_back ... oggi + days_ahead],
    gia' in forma Graph. La finestra parte SEMPRE da mezzanotte di oggi,
    come in ms_calendar: gli appuntamenti odierni gia' trascorsi restano
    visibili.

    singleEvents espande le ricorrenze in occorrenze singole: senza,
    un impegno settimanale tornerebbe come una riga sola e il calcolo
    degli slot liberi lo ignorerebbe.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start - timedelta(days=max(0, days_back))
    end = today_start + timedelta(days=days_ahead + 1)

    url = f'{API}/calendars/{calendar_id}/events'
    params = {
        'timeMin': _rfc3339(start),
        'timeMax': _rfc3339(end),
        'singleEvents': 'true',
        'orderBy': 'startTime',
        'maxResults': 250,
        'timeZone': TZ_NAME,
    }

    events: List[Dict] = []
    headers = auth_headers(email)
    pages = 0
    token = None
    while pages < 10:
        if token:
            params['pageToken'] = token
        res = requests.get(url, headers=headers, params=params, timeout=30)
        check(res)
        data = res.json()
        events.extend(data.get('items', []))
        token = data.get('nextPageToken')
        pages += 1
        if not token:
            break

    # Gli eventi annullati restano nella risposta con status cancelled.
    return [_to_graph(e) for e in events if e.get('status') != 'cancelled']


def get_event(event_id: str, calendar_id: str = 'primary',
              email: str = None) -> Dict:
    url = f'{API}/calendars/{calendar_id}/events/{event_id}'
    res = requests.get(url, headers=auth_headers(email), timeout=30)
    check(res)
    return _to_graph(res.json())


def _ensure_local(dt_str: str) -> str:
    """Normalizza l'ora in arrivo dall'agente, come fa ms_calendar: niente
    Z, niente offset, secondi sempre presenti."""
    import re as _re
    txt = str(dt_str or '').strip()
    txt = txt.replace('Z', '').replace('z', '')
    txt = _re.sub(r'[+-]\d{2}:\d{2}$', '', txt)
    if len(txt) == 16:
        txt += ':00'
    return txt


def create_event(subject: str, start: str, end: str,
                 location: str = '', body: str = '',
                 attendees: List[str] = None,
                 calendar_id: str = 'primary', email: str = None) -> Dict:
    """Crea un evento. start/end in ora locale, es. '2026-04-01T10:00:00'."""
    payload = {
        'summary': subject,
        'start': {'dateTime': _ensure_local(start), 'timeZone': TZ_NAME},
        'end': {'dateTime': _ensure_local(end), 'timeZone': TZ_NAME},
        'location': location or '',
        'description': body or '',
    }
    if attendees:
        payload['attendees'] = [{'email': a} for a in attendees]

    url = f'{API}/calendars/{calendar_id}/events'
    # sendUpdates=all solo se ci sono invitati: altrimenti Google manda
    # comunque notifiche a vuoto.
    params = {'sendUpdates': 'all' if attendees else 'none'}
    res = requests.post(url, headers=auth_headers(email), json=payload,
                        params=params, timeout=30)
    check(res)
    return _to_graph(res.json())


def update_event(event_id: str, calendar_id: str = 'primary',
                 email: str = None, **kwargs) -> Dict:
    """Aggiorna un evento. Accetta le stesse chiavi di ms_calendar."""
    payload: Dict = {}
    if 'subject' in kwargs:
        payload['summary'] = kwargs['subject']
    if 'start' in kwargs:
        payload['start'] = {'dateTime': _ensure_local(kwargs['start']),
                            'timeZone': TZ_NAME}
    if 'end' in kwargs:
        payload['end'] = {'dateTime': _ensure_local(kwargs['end']),
                          'timeZone': TZ_NAME}
    if 'location' in kwargs:
        payload['location'] = kwargs['location']
    if 'body' in kwargs:
        payload['description'] = kwargs['body']

    url = f'{API}/calendars/{calendar_id}/events/{event_id}'
    res = requests.patch(url, headers=auth_headers(email), json=payload,
                         timeout=30)
    check(res)
    return _to_graph(res.json())


def delete_event(event_id: str, calendar_id: str = 'primary',
                 email: str = None) -> bool:
    url = f'{API}/calendars/{calendar_id}/events/{event_id}'
    res = requests.delete(url, headers=auth_headers(email),
                          params={'sendUpdates': 'all'}, timeout=30)
    # 204 cancellato, 410 gia' cancellato: per il chiamante e' lo stesso.
    return res.status_code in (204, 410)
