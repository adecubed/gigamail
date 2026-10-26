"""Il link personale Zoom: una video call confermata ha il suo link anche
senza app Server-to-Server, e resta sempre lo stesso."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from gigamail import policy
from gigamail.core import accounts as core_accounts
from gigamail.core import appointments, video_call

# mercoledi' 16 settembre 2026, ore 09:00
NOW = datetime(2026, 9, 16, 9, 0)
LINK = "https://us02web.zoom.us/j/1234567890?pwd=abc"


class Cal:
    def __init__(self):
        self.creati, self.aggiornati = [], []

    def create_event(self, subject, start, end, location='', body='', attendees=None):
        self.creati.append({"subject": subject, "start": start})
        return {"id": f"ev{len(self.creati)}"}

    def update_event(self, event_id, **kw):
        self.aggiornati.append({"id": event_id, **kw})
        return {}

    def delete_event(self, event_id):
        return True

    def get_events(self, days_ahead=7, **kw):
        return []


@pytest.fixture()
def mondo(monkeypatch, tmp_path):
    """Zoom NON collegato, ma il link personale c'e'."""
    cal = Cal()
    monkeypatch.setattr(appointments, "calendar_router", cal)
    monkeypatch.setattr(video_call, "calendar_router", cal)
    monkeypatch.setattr(video_call.zoom, "configurato", lambda: False)
    monkeypatch.setattr(video_call.zoom, "crea_riunione",
                        lambda *a, **k: pytest.fail("Zoom non doveva essere chiamato"))
    monkeypatch.setattr(video_call.zoom, "sposta_riunione",
                        lambda *a, **k: pytest.fail("Zoom non doveva essere chiamato"))
    monkeypatch.setattr(video_call, "link_fisso", lambda: LINK)
    monkeypatch.setattr(video_call, "_cc", lambda aid: ["ufficio@agenzia.example"])
    monkeypatch.setattr(video_call, "_firma", lambda aid: "Paolo Conti")
    monkeypatch.setattr(video_call.telegram_channel, "channel", lambda: None)
    notifiche = []
    monkeypatch.setattr(video_call.policy, "notify_approval_requested",
                        lambda rid, tool, preview, **kw: notifiche.append(rid) or True)
    appointments.set_store(appointments.AppointmentStore(tmp_path / "a.db"))
    yield cal, notifiche
    appointments.set_store(None)


def _agente(monkeypatch, risposta):
    monkeypatch.setattr(appointments.agent_bridge, "run",
                        lambda prompt, timeout=None: risposta)


def _msg(mid, corpo):
    return {"id": mid, "subject": "Re: Bilocali Via Roma", "body_text": corpo,
            "from": {"emailAddress": {"address": "gb@example.com", "name": "Giorgio B"}}}


def _conferma(monkeypatch, mid, inizio):
    _agente(monkeypatch, '{"stato":"proposto","inizio":"%s","scelta_unica":true,"accetta":true}' % inizio)
    avvisi = []
    appointments.sweep(2, [_msg(mid, "va bene alle 16:00")], adesso=NOW,
                       avvisa=lambda *a: avvisi.append(a))
    return avvisi


def test_senza_app_il_link_personale_finisce_nella_mail(monkeypatch, mondo):
    cal, notifiche = mondo
    appointments.segna_video(2, "Bilocali Via Roma", "gb@example.com")
    avvisi = _conferma(monkeypatch, "link-1", "2026-09-17T16:00")

    assert cal.aggiornati[-1]["location"] == LINK
    rec = policy.store().get(notifiche[0])
    assert rec["status"] == policy.PENDING, "il link non parte senza approvazione"
    assert LINK in rec["args"]["body"]
    riga = appointments.store().get(
        2, appointments.thread_key("Bilocali Via Roma", "gb@example.com"))
    assert riga["zoom_id"] == video_call._FISSO and riga["zoom_url"] == LINK
    testo = appointments.testo_avviso(*avvisi[0])
    assert "personale" in testo and LINK in testo


def test_un_nuovo_orario_non_manda_una_seconda_mail(monkeypatch, mondo):
    _cal, notifiche = mondo
    appointments.segna_video(2, "Bilocali Via Roma", "gb@example.com")
    _conferma(monkeypatch, "link-2", "2026-09-17T16:00")
    avvisi = _conferma(monkeypatch, "link-3", "2026-09-18T16:00")
    assert len(notifiche) == 1, "il link e' lo stesso: niente seconda mail"
    assert "spostata" in appointments.testo_avviso(*avvisi[0])


def test_senza_link_e_senza_app_lo_dice(monkeypatch, mondo):
    monkeypatch.setattr(video_call, "link_fisso", lambda: "")
    appointments.segna_video(2, "Bilocali Via Roma", "gb@example.com")
    avvisi = _conferma(monkeypatch, "link-4", "2026-09-17T16:00")
    assert "console" in appointments.testo_avviso(*avvisi[0])


# ── a link already in the mail ───────────────────────────────────────

CLIENT = "gb@example.com"
OUR_LINK = "https://us06web.zoom.us/j/9876543210?pwd=xyz"


def _zoom_connected(monkeypatch):
    """Zoom connected: any meeting created here is a bug."""
    monkeypatch.setattr(video_call.zoom, "configurato", lambda: True)


def _we_send(monkeypatch, account_id, subject, body, inizio):
    """What mail_router does after one of our mails goes out."""
    _agente(monkeypatch, '{"stato":"confermato","inizio":"%s"}' % inizio)
    appointments.segui(account_id, subject, CLIENT)
    if appointments.parla_di_video(body):
        appointments.segna_video(account_id, subject, CLIENT)
    return appointments.after_sent(account_id, subject, body, CLIENT,
                                   adesso=NOW)


def test_new_mail_to_a_client_already_confirmed_creates_no_second_meeting(
        monkeypatch, mondo):
    """A new mail with a new subject, from another account, to a client
    whose video call at that time was already confirmed: it used to create
    a second appointment, a second Zoom meeting and a reply with the new
    link waiting for approval."""
    cal, notifiche = mondo
    appointments.segna_video(2, "Bilocali Via Roma", CLIENT)
    _conferma(monkeypatch, "link-5", "2026-09-17T16:00")
    assert len(notifiche) == 1
    _zoom_connected(monkeypatch)

    toccato = _we_send(monkeypatch, 3, "Link video call di domani ore 16:00",
                       f"Ecco il link per domani alle 16:00: {LINK}",
                       "2026-09-17T16:00")

    assert toccato["invariato"] is True
    assert len(cal.creati) == 1 and len(notifiche) == 1
    riga = appointments.store().get(3, appointments.thread_key(
        "Link video call di domani ore 16:00", CLIENT))
    assert riga["event_id"] == "ev1" and riga["zoom_url"] == LINK


def test_link_in_the_confirming_mail_is_the_calls_link(monkeypatch, mondo):
    cal, notifiche = mondo
    _zoom_connected(monkeypatch)

    _we_send(monkeypatch, 2, "Video call",
             f"Confermo la video call di domani alle 16:00.\n"
             f"Link Zoom: {OUR_LINK}.\n", "2026-09-17T16:00")

    assert notifiche == [], "no reply with another link"
    assert cal.aggiornati[-1]["location"] == OUR_LINK
    riga = appointments.store().get(2, appointments.thread_key("Video call", CLIENT))
    assert riga["zoom_id"] == video_call._EXTERNAL and riga["zoom_url"] == OUR_LINK


def test_client_reply_with_their_link_creates_no_meeting(monkeypatch, mondo):
    _cal, notifiche = mondo
    _zoom_connected(monkeypatch)
    appointments.segna_video(2, "Bilocali Via Roma", CLIENT)
    meet = "https://meet.google.com/abc-defg-hij"
    _agente(monkeypatch, '{"stato":"proposto","inizio":"2026-09-17T16:00",'
                         '"scelta_unica":true,"accetta":true}')
    avvisi = []
    appointments.sweep(2, [_msg("link-6", f"va bene alle 16:00, ci colleghiamo qui: {meet}")],
                       adesso=NOW, avvisa=lambda *a: avvisi.append(a))
    assert notifiche == []
    assert meet in appointments.testo_avviso(*avvisi[0])


def test_an_external_link_is_neither_moved_nor_cancelled(monkeypatch, mondo):
    _zoom_connected(monkeypatch)
    cancellate = []
    monkeypatch.setattr(video_call.zoom, "cancella_riunione", cancellate.append)
    _we_send(monkeypatch, 2, "Video call",
             f"Confermo domani alle 16:00, link: {OUR_LINK}", "2026-09-17T16:00")
    _we_send(monkeypatch, 2, "Re: Video call", "Spostiamo a venerdi alle 16:00?",
             "2026-09-18T16:00")
    _agente(monkeypatch, '{"stato":"disdetto"}')
    appointments.dalla_mail(2, "Re: Video call", "Devo disdire l'appuntamento",
                            CLIENT, adesso=NOW)
    assert cancellate == []


@pytest.mark.parametrize("testo, link", [
    ("entra da https://us02web.zoom.us/j/111222333?pwd=q1 alle 16",
     "https://us02web.zoom.us/j/111222333?pwd=q1"),
    ("<https://zoom.us/j/444555666>", "https://zoom.us/j/444555666"),
    ("Meet: https://meet.google.com/abc-defg-hij.",
     "https://meet.google.com/abc-defg-hij"),
    ("https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0",
     "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0"),
    ("scarica Zoom da https://zoom.us/download", ""),
    ("ci vediamo su Zoom alle 16", ""),
])
def test_meeting_link(testo, link):
    assert video_call.meeting_link(testo) == link


# ── la scheda della console ──────────────────────────────────────────

@pytest.fixture()
def client():
    from gigamail import http_api
    with TestClient(http_api.app) as c:
        yield c


@pytest.fixture(autouse=True)
def senza_link():
    core_accounts.set_setting("zoom_link_fisso", "")
    yield
    core_accounts.set_setting("zoom_link_fisso", "")


def test_salvare_il_link_dalla_console(client):
    assert client.post("/zoom/link", json={"url": LINK}).json() == {
        "success": True, "link": LINK}
    assert client.get("/zoom/status").json()["link"] == LINK
    assert video_call.link_fisso() == LINK


def test_un_indirizzo_qualsiasi_non_e_un_link_zoom(client):
    r = client.post("/zoom/link", json={"url": "https://esempio.com/riunione"})
    assert r.status_code == 400
    assert video_call.link_fisso() == ""


def test_stringa_vuota_toglie_il_link(client):
    client.post("/zoom/link", json={"url": LINK})
    assert client.post("/zoom/link", json={"url": ""}).json()["link"] == ""
    assert video_call.link_fisso() == ""
