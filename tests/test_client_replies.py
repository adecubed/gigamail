"""Client replies on followed threads: the alert also reaches the desktop,
and when the client names one free time the confirmation is drafted at
once, for approval.

A client wrote "would Friday the 9th at 17:00 work?". The alert went to
Telegram only, and nothing was drafted: the user had to ask for the reply
by hand, from the phone.
"""
import pytest

from gigamail import agent_bridge, cli, policy
from gigamail import watcher as watcher_mod
from gigamail.core import appointments, desktop_notify, mail_router, telegram_channel
from gigamail.core import rules as rules_mod
from gigamail.watcher import tg_risposte

CHAT = 123456789

MAIL = {"id": "4100", "subject": "Re: Trilocale in Via Roma 10",
        "from": {"emailAddress": {"address": "anna.verdi@example.com",
                                  "name": "Anna Verdi"}},
        "body_text": "Buongiorno, andrebbe bene venerdi' 9 alle 17?"}

FREE_TIME = {"stato": "proposto", "inizio": "2026-10-09T17:00",
             "fine": "2026-10-09T18:00", "con": "Anna Verdi",
             "scelta_unica": True, "accetta": False}


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

    action_buttons = staticmethod(telegram_channel.Telegram.action_buttons)
    is_trusted = telegram_channel.Telegram.is_trusted


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    w = {"tg": FakeTG(), "toasts": [], "prompts": [], "notified": [],
         "draft": "Gentile Sig.ra Verdi, le confermo venerdi' 9 alle 17:00."}
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: dict(MAIL) if str(kw.get("message_id")) == "4100" else {})
    monkeypatch.setattr(agent_bridge, "run",
                        lambda prompt, **kw: w["prompts"].append(prompt) or w["draft"])
    monkeypatch.setattr(tg_risposte, "_cc", lambda aid: ["office@example.com"])
    monkeypatch.setattr(desktop_notify, "notify",
                        lambda title, body, **kw: w["toasts"].append(
                            {"body": body, "actions": kw.get("actions")}) or True)
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda rid, tool, preview, **kw: w["notified"].append(
                            {"rid": rid, "buttons": kw.get("buttons")}) or True)
    monkeypatch.setattr(appointments, "libero", lambda start, end, escludi="": True)
    yield w
    policy.set_store(None)
    rules_mod.set_store(None)


def _requests():
    return [r for r in rules_mod.store().pending_requests()
            if r["rule_id"] == tg_risposte.RULE_ID]


# ── the alert on the desktop ─────────────────────────────────────────

def test_the_alert_reaches_the_desktop_with_a_reply_button(world):
    key = tg_risposte.register_context(2, MAIL)
    tg_risposte.notify_desktop("Anna Verdi:\n«andrebbe bene venerdi' 9?»", key)
    toast = world["toasts"][-1]
    assert "Anna Verdi" in toast["body"]
    assert toast["actions"] == [("Rispondi", f"gigamail://reply/{key}")]
    assert desktop_notify._toast_tag(toast["actions"]) == f"reply_{key}"


