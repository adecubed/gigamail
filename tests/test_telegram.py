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
        self.cleared = []
        self.deleted = []

    def send(self, text, buttons=None, html=False):
        self.sent.append({"text": text, "buttons": buttons, "html": html})
        return True

    def answer_callback(self, cid, text=""):
        self.answered.append(cid)

    def clear_buttons(self, message_id):
        self.cleared.append(message_id)
        return True

    def delete_message(self, message_id):
        self.deleted.append(message_id)
        return True

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


def _ev_cb(data, chat=CHAT, frm=None, message_id=777):
    return {"kind": "callback", "chat_id": chat, "from_id": frm or chat,
            "data": data, "callback_id": "cb1", "message_id": message_id}


def _ev_text(text, chat=CHAT, frm=None, message_id=555):
    return {"kind": "text", "chat_id": chat, "from_id": frm or chat,
            "text": text, "message_id": message_id}


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


def test_su_telegram_si_vede_la_mail_intera():
    """La toast puo' restare corta perche' ha il bottone Leggi; Telegram
    quel secondo passo non ce l'ha. Se il corpo non e' nel messaggio si
    finisce ad approvare una mail di cui si e' letto solo l'oggetto."""
    from ade_mail_agent import policy
    preview = {
        "from": "info@20128milano.it", "to": "sam@euronext.com",
        "cc": ["info@fingroupspa.com"], "subject": "Re: Appuntamento",
        "attachments": [{"name": "B.1.3.pdf"}],
        "body": "Gentile Sig. Sam,\n\ndisponibilita' attuale: ...\n\nCordiali saluti",
    }
    t = policy.full_preview_text("send_mail", preview)
    assert "Da: info@20128milano.it" in t
    assert "A: sam@euronext.com" in t
    assert "Cc: info@fingroupspa.com" in t
    assert "Oggetto: Re: Appuntamento" in t
    assert "B.1.3.pdf" in t
    assert "Gentile Sig. Sam," in t and "Cordiali saluti" in t


def test_il_corpo_lungo_viene_troncato_ma_dichiarato():
    """Telegram taglia a 4096: meglio dire che manca un pezzo che farlo
    sparire in silenzio."""
    from ade_mail_agent import policy
    t = policy.full_preview_text(
        "send_mail", {"to": "a@x.it", "subject": "s", "body": "x" * 9000})
    assert len(t) < 4096
    assert "troncato" in t or "truncated" in t


def test_senza_corpo_resta_il_riassunto():
    from ade_mail_agent import policy
    t = policy.full_preview_text("delete_message", {"action": "elimina"})
    assert "action=elimina" in t


def test_una_richiesta_scaduta_non_e_una_gia_decisa(world):
    """Il messaggio diceva "gia' decisa o scaduta (pending)": decisa e
    pending nella stessa frase, e chi legge non capisce cosa sia
    successo. Sono due casi diversi e vanno detti diversi."""
    import time as _t
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()

    # la faccio scadere senza che nessuno l'abbia decisa
    store = policy.store()
    with store._conn() as conn:
        conn.execute("UPDATE approvals SET expires_at=? WHERE request_id=?",
                     (_t.time() - 60, rid))
    assert store.get(rid)["expired"] is True

    w.handle_telegram_event(world["tg"], _ev_cb(f"m:{rid}"))
    detto = world["tg"].sent[-1]["text"]
    assert "scaduta" in detto and "Niente e' partito" in detto
    assert "gia' decisa" not in detto
    assert policy.store().get(rid)["status"] == policy.PENDING  # mai decisa


def test_i_bottoni_spariscono_quando_non_servono_piu(world):
    """Una richiesta vive 15 minuti, il messaggio Telegram resta in chat
    per sempre: senza togliere la tastiera si continua a premerla e a
    farsi rispondere di no. Il tap porta con se' il message_id, quindi i
    bottoni spariscono la prima volta che scopri che e' morta."""
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()

    w.handle_telegram_event(world["tg"], _ev_cb(f"r:{rid}", message_id=999))
    assert world["tg"].cleared == [999]          # decisa: via i bottoni

    world["tg"].cleared.clear()
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}", message_id=999))
    assert world["tg"].cleared == [999]          # gia' decisa: idem


