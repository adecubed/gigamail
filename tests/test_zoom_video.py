# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Zoom e video call: la riunione nasce alla conferma, il link parte solo
dopo l'approvazione, e ogni mail verso l'esterno mette il thread in ascolto."""
import json
from datetime import datetime

import pytest

from ade_mail_agent import policy
from ade_mail_agent.core import appointments, video_call, zoom
from ade_mail_agent.core import rules as rules_mod

# martedi' 15 settembre 2026, ore 09:00
NOW = datetime(2026, 9, 15, 9, 0)


class Risposta:
    def __init__(self, status, dato=None):
        self.status_code = status
        self._dato = dato
        self.content = b"" if dato is None else json.dumps(dato).encode()
        self.text = self.content.decode()

    def json(self):
        return self._dato


@pytest.fixture()
def zoom_finto(monkeypatch):
    chiamate, code = [], {}
    monkeypatch.setattr(zoom, "config", lambda: {
        "account_id": "acc", "client_id": "cid", "client_secret": "sec"})
    zoom._token.clear()

    def _request(metodo, url, **kw):
        chiamate.append((metodo, url.replace(zoom.API_URL, ""), kw))
        if url == zoom.TOKEN_URL:
            return Risposta(200, {"access_token": "tok", "expires_in": 3600})
        coda = code.get((metodo, url.replace(zoom.API_URL, "")))
        if coda:
            return coda.pop(0)
        if metodo == "POST":
            return Risposta(201, {"id": 123, "join_url": "https://zoom.us/j/123",
                                  "password": "abc"})
        if metodo == "GET":
            return Risposta(200, {"email": "me@example.com"})
        return Risposta(204)
    monkeypatch.setattr(zoom.requests, "request", _request)
    yield chiamate, code
    zoom._token.clear()


# ── il client Zoom ───────────────────────────────────────────────────

def test_crea_riunione_con_token_e_fuso(zoom_finto):
    chiamate, _ = zoom_finto
    r = zoom.crea_riunione("Video call con Lorenzo", "2026-09-16T16:00", 60)
    zoom.crea_riunione("Seconda", "2026-09-17T16:00", 30)
    assert r == {"id": "123", "join_url": "https://zoom.us/j/123",
                 "password": "abc"}
    token = [c for c in chiamate if c[1] == zoom.TOKEN_URL]
    assert len(token) == 1, "il token vale un'ora: non si chiede a ogni chiamata"
    post = [c for c in chiamate if c[0] == "POST" and c[1] == "/users/me/meetings"][0]
    assert post[2]["json"]["start_time"] == "2026-09-16T16:00:00"
    assert post[2]["json"]["timezone"] == "Europe/Rome"
    assert post[2]["json"]["settings"]["waiting_room"] is True
    assert post[2]["headers"]["Authorization"] == "Bearer tok"


def test_token_rifiutato_si_rinnova_una_volta(zoom_finto):
    chiamate, code = zoom_finto
    code[("GET", "/users/me")] = [Risposta(401, {"message": "expired"}),
                                  Risposta(200, {"email": "x@example.com"})]
    assert zoom.verifica() == "x@example.com"
    assert len([c for c in chiamate if c[1] == zoom.TOKEN_URL]) == 2


def test_senza_credenziali_non_chiama_zoom(monkeypatch):
    monkeypatch.setattr(zoom, "config", lambda: None)
    monkeypatch.setattr(zoom.requests, "request",
                        lambda *a, **k: pytest.fail("Zoom non doveva essere chiamato"))
    with pytest.raises(zoom.ZoomNonConfigurato):
        zoom.crea_riunione("x", "2026-09-16T16:00")


def test_riunione_gia_tolta_non_e_un_errore(zoom_finto):
    _, code = zoom_finto
    code[("DELETE", "/meetings/9")] = [Risposta(404, {"message": "not found"})]
    assert zoom.cancella_riunione("9") is True


def test_errore_di_zoom_resta_un_errore(zoom_finto):
    _, code = zoom_finto
    code[("POST", "/users/me/meetings")] = [Risposta(400, {"message": "bad time"})]
    with pytest.raises(zoom.ZoomErrore) as e:
        zoom.crea_riunione("x", "2026-09-16T16:00")
    assert "bad time" in str(e.value)


# ── dalla conferma al link ───────────────────────────────────────────

class Cal:
    def __init__(self):
        self.creati, self.aggiornati, self.cancellati = [], [], []

    def create_event(self, subject, start, end, location='', body='',
                     attendees=None):
        self.creati.append({"subject": subject, "start": start})
        return {"id": f"ev{len(self.creati)}"}

    def update_event(self, event_id, **kw):
        self.aggiornati.append({"id": event_id, **kw})
        return {}

    def delete_event(self, event_id):
        self.cancellati.append(event_id)
        return True

    def get_events(self, days_ahead=7, **kw):
        return []


@pytest.fixture()
def mondo(monkeypatch, tmp_path, zoom_finto):
    cal = Cal()
    monkeypatch.setattr(appointments, "calendar_router", cal)
    monkeypatch.setattr(video_call, "calendar_router", cal)
    appointments.set_store(appointments.AppointmentStore(tmp_path / "a.db"))
    notifiche = []
    monkeypatch.setattr(
        video_call.policy, "notify_approval_requested",
        lambda rid, tool, preview, **kw: notifiche.append((rid, preview, kw)) or True)
    monkeypatch.setattr(video_call, "_cc", lambda aid: ["info@fingroupspa.com"])
    monkeypatch.setattr(video_call, "_firma", lambda aid: "Ufficio Vendite")
    monkeypatch.setattr(video_call.telegram_channel, "channel", lambda: None)
    yield cal, notifiche, zoom_finto[0]
    appointments.set_store(None)


def _agente(monkeypatch, risposta):
    monkeypatch.setattr(appointments.agent_bridge, "run",
                        lambda prompt, timeout=None: risposta)


def _msg(mid, corpo, subject="Re: Bilocali Via Treviglio"):
    return {"id": mid, "subject": subject, "body_text": corpo,
            "from": {"emailAddress": {"address": "lk@example.com",
                                      "name": "Lorenzo K"}}}


def _conferma(monkeypatch, mid="zoom-1", inizio="2026-09-16T16:00"):
    _agente(monkeypatch, '{"stato":"proposto","inizio":"%s",'
                         '"scelta_unica":true}' % inizio)
    avvisi = []
    n = appointments.sweep(2, [_msg(mid, "va bene alle 16:00")], adesso=NOW,
                           avvisa=lambda *a: avvisi.append(a))
    return n, avvisi


def test_video_call_confermata_crea_riunione_e_mail_in_approvazione(monkeypatch, mondo):
    cal, notifiche, _ = mondo
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    n, avvisi = _conferma(monkeypatch)
    assert n == 1 and len(cal.creati) == 1
    assert cal.aggiornati[-1]["location"] == "https://zoom.us/j/123"

    rid, preview, kw = notifiche[0]
    rec = policy.store().get(rid)
    assert rec["status"] == policy.PENDING, "il link non parte senza approvazione"
    assert rec["args"]["to"] == "lk@example.com"
    assert rec["args"]["cc"] == ["info@fingroupspa.com"]
    assert "https://zoom.us/j/123" in rec["args"]["body"]
    assert "Codice d'accesso: abc" in rec["args"]["body"]
    assert rec["args"]["body"].startswith("Gentile Lorenzo K,")

    riga = rules_mod.store().find_by_request(rid)
    assert riga["rule_id"] == video_call.RULE_ID
    assert riga["status"] == "awaiting_approval", "il watcher la deve eseguire"

    testo = appointments.testo_avviso(*avvisi[0])
    assert "Zoom" in testo and "approvazione" in testo


def test_senza_video_nessuna_riunione(monkeypatch, mondo):
    cal, notifiche, chiamate = mondo
    appointments.segui(2, "Bilocali Via Treviglio", "lk@example.com")
    n, _ = _conferma(monkeypatch)
    assert n == 1 and len(cal.creati) == 1
    assert notifiche == []
    assert not [c for c in chiamate if c[1] == "/users/me/meetings"]


def test_zoom_non_collegato_lo_dice_e_non_chiede_nulla(monkeypatch, mondo):
    cal, notifiche, _ = mondo
    monkeypatch.setattr(zoom, "config", lambda: None)
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    n, avvisi = _conferma(monkeypatch)
    assert n == 1 and len(cal.creati) == 1
    assert notifiche == []
    assert "gigamail zoom setup" in appointments.testo_avviso(*avvisi[0])


def test_nuovo_orario_sposta_la_riunione_senza_altra_mail(monkeypatch, mondo):
    cal, notifiche, chiamate = mondo
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    _conferma(monkeypatch)
    _, avvisi = _conferma(monkeypatch, mid="zoom-2", inizio="2026-09-17T16:00")
    assert [c for c in chiamate if c[0] == "PATCH" and c[1] == "/meetings/123"]
    assert len(notifiche) == 1, "il link e' gia' stato mandato: niente seconda mail"
    assert "spostata" in appointments.testo_avviso(*avvisi[0])


def test_disdetta_cancella_la_riunione(monkeypatch, mondo):
    cal, _, chiamate = mondo
    appointments.segna_video(2, "Bilocali Via Treviglio", "lk@example.com")
    _conferma(monkeypatch)
    _agente(monkeypatch, '{"stato":"disdetto"}')
    appointments.sweep(2, [_msg("zoom-3", "mi spiace, devo annullare")],
                       adesso=NOW)
    assert [c for c in chiamate if c[0] == "DELETE" and c[1] == "/meetings/123"]
    assert cal.cancellati == ["ev1"]


def test_un_aggiornamento_non_perde_il_segno_video(monkeypatch, tmp_path):
    appointments.set_store(appointments.AppointmentStore(tmp_path / "c.db"))
    appointments.segna_video(2, "Bilocali", "lk@example.com")
    _agente(monkeypatch, '{"stato":"proposto","inizio":"2026-09-16T16:00"}')
    appointments.dalla_mail(2, "Re: Bilocali", "domani alle 16:00?",
                            "lk@example.com", adesso=NOW)
    riga = appointments.store().get(
        2, appointments.thread_key("Bilocali", "lk@example.com"))
    assert riga["stato"] == "proposto" and riga["video"] == 1
    appointments.set_store(None)


# ── ogni mail verso l'esterno resta in ascolto ───────────────────────

def test_invio_nuovo_verso_esterni_in_ascolto(monkeypatch, tmp_path):
    """Il 15/09 la risposta a una mail nuova con listino e planimetrie non
    ha fatto scattare nessun avviso: si seguivano solo le risposte."""
    from ade_mail_agent.core import mail_router

    appointments.set_store(appointments.AppointmentStore(tmp_path / "d.db"))
    monkeypatch.setattr(mail_router, "_send_backend",
                        lambda **kw: {"success": True})
    monkeypatch.setattr(mail_router, "_account", lambda aid=None: {"id": 2})
    monkeypatch.setattr(appointments, "dalla_mail_async", lambda *a: False)
    monkeypatch.setattr(appointments, "_propri", lambda: (
        {"simonaples@msn.com"}, {"fingroupspa.com"}))
    mail_router.send_message(
        account_id=2,
        to="Lorenzo <LK@gmail.com>, info@fingroupspa.com, "
           "simonaples@msn.com, cliente@msn.com",
        subject="Bilocali", body="ci faccia sapere quando fissare una video call")
    righe = appointments.store().aperti(2)
    assert sorted(r["con"] for r in righe) == ["cliente@msn.com", "lk@gmail.com"]
    assert all(r["video"] == 1 for r in righe)
    appointments.set_store(None)


def test_parla_di_video():
    assert appointments.parla_di_video("fissiamo una videochiamata")
    assert appointments.parla_di_video("Per la video call su Zoom")
    assert not appointments.parla_di_video("ci vediamo in ufficio")
