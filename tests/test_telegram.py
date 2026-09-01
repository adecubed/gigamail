"""Telegram bidirezionale (0.2): comandi accettati SOLO dalla chat
configurata; approva solo se abilitato (opt-in dietro Hello); rifiuto
sempre; "modifica" → feedback → nuova bozza che ripassa dal gate (sempre
semi, anche su regola auto)."""
import json
import time

import pytest

from ade_mail_agent import agent_bridge, policy
from ade_mail_agent import watcher as watcher_mod
from ade_mail_agent.core import mail_router
from ade_mail_agent.core import rules as rules_mod
from ade_mail_agent.core import telegram_channel

CHAT = 1484306713
DMARC_PASS = {"authentication-results": ["mx; dmarc=pass header.from=fidato.it"]}


class FakeTG:
    """Telegram finto: registra cio' che GigaMail manda."""

    def __init__(self, approve=True):
        self.chat_id = CHAT
        self.approve_enabled = approve
        self.sent = []
        self.answered = []

    def send(self, text, buttons=None, html=False):
        self.sent.append({"text": text, "buttons": buttons, "html": html})
        return True

    def answer_callback(self, cid, text=""):
        self.answered.append(cid)

    action_buttons = staticmethod(telegram_channel.Telegram.action_buttons)
    safe_html = staticmethod(telegram_channel.Telegram.safe_html)
    is_trusted = telegram_channel.Telegram.is_trusted


def _msg(mid="101", sender="cliente@fidato.it", subject="Preventivo"):
    return {"id": mid, "subject": subject,
            "from": {"emailAddress": {"address": sender}},
            "body": {"content": "Quanto costa?"}, "isRead": False}


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
    w = {"unread": [], "replies": [], "draft": "Bozza uno", "tg": tg}
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: list(w["unread"]))
    monkeypatch.setattr(mail_router, "get_message_headers", lambda **kw: DMARC_PASS)
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: next((m for m in w["unread"]
                                           if str(m["id"]) == str(kw.get("message_id"))), {}))
    monkeypatch.setattr(mail_router, "reply_message",
                        lambda **kw: w["replies"].append(kw) or {"success": True})
    monkeypatch.setattr(agent_bridge, "run", lambda prompt, **kw: w["draft"])
    monkeypatch.setattr(telegram_channel, "channel", lambda: tg)
    # setup verificato simulato: la chat fidata registrata dietro Hello
    rules_mod.store().kv_set("tg_trusted_chat", str(CHAT))
    return w


def _rule(**kw):
    args = dict(account_id=1, trigger_kind="senders",
                trigger_values=["cliente@fidato.it"], reply_style="cordiale",
                doc_paths=[], mode="semi", created_by="test",
                hello_verified_at=time.time())
    args.update(kw)
    return rules_mod.store().create(**args)


def _pending_id():
    return policy.store().list_pending()[0]["request_id"]


def _ev_cb(data, chat=CHAT, frm=None):
    return {"kind": "callback", "chat_id": chat, "from_id": frm or chat,
            "data": data, "callback_id": "cb1"}


def _ev_text(text, chat=CHAT, frm=None):
    return {"kind": "text", "chat_id": chat, "from_id": frm or chat, "text": text}


# ------------------------------------------------------------- config

def test_config_load_save(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram_channel, "_config_path", lambda: tmp_path / "notify.json")
    (tmp_path / "notify.json").write_text(json.dumps({
        "command": ["curl", "https://api.telegram.org/botX/sendMessage", "chat_id=1"]}),
        encoding="utf-8")
    assert telegram_channel.load_config() is None  # niente blocco telegram
    telegram_channel.save_config("123:abc", CHAT, approve=False)
    cfg = telegram_channel.load_config()
    assert cfg == {"token": "123:abc", "chat_id": CHAT, "approve": False}
    # il vecchio comando curl verso telegram e' stato tolto (niente doppioni)
    data = json.loads((tmp_path / "notify.json").read_text(encoding="utf-8"))
    assert "command" not in data


