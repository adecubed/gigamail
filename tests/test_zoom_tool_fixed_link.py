"""Lo strumento dell'agente usa il link personale Zoom quando non c'e'
un'app Server-to-Server: niente da creare, niente approvazione. Visto dal
vivo: con il solo link salvato l'agente rispondeva "Zoom non collegato"."""
from gigamail import policy, server
from gigamail.core import video_call, zoom

LINK = "https://us02web.zoom.us/j/1234567890?pwd=abc"


def _tool():
    fn = server.create_zoom_meeting
    return getattr(fn, "fn", fn)


def test_senza_app_ma_con_link_personale(monkeypatch, tmp_path):
    policy.set_store(policy.ApprovalStore(str(tmp_path / "a.db")))
    monkeypatch.setattr(zoom, "configurato", lambda: False)
    monkeypatch.setattr(video_call, "link_fisso", lambda: LINK)
    monkeypatch.setattr(zoom, "crea_riunione", lambda *a, **k: (_ for _ in ()).throw(AssertionError("niente API")))
    r = _tool()(topic="Call con Maxi", start="2026-10-22T15:00:00")
    assert r["join_url"] == LINK and r["fixed_link"] is True
    assert policy.store().list_pending() == []   # nessuna approvazione per un link che esiste gia'
    policy.set_store(None)


def test_senza_app_e_senza_link_lo_dice_e_non_apre_richieste(monkeypatch, tmp_path):
    policy.set_store(policy.ApprovalStore(str(tmp_path / "a.db")))
    monkeypatch.setattr(zoom, "configurato", lambda: False)
    monkeypatch.setattr(video_call, "link_fisso", lambda: "")
    r = _tool()(topic="Call", start="2026-10-22T15:00:00")
    assert r["error"] == "zoom_not_connected" and "personal Zoom link" in r["note"]
    assert policy.store().list_pending() == []
    policy.set_store(None)