def test_il_log_non_dichiara_attiva_un_approvazione_spenta(world, monkeypatch, capsys):
    """notify.json con approve:true ma nessuna chat registrata dietro
    Hello = approvazione SPENTA. Il watcher scriveva comunque "Telegram
    con approvazione", e lo scoprivi solo premendo Approva e vedendoti
    rispondere di no."""
    from ade_mail_agent.core import rules as rules_mod
    rs = rules_mod.store()
    rs.kv_set("tg_trusted_chat", "")          # mai registrata
    w = watcher_mod.Watcher()
    w.run(once=True)
    out = capsys.readouterr().out
    assert "Telegram senza approvazione" in out
    assert "gigamail telegram setup --approve" in out

    # registrata: torna "con", e nessun avviso
    rs.kv_set("tg_trusted_chat", str(CHAT))
    w.run(once=True)
    out = capsys.readouterr().out
    assert "Telegram con approvazione" in out
    assert "ATTENZIONE" not in out


def _con_pin(pin="739104"):
    from ade_mail_agent.core import approval_pin, rules as rules_mod
    rs = rules_mod.store()
    rs.kv_set("tg_approve_pin", approval_pin.hash_pin(pin))
    rs.kv_set("tg_pin_fails", "0")
    rs.kv_set("tg_pin_locked_until", "0")
    rs.kv_set("tg_trusted_chat", str(CHAT))
    return rs


def test_col_pin_il_tap_da_solo_non_approva(world):
    """Il punto della funzione: avere il telefono sbloccato non basta piu'."""
    rs = _con_pin()
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()

    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    assert policy.store().get(rid)["status"] == policy.PENDING   # non approvata
    assert world["replies"] == []                                # niente inviato
    assert "PIN" in world["tg"].sent[-1]["text"]
    assert rs.kv_get("tg_await_pin") == rid


def test_il_pin_giusto_approva_e_il_messaggio_sparisce(world):
    _con_pin()
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    w.handle_telegram_event(world["tg"], _ev_text("739104", message_id=42))

    assert policy.store().get(rid)["status"] in (policy.APPROVED, policy.EXECUTED)
    assert 42 in world["tg"].deleted        # il PIN non resta in cronologia
    assert len(world["replies"]) == 1


def test_tre_pin_sbagliati_bloccano_e_non_inviano(world):
    """Uno spazio di PIN e' minuscolo: senza blocco lo si indovina a tentativi."""
    rs = _con_pin()
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()

    for tentativo in ("000000", "111222", "987654"):
        w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
        w.handle_telegram_event(world["tg"], _ev_text(tentativo))

    assert policy.store().get(rid)["status"] == policy.PENDING
    assert world["replies"] == []
    assert float(rs.kv_get("tg_pin_locked_until", "0")) > 0
    assert "bloccata" in world["tg"].sent[-1]["text"]

    # e da bloccato nemmeno il PIN giusto passa
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    assert "bloccata" in world["tg"].sent[-1]["text"]
    assert rs.kv_get("tg_await_pin", "") == ""


def test_il_pin_sbagliato_viene_cancellato_comunque(world):
    """Anche un PIN errato e' un tentativo di segreto: non deve restare
    scritto in chat."""
    _con_pin()
    _rule()
    world["unread"] = [_msg()]
    w = watcher_mod.Watcher()
    w.tick()
    rid = _pending_id()
    w.handle_telegram_event(world["tg"], _ev_cb(f"a:{rid}"))
    w.handle_telegram_event(world["tg"], _ev_text("000000", message_id=77))
    assert 77 in world["tg"].deleted
