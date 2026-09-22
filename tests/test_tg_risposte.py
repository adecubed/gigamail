"""Rispondere a un cliente da Telegram: l'istruzione diventa una bozza, e
la bozza passa dall'approvazione come tutte le altre."""

import pytest

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent import watcher as watcher_mod
from ade_mail_agent.core import mail_router, telegram_channel
from ade_mail_agent.core import rules as rules_mod
from ade_mail_agent.watcher import tg_risposte

CHAT = 1484306713


class FakeTG:
    def __init__(self):
        self.chat_id = CHAT
        self.approve_enabled = True
        self.sent = []
        self._next = 9000

    def send_message(self, text, buttons=None, html=False):
        self._next += 1
        self.sent.append({"text": text, "buttons": buttons, "id": self._next})
        return self._next

    def send(self, text, buttons=None, html=False):
        return bool(self.send_message(text, buttons, html))

    def answer_callback(self, cid, text=""):
        pass

    def clear_buttons(self, message_id):
        return True

    def delete_message(self, message_id):
        return True

    action_buttons = staticmethod(telegram_channel.Telegram.action_buttons)
    safe_html = staticmethod(telegram_channel.Telegram.safe_html)
    is_trusted = telegram_channel.Telegram.is_trusted


MAIL = {"id": "3485", "subject": "Re: Via Treviglio 28, Milano - bilocali disponibili",
        "from": {"emailAddress": {"address": "lk@example.com", "name": "Lorenzo K"}},
        "body_text": "Possiamo spostare la chiamata di 15 minuti?"}


@pytest.fixture(autouse=True)
def isolated(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield
    policy.set_store(None)
    rules_mod.set_store(None)


@pytest.fixture()
def world(monkeypatch):
    tg = FakeTG()
    w = {"tg": tg, "inviate": [], "prompt": [], "bozza": "Nessun problema, a dopo."}
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: dict(MAIL) if str(kw.get("message_id")) == "3485" else {})
    monkeypatch.setattr(mail_router, "send_message",
                        lambda **kw: w["inviate"].append(kw) or {"success": True})
    monkeypatch.setattr(agent_bridge, "run",
                        lambda prompt, **kw: w["prompt"].append(prompt) or w["bozza"])
    monkeypatch.setattr(telegram_channel, "channel", lambda: tg)
    monkeypatch.setattr(tg_risposte, "_cc", lambda aid: ["info@fingroupspa.com"])
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda rid, tool, preview, **kw: tg.send(kw.get("message") or "",
                                                                 kw.get("buttons")) or True)
    rules_mod.store().kv_set("tg_trusted_chat", str(CHAT))
    return w


def _avviso(tg):
    return tg_risposte.registra_avviso(tg, "Lorenzo K:\n«Possiamo spostare…»", 2, MAIL, "it")


def _cb(data):
    return {"kind": "callback", "chat_id": CHAT, "from_id": CHAT, "data": data,
            "callback_id": "c1", "message_id": 1}


def _testo(text, reply_to=0):
    return {"kind": "text", "chat_id": CHAT, "from_id": CHAT, "text": text,
            "message_id": 2, "reply_to": reply_to}


def test_l_avviso_ha_il_bottone_rispondi(world):
    chiave = _avviso(world["tg"])
    pulsanti = world["tg"].sent[-1]["buttons"]
    assert pulsanti[0][0]["callback_data"] == f"w:{chiave}"
    assert "Rispondi" in pulsanti[0][0]["text"]


def test_rispondi_poi_istruzione_crea_la_bozza_in_approvazione(world):
    """Il 17/09 l'avviso arrivava su Telegram ma da li' non si poteva
    rispondere al cliente."""
    tg, w = world["tg"], watcher_mod.Watcher()
    chiave = _avviso(tg)
    w.handle_telegram_event(tg, _cb(f"w:{chiave}"))
    assert "Cosa rispondo a Lorenzo K" in tg.sent[-1]["text"]
    w.handle_telegram_event(tg, _testo("ok va bene"))

    pend = policy.store().list_pending()
    assert len(pend) == 1
    args = pend[0]["args"]
    assert args["to"] == "lk@example.com" and args["cc"] == ["info@fingroupspa.com"]
    assert args["subject"].startswith("Re: Via Treviglio 28")
    assert args["body"] == world["bozza"]
    assert "ok va bene" in world["prompt"][-1]
    assert world["inviate"] == [], "niente parte senza approvazione"
    riga = rules_mod.store().find_by_request(pend[0]["request_id"])
    assert riga["rule_id"] == tg_risposte.RULE_ID and riga["status"] == "awaiting_approval"