def test_the_reply_button_queues_the_instruction_for_the_watcher(world, monkeypatch):
    key = tg_risposte.register_context(2, MAIL)
    answers = iter(["ok, va bene", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert cli.cmd_open_url(type("A", (), {"url": f"gigamail://reply/{key}"})()) == 0
    assert _requests() == []                       # nothing drafted in the CLI
    assert tg_risposte.process_desktop_queue(None, None) == 1
    [req] = _requests()
    rec = policy.store().get(req["request_id"])
    assert rec["args"]["to"] == "anna.verdi@example.com"
    assert rec["args"]["body"] == world["draft"]
    assert "ok, va bene" in world["prompts"][-1]
    assert tg_risposte.process_desktop_queue(None, None) == 0   # taken once


def test_an_unknown_alert_queues_nothing():
    assert not tg_risposte.queue_desktop_reply("deadbeef", "ok")


def test_edit_from_the_desktop_redrafts_a_reply(world):
    key = tg_risposte.register_context(2, MAIL)
    old = tg_risposte.rispondi(None, world["tg"], key, "ok, va bene")
    assert policy.store().revoke(old, by="cli:test edit")
    assert cli._retry_di_regola(old, "piu' breve")
    world["draft"] = "Gentile Sig.ra Verdi, a venerdi'."
    assert tg_risposte.process_desktop_queue(None, world["tg"]) == 1
    new = [r["request_id"] for r in _requests() if r["request_id"] != old]
    assert len(new) == 1
    assert policy.store().get(new[0])["args"]["body"] == "Gentile Sig.ra Verdi, a venerdi'."
    assert "piu' breve" in world["prompts"][-1]


# ── the confirmation drafted at once ─────────────────────────────────

def test_a_free_time_named_by_the_client_gets_a_confirmation_draft(world):
    rid = tg_risposte.draft_confirmation(None, world["tg"], 2, {}, MAIL, FREE_TIME)
    assert rid
    assert policy.store().get(rid)["args"]["body"] == world["draft"]
    assert "Confirm the appointment" in world["prompts"][-1]
    assert "at our office" in world["prompts"][-1]
    assert world["notified"][-1]["rid"] == rid
    assert not any("Scrivo la risposta" in m["text"] for m in world["tg"].sent)
    # the same mail never gets a second draft
    assert tg_risposte.draft_confirmation(None, world["tg"], 2, {}, MAIL, FREE_TIME) is None


def test_without_telegram_the_draft_still_comes(world):
    rid = tg_risposte.draft_confirmation(None, None, 2, {"video": 1}, MAIL, FREE_TIME)
    assert rid
    assert world["notified"][-1]["buttons"] is None
    assert "by video call" in world["prompts"][-1]


@pytest.mark.parametrize("outcome", [
    dict(FREE_TIME, scelta_unica=False),               # several times offered
    dict(FREE_TIME, occupato=True),                    # busy
    dict(FREE_TIME, agenda_illeggibile=True),          # calendar unreadable
    {"stato": "disdetto"},
    {"stato": "nessuno"},
])
def test_no_draft_when_the_time_is_not_one_free_slot(world, outcome):
    assert tg_risposte.draft_confirmation(None, world["tg"], 2, {}, MAIL, outcome) is None
    assert world["prompts"] == []


def test_no_draft_when_the_calendar_says_busy(world, monkeypatch):
    monkeypatch.setattr(appointments, "libero", lambda start, end, escludi="": False)
    assert tg_risposte.draft_confirmation(None, world["tg"], 2, {}, MAIL, FREE_TIME) is None


def test_an_accepted_offered_time_gets_a_confirmation_draft(world):
    accepted = dict(FREE_TIME, stato="confermato", accetta=True)
    assert tg_risposte.draft_confirmation(
        None, world["tg"], 2, {}, MAIL, accepted, touched={"event_id": "ev-1"})
    # a repeated confirmation ("thanks, see you then") is not answered again
    world["prompts"].clear()
    again = dict(MAIL, id="4101")
    assert tg_risposte.draft_confirmation(
        None, world["tg"], 2, {}, again, accepted,
        touched={"event_id": "ev-1", "invariato": True}) is None


# ── wired into the watcher sweep ─────────────────────────────────────

def test_the_sweep_alerts_the_desktop_and_drafts_the_confirmation(world, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "appointments")
    monkeypatch.setattr(telegram_channel, "channel", lambda: world["tg"])
    monkeypatch.setattr(appointments, "store", lambda: type("S", (), {
        "aperti": lambda self, *a: [{"account_id": 2, "thread_key": "k"}]})())
    monkeypatch.setattr(appointments, "retry_pending_reads", lambda: 0, raising=False)
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: [dict(MAIL)])

    def fake_sweep(account_id, messages, corpo_di=None, avvisa=None, **kw):
        avvisa({"thread_key": "k"}, messages[0], MAIL["body_text"], FREE_TIME, None)
        return 0
    monkeypatch.setattr(appointments, "sweep", fake_sweep)
    w = watcher_mod.Watcher(interval=60)
    monkeypatch.setattr(w, "heartbeat", lambda: None)
    w.sweep_appointments()
    assert any(t["actions"] and t["actions"][0][1].startswith("gigamail://reply/")
               for t in world["toasts"])
    assert len(_requests()) == 1


# ── the kv helpers the queue relies on ───────────────────────────────

def test_kv_keys_and_delete():
    rs = rules_mod.store()
    rs.kv_set("desktop_reply_1", "a")
    rs.kv_set("desktop_reply_2", "b")
    rs.kv_set("desktopXreply_3", "c")              # "_" is not a wildcard
    assert rs.kv_keys("desktop_reply_") == ["desktop_reply_1", "desktop_reply_2"]
    assert rs.kv_delete("desktop_reply_1")
    assert not rs.kv_delete("desktop_reply_1")
