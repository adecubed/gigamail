"""Il link personale Zoom: una video call confermata ha il suo link anche
senza app Server-to-Server, e resta sempre lo stesso."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent import policy
from ade_mail_agent.core import accounts as core_accounts
from ade_mail_agent.core import appointments, video_call

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
    monkeypatch.setattr(video_call, "_cc", lambda aid: ["info@fingroupspa.com"])
    monkeypatch.setattr(video_call, "_firma", lambda aid: "Simone Napoli")
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
    return {"id": mid, "subject": "Re: Bilocali Via Treviglio", "body_text": corpo,
            "from": {"emailAddress": {"address": "lk@example.com", "name": "Lorenzo K"}}}


def _conferma(monkeypatch, mid, inizio):
    _agente(monkeypatch, '{"stato":"proposto","inizio":"%s","scelta_unica":true,"accetta":true}' % inizio)
    avvisi = []
    appointments.sweep(2, [_msg(mid, "va bene alle 16:00")], adesso=NOW,
                       avvisa=lambda *a: avvisi.append(a))
    return avvisi


def test_senza_app_il_link_personale_finisce_nella_mail(monkeypatch, mondo):
    cal, notifiche = mondo
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    avvisi = _conferma(monkeypatch, "link-1", "2026-09-17T16:00")

    assert cal.aggiornati[-1]["location"] == LINK
    rec = policy.store().get(notifiche[0])
    assert rec["status"] == policy.PENDING, "il link non parte senza approvazione"
    assert LINK in rec["args"]["body"]
    riga = appointments.store().get(
        2, appointments.thread_key("Bilocali Via Treviglio", "lk@example.com"))
    assert riga["zoom_id"] == video_call._FISSO and riga["zoom_url"] == LINK
    testo = appointments.testo_avviso(*avvisi[0])
    assert "personale" in testo and LINK in testo


def test_un_nuovo_orario_non_manda_una_seconda_mail(monkeypatch, mondo):
    _cal, notifiche = mondo
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    _conferma(monkeypatch, "link-2", "2026-09-17T16:00")
    avvisi = _conferma(monkeypatch, "link-3", "2026-09-18T16:00")
    assert len(notifiche) == 1, "il link e' lo stesso: niente seconda mail"
    assert "spostata" in appointments.testo_avviso(*avvisi[0])


def test_senza_link_e_senza_app_lo_dice(monkeypatch, mondo):
    monkeypatch.setattr(video_call, "link_fisso", lambda: "")
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    avvisi = _conferma(monkeypatch, "link-4", "2026-09-17T16:00")
    assert "console" in appointments.testo_avviso(*avvisi[0])


# ── la scheda della console ──────────────────────────────────────────

@pytest.fixture()
def client():
    from ade_mail_agent import http_api
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