def test_poll_parsing(monkeypatch):
    tg = telegram_channel.Telegram({"token": "t", "chat_id": CHAT, "approve": True})

    class R:
        def json(self):
            return {"ok": True, "result": [
                {"update_id": 10, "message": {"text": "ciao", "chat": {"id": CHAT},
                                              "from": {"id": CHAT}}},
                {"update_id": 11, "callback_query": {"id": "c9", "data": "a:req_1",
                                                     "from": {"id": 999},
                                                     "message": {"chat": {"id": 999}}}},
            ]}
    monkeypatch.setattr(telegram_channel.requests, "post", lambda *a, **kw: R())
    events, off = tg.poll(0, timeout=5)
    assert off == 12
    assert events[0]["kind"] == "text" and tg.is_trusted(events[0])
    assert events[1]["kind"] == "callback" and not tg.is_trusted(events[1])


def test_bottoni_senza_approve_non_hanno_approva():
    b = telegram_channel.Telegram.action_buttons("req_1", "it", can_approve=False)
    labels = [x["text"] for x in b[0]]
    assert not any("Approva" in l for l in labels)
    assert any("Rifiuta" in l for l in labels) and any("Modifica" in l for l in labels)
    b = telegram_channel.Telegram.action_buttons("req_1", "en", can_approve=True)
    assert b[0][0]["callback_data"] == "a:req_1"


# ------------------------------------------------------------- flussi

def test_semi_notifica_con_bottoni(world):
    _rule()
    world["unread"] = [_msg()]
    watcher_mod.Watcher().tick()
    assert len(world["tg"].sent) == 1
    btns = world["tg"].sent[0]["buttons"][0]
    assert [b["callback_data"][:2] for b in btns] == ["a:", "r:", "m:"]


def test_tap_approva_invia(world):
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    assert len(world["replies"]) == 1
    rec = policy.store().get(rid)
    assert rec["status"] == policy.EXECUTED
    assert rec["decided_by"] == f"telegram:{CHAT}"
    assert "✅" in world["tg"].sent[-1]["text"]


def test_tap_rifiuta_non_invia(world):
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_cb(f"r:{rid}"))
    assert world["replies"] == []
    assert policy.store().get(rid)["status"] == policy.REJECTED
    assert "❌" in world["tg"].sent[-1]["text"]


def test_modifica_rifa_la_bozza_col_feedback(world):
    rid_rule = _rule(mode="auto")  # anche su regola auto, il retry e' semi
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    prompts = []
    import ade_mail_agent.agent_bridge as ab
    orig = ab.run
    ab.run = lambda prompt, **kw: prompts.append(prompt) or "Bozza due"
    try:
        w.handle_telegram_event(world["tg"], _ev_cb(f"m:{rid}"))
        assert "✏️" in world["tg"].sent[-1]["text"]
        w.handle_telegram_event(world["tg"], _ev_text("piu' breve e con il prezzo"))
    finally:
        ab.run = orig
    # la vecchia richiesta e' rifiutata, ne esiste una nuova pending
    assert policy.store().get(rid)["status"] == policy.REJECTED
    pend = policy.store().list_pending()
    assert len(pend) == 1 and pend[0]["preview"]["body"] == "Bozza due"
    assert pend[0]["preview"]["rule_mode"] == "semi"
    assert world["replies"] == []  # niente inviato da solo
    # il feedback e la bozza precedente sono nel prompt del drafter
    assert "piu' breve e con il prezzo" in prompts[-1]
    assert "Bozza uno" in prompts[-1]


def test_rifiuta_con_testo_in_un_colpo(world):
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    world["draft"] = "Bozza tre"
    w.handle_telegram_event(world["tg"], _ev_text(f"rifiuta {rid}: formale"))
    assert policy.store().get(rid)["status"] == policy.REJECTED
    assert policy.store().list_pending()[0]["preview"]["body"] == "Bozza tre"