def test_rispondere_al_messaggio_dell_avviso_basta(world):
    tg, w = world["tg"], watcher_mod.Watcher()
    _avviso(tg)
    id_avviso = tg.sent[-1]["id"]
    w.handle_telegram_event(tg, _testo("va bene alle 16:15", reply_to=id_avviso))
    assert len(policy.store().list_pending()) == 1


def test_approvare_invia_con_destinatario_e_copia(world):
    tg, w = world["tg"], watcher_mod.Watcher()
    _avviso(tg)
    w.handle_telegram_event(tg, _testo("ok", reply_to=tg.sent[-1]["id"]))
    rid = policy.store().list_pending()[0]["request_id"]
    w.handle_telegram_event(tg, _cb(f"a:{rid}"))
    w.tick()
    assert len(world["inviate"]) == 1
    assert world["inviate"][0]["to"] == "lk@example.com"
    assert world["inviate"][0]["cc"] == ["info@fingroupspa.com"]


def test_agente_non_disponibile_lo_dice_e_non_crea_nulla(world, monkeypatch):
    def _no(prompt, **kw):
        raise agent_bridge.AgentUnavailable("Not logged in")
    monkeypatch.setattr(agent_bridge, "run", _no)
    tg, w = world["tg"], watcher_mod.Watcher()
    _avviso(tg)
    w.handle_telegram_event(tg, _testo("ok", reply_to=tg.sent[-1]["id"]))
    assert policy.store().list_pending() == []
    assert "Non riesco a scrivere la bozza" in tg.sent[-1]["text"]


def test_modifica_rifa_la_bozza_con_le_correzioni(world):
    tg, w = world["tg"], watcher_mod.Watcher()
    _avviso(tg)
    w.handle_telegram_event(tg, _testo("ok va bene", reply_to=tg.sent[-1]["id"]))
    rid = policy.store().list_pending()[0]["request_id"]
    world["bozza"] = "Nessun problema, ci sentiamo alle 16:15. A dopo."
    w.handle_telegram_event(tg, _cb(f"m:{rid}"))
    w.handle_telegram_event(tg, _testo("aggiungi l'orario"))
    assert policy.store().get(rid)["status"] == policy.REJECTED
    pend = policy.store().list_pending()
    assert len(pend) == 1 and pend[0]["args"]["body"] == world["bozza"]
    assert "aggiungi l'orario" in world["prompt"][-1]
    assert "ok va bene" in world["prompt"][-1]


def test_avviso_sconosciuto_non_crea_nulla(world):
    tg, w = world["tg"], watcher_mod.Watcher()
    w.handle_telegram_event(tg, _cb("w:deadbeef"))
    assert "non si trova" in tg.sent[-1]["text"]
    assert policy.store().list_pending() == []


def test_poll_legge_a_quale_messaggio_si_risponde(monkeypatch):
    tg = telegram_channel.Telegram({"token": "t", "chat_id": CHAT, "approve": True})

    class R:
        def json(self):
            return {"ok": True, "result": [
                {"update_id": 5, "message": {"text": "ok", "message_id": 12,
                                             "chat": {"id": CHAT}, "from": {"id": CHAT},
                                             "reply_to_message": {"message_id": 9001}}}]}
    monkeypatch.setattr(telegram_channel.requests, "post", lambda *a, **kw: R())
    events, _ = tg.poll(0)
    assert events[0]["reply_to"] == 9001


def test_send_message_ritorna_l_id(monkeypatch):
    tg = telegram_channel.Telegram({"token": "t", "chat_id": CHAT, "approve": True})

    class R:
        def json(self):
            return {"ok": True, "result": {"message_id": 4242}}
    monkeypatch.setattr(telegram_channel.requests, "post", lambda *a, **kw: R())
    assert tg.send_message("ciao") == 4242
    assert tg.send("ciao") is True
