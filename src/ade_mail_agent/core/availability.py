"""Calcolo degli slot liberi dal calendario.

Serve al caso d'uso "proponi un appuntamento al cliente": l'agente non deve
dedurre la disponibilita' leggendo la lista eventi (sbaglia fusi, weekend,
sovrapposizioni). Qui la disponibilita' viene calcolata in modo
deterministico e restituita gia' pronta, con etichette in italiano.

Sorgente eventi: Microsoft Graph (calendario primario) e, se configurato
per l'account, CalDAV.
"""
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover
    _TZ = None

_GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì",
           "venerdì", "sabato", "domenica"]
_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
         "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]

# Feste nazionali a data fissa (mese, giorno). Pasquetta si calcola.
_FESTE_FISSE = ((1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1),
                (12, 8), (12, 25), (12, 26))


def _pasqua(anno: int) -> date:
    """Domenica di Pasqua, calendario gregoriano (Meeus/Jones/Butcher)."""
    a = anno % 19
    b, c = divmod(anno, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    # "L" nell'algoritmo originale: ruff vieta la l minuscola (E741).
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mese, giorno = divmod(h + ll - 7 * m + 114, 31)
    return date(anno, mese, giorno + 1)


def festivo(giorno: date, patrono: str = "") -> bool:
    """Festa nazionale italiana, Pasquetta compresa, o il patrono ("MM-GG").

    Proporre a un cliente l'8 dicembre o il lunedi' di Pasqua vuol dire
    fissare un appuntamento in un ufficio chiuso."""
    if (giorno.month, giorno.day) in _FESTE_FISSE:
        return True
    if giorno == _pasqua(giorno.year) + timedelta(days=1):
        return True
    if patrono:
        try:
            mese, gg = (int(x) for x in patrono.split("-"))
        except ValueError:
            return False
        return (giorno.month, giorno.day) == (mese, gg)
    return False


def _parse_graph_dt(node: Dict) -> Optional[datetime]:
    """Converte {'dateTime': ..., 'timeZone': ...} in datetime naive locale."""
    if not isinstance(node, dict):
        return None
    raw = str(node.get("dateTime") or "")
    if not raw:
        return None
    raw = raw.split(".")[0].replace("Z", "")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    tzname = str(node.get("timeZone") or "")
    if tzname.upper() == "UTC" and _TZ is not None:
        from datetime import timezone as _tzmod
        dt = dt.replace(tzinfo=_tzmod.utc).astimezone(_TZ).replace(tzinfo=None)
    return dt


def _busy_intervals(events: List[Dict]) -> List[tuple]:
    out = []
    for ev in events or []:
        start = _parse_graph_dt(ev.get("start"))
        end = _parse_graph_dt(ev.get("end"))
        if start and end and end > start:
            out.append((start, end))
    return sorted(out)


def etichetta_slot(dt: datetime) -> str:
    """'martedì 19 agosto alle 15:00' — per il testo delle mail."""
    return (f"{_GIORNI[dt.weekday()]} {dt.day} {_MESI[dt.month - 1]} "
            f"alle {dt.strftime('%H:%M')}")


def find_free_slots(
    events: List[Dict],
    days_ahead: int = 7,
    duration_minutes: int = 60,
    work_start: str = "09:30",
    work_end: str = "18:30",
    skip_weekends: bool = True,
    min_notice_hours: int = 24,
    buffer_minutes: int = 15,
    max_slots: int = 6,
    slot_step_minutes: int = 30,
    skip_holidays: bool = False,
    patrono: str = "",
    now: Optional[datetime] = None,
) -> List[Dict]:
    """Slot liberi compatibili con gli impegni esistenti.

    events: eventi in formato Microsoft Graph (start/end con dateTime).
    buffer_minutes: margine da lasciare prima e dopo ogni impegno.
    min_notice_hours: nessuna proposta prima di N ore da adesso.
    skip_holidays: salta i festivi italiani e, se indicato, il patrono.
    """
    now = now or datetime.now()
    busy = _busy_intervals(events)
    dur = timedelta(minutes=duration_minutes)
    buf = timedelta(minutes=buffer_minutes)
    earliest = now + timedelta(hours=min_notice_hours)

    try:
        wh, wm = [int(x) for x in work_start.split(":")]
        eh, em = [int(x) for x in work_end.split(":")]
    except Exception:
        wh, wm, eh, em = 9, 30, 18, 30

    slots: List[Dict] = []
    for offset in range(0, max(1, days_ahead) + 1):
        day: date = (now + timedelta(days=offset)).date()
        if skip_weekends and day.weekday() >= 5:
            continue
        if skip_holidays and festivo(day, patrono):
            continue
        cursor = datetime.combine(day, time(wh, wm))
        day_end = datetime.combine(day, time(eh, em))
        while cursor + dur <= day_end:
            slot_start, slot_end = cursor, cursor + dur
            if slot_start < earliest:
                cursor += timedelta(minutes=slot_step_minutes)
                continue
            libero = all(
                slot_end + buf <= b_start or slot_start >= b_end + buf
                for b_start, b_end in busy
            )
            if libero:
                slots.append({
                    "start": slot_start.isoformat(timespec="minutes"),
                    "end": slot_end.isoformat(timespec="minutes"),
                    "label": etichetta_slot(slot_start),
                })
                if len(slots) >= max_slots:
                    return slots
                # una sola proposta per fascia: passa al pomeriggio/giorno dopo
                cursor = slot_end + timedelta(hours=2)
                continue
            cursor += timedelta(minutes=slot_step_minutes)
    return slots