def test_chat_sconosciuta_ignorata_e_auditata(world):
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}", chat=999, frm=999))
    # stessa chat ma premuto da un altro utente (gruppo): no
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}", chat=CHAT, frm=42))
    assert policy.store().get(rid)["status"] == policy.PENDING
    assert world["replies"] == []
    with open(policy._audit_path(), encoding="utf-8") as f:
        outs = [json.loads(l)["outcome"] for l in f if l.strip()]
    assert outs.count("telegram_unauthorized") >= 2


def test_approve_disabilitato_rifiuta_il_si(world):
    world["tg"].approve_enabled = False
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_text(f"approva {rid}"))
    assert policy.store().get(rid)["status"] == policy.PENDING
    assert world["replies"] == []
    assert "Hello" in world["tg"].sent[-1]["text"]


def test_comando_sconosciuto_spiega(world):
    w = watcher_mod.Watcher()
    w.handle_telegram_event(world["tg"], _ev_text("ciao bot"))
    assert "approva" in world["tg"].sent[-1]["text"].lower()


# ------------------------------------------ chat fidata (u/Secondmindsystems)

def test_approva_richiede_chat_fidata_registrata(world):
    """approve=True in notify.json non basta: serve il kv scritto dietro
    Hello al setup. Senza, il si' da Telegram viene rifiutato."""
    rules_mod.store().kv_set("tg_trusted_chat", "")  # setup mai fatto
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    assert world["replies"] == []
    assert policy.store().get(rid)["status"] == policy.PENDING
    rules_mod.store().kv_set("tg_trusted_chat", str(CHAT))
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    assert len(world["replies"]) == 1


def test_cambio_chat_revoca_le_pending(world):
    """notify.json riscritto con un'altra chat: le pending del watcher
    vengono revocate, la vecchia chat fidata riceve l'avviso, una volta."""
    rules_mod.store().kv_set("tg_trusted_chat", "555")  # fidata = 555
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    alerts = []
    world["tg"].send_to = lambda chat, text: alerts.append((chat, text)) or True
    w.check_telegram_trust(world["tg"])
    assert policy.store().get(rid)["status"] == policy.REJECTED
    assert policy.store().get(rid)["decided_by"] == "system:telegram-chat-changed"
    assert alerts and alerts[0][0] == 555
    # e il si' dalla chat nuova non passa comunque
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    assert world["replies"] == []
    # l'avviso non si ripete
    w.check_telegram_trust(world["tg"])
    assert len(alerts) == 1


def test_indirizzi_non_diventano_link_tappabili():
    """Regressione, vista dal vivo su Telegram: senza parse_mode Telegram
    linkifica da solo l'indirizzo nel testo, e in un messaggio senza
    bottoni l'UNICA cosa premibile diventava il mailto: del destinatario —
    che sul telefono apre il client di posta e chiede un login. Ora
    indirizzi e URL vanno in <code>, che Telegram non tocca."""
    h = telegram_channel.Telegram.safe_html(
        "GigaMail: send_mail in attesa — to=manuela.fomiatti@gmail.com; "
        "vedi https://esempio.it/x")
    assert "<code>manuela.fomiatti@gmail.com</code>" in h
    assert "<code>https://esempio.it/x</code>" in h
    # e il testo resta innocuo se contiene HTML
    assert "&lt;b&gt;" in telegram_channel.Telegram.safe_html("<b>x</b>")


def test_approvazione_di_un_tool_ha_i_bottoni(monkeypatch):
    """I messaggi Telegram delle richieste nate da un tool arrivavano
    muti: require_approval passava gli actions della toast ma non i
    buttons di Telegram."""
    from ade_mail_agent import policy
    monkeypatch.setattr(telegram_channel, "channel", lambda: FakeTG())
    b = policy.telegram_buttons("req_abc123")
    assert b is not None
    azioni = [x["callback_data"] for riga in b for x in riga]
    assert azioni == ["a:req_abc123", "r:req_abc123", "m:req_abc123"]
