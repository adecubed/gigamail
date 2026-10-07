"""After an appointment GigaMail asks how it went, writes it into the
contact's notes and, seven days later, prepares the follow-up for
approval.

Three clients seen in the office the week before were still waiting for a
line, and nothing recorded what had been discussed at the meetings.
"""
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from gigamail import agent_bridge, cli, policy
from gigamail.core import (
    appointments,
    archivio,
    calendar_router,
    desktop_notify,
    mail_memory,
    mail_router,
    telegram_channel,
)
from gigamail.core import rules as rules_mod
from gigamail.watcher import after_appointment as after
from gigamail.watcher import drafting, execution, tg_risposte
from gigamail.watcher import telegram as tgmod

CHAT = 123456789
CONTACT = "mario.rossi@example.com"
SUBJECT = ("Nuovo messaggio di Mario Rossi sul tuo immobile, Trilocale "
           "in Via Roma, 10, Milano")
START = datetime(2026, 9, 22, 17, 0)          # a Tuesday


class FakeTG:
    def __init__(self):
        self.chat_id = CHAT
        self.approve_enabled = True
        self.sent = []
        self.cleared = []
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
        self.cleared.append(message_id)
        return True

    def delete_message(self, message_id):
        return True

    action_buttons = staticmethod(telegram_channel.Telegram.action_buttons)
    safe_html = staticmethod(telegram_channel.Telegram.safe_html)
    is_trusted = telegram_channel.Telegram.is_trusted


def _mime(sender, to, subject, body, when):
    m = EmailMessage()
    m["Message-ID"] = f"<{when.timestamp()}@test>"
    m["From"], m["To"], m["Subject"] = sender, to, subject
    m["Date"] = format_datetime(when.astimezone())
    m.set_content(body)
    return m.as_bytes()


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    appointments.set_store(appointments.AppointmentStore(tmp_path / "app.db"))
    archivio.set_store(archivio.ArchiveStore(tmp_path / "arch.db", tmp_path / "mail"))
    monkeypatch.setattr(mail_memory, "_DB_PATH", str(tmp_path / "mem.db"))
    mail_memory.init_db()
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "appointments")
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    tg = FakeTG()
    monkeypatch.setattr(telegram_channel, "channel", lambda: tg)
    w = {"tg": tg, "events": [{"id": "ev-1"}], "prompts": [], "sent": [],
         "toasts": [], "draft": "Gentile Sig. Rossi, grazie ancora per la visita."}
    monkeypatch.setattr(calendar_router, "get_events",
                        lambda **kw: list(w["events"]))
    monkeypatch.setattr(agent_bridge, "run",
                        lambda prompt, **kw: w["prompts"].append(prompt) or w["draft"])
    monkeypatch.setattr(tg_risposte, "_cc", lambda aid: ["office@example.com"])
    monkeypatch.setattr(tg_risposte, "_doc_paths", lambda aid: [])
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda rid, tool, preview, **kw: tg.send(
                            kw.get("message") or "", kw.get("buttons")) or True)
    monkeypatch.setattr(mail_router, "reply_message",
                        lambda **kw: w["sent"].append(kw) or {"success": True})
    monkeypatch.setattr(desktop_notify, "notify",
                        lambda title, body, **kw: w["toasts"].append(
                            {"body": body, "actions": kw.get("actions")}) or True)
    rules_mod.store().kv_set("tg_trusted_chat", str(CHAT))
    # The contact's mail the follow-up will reply to.
    archivio.store().salva(2, _mime(
        f"Mario Rossi <{CONTACT}>", "sales@example.com", f"Re: {SUBJECT}",
        "Martedi' 22 alle 17:00 mi va bene.", datetime(2026, 9, 17, 11, 40)),
        folder="INBOX")
    yield w
    policy.set_store(None)
    rules_mod.set_store(None)
    appointments.set_store(None)
    archivio.set_store(None)


def _confirmed(start=START, event_id="ev-1"):
    appointments.store().upsert(
        2, appointments.thread_key(SUBJECT, CONTACT), event_id, "confermato",
        start.isoformat(timespec="minutes"),
        (start + timedelta(hours=1)).isoformat(timespec="minutes"),
        "Mario Rossi")


def _questions(tg):
    return [m for m in tg.sent if m["buttons"] and
            str(m["buttons"][0][0].get("callback_data", "")).startswith("d:")]


def _callback(data, message_id=1):
    return {"kind": "callback", "chat_id": CHAT, "from_id": CHAT, "data": data,
            "callback_id": "c1", "message_id": message_id}


def _text(text, reply_to=0):
    return {"kind": "text", "chat_id": CHAT, "from_id": CHAT, "text": text,
            "message_id": 2, "reply_to": reply_to}


def _answer(world, code):
    q = _questions(world["tg"])[-1]
    key = q["buttons"][0][0]["callback_data"].split(":")[1]
    tgmod.handle_event(None, world["tg"], _callback(f"d:{key}:{code}", q["id"]))
    return key, q


def _outcome(key):
    return appointments.store().outcome_by_key(key)


# ── the question ─────────────────────────────────────────────────────

def test_asks_how_it_went_an_hour_after_the_start(world):
    _confirmed()
    after.tick(None, now=START + timedelta(minutes=59))
    assert _questions(world["tg"]) == []
    after.tick(None, now=START + timedelta(minutes=61))
    questions = _questions(world["tg"])
    assert len(questions) == 1
    assert "Mario Rossi" in questions[0]["text"]
    assert [b["callback_data"][-1] for b in questions[0]["buttons"][0]] == ["s", "n", "p"]
    after.tick(None, now=START + timedelta(minutes=90))
    assert len(_questions(world["tg"])) == 1          # asked once


def test_old_or_removed_appointments_are_not_asked_about(world):
    _confirmed(start=START - timedelta(days=5))
    after.tick(None, now=START + timedelta(hours=2))
    assert _questions(world["tg"]) == []
    _confirmed()
    world["events"].clear()                            # removed by hand
    after.tick(None, now=START + timedelta(hours=2))
    assert _questions(world["tg"]) == []
    row = appointments.store().outcome_get(
        2, appointments.thread_key(SUBJECT, CONTACT), START.isoformat(timespec="minutes"))
    assert row["outcome"] == "removed"


def test_an_event_recreated_by_hand_still_counts(world):
    """An event recreated in the calendar with a note has a new id; it is
    still there at the same time, and the question must go out."""
    _confirmed()
    world["events"][:] = [{"id": "ev-recreated",
                           "start": {"dateTime": "2026-09-22T17:00:00.0000000",
                                     "timeZone": "Europe/Rome"}}]
    after.tick(None, now=START + timedelta(hours=2))
    assert len(_questions(world["tg"])) == 1


def test_showed_up_goes_into_the_contact_notes(world):
    _confirmed()
    after.tick(None, now=START + timedelta(hours=1, minutes=5))
    key, q = _answer(world, "s")
    assert q["id"] in world["tg"].cleared
    assert "si e' presentato" in mail_memory.client_notes(CONTACT)
    tgmod.handle_event(None, world["tg"], _text("Interessato all'A.2, deve sentire la banca"))
    assert "A.2, deve sentire la banca" in mail_memory.client_notes(CONTACT)
    # Replying to the question later adds more notes.
    tgmod.handle_event(None, world["tg"], _text("Viene con la compagna Laura",
                                                reply_to=q["id"]))
    assert "compagna Laura" in mail_memory.client_notes(CONTACT)
    outcome = _outcome(key)
    assert outcome["outcome"] == "showed_up"
    assert outcome["followup_state"] == "due"
    assert outcome["followup_due"] == datetime(2026, 9, 29, 10, 0).timestamp()


def test_the_first_telegram_button_codes_still_work(world):
    _confirmed()
    after.tick(None, now=START + timedelta(hours=1, minutes=5))
    key, _ = _answer(world, "v")
    assert _outcome(key)["outcome"] == "showed_up"


def test_no_show_means_no_follow_up(world):
    _confirmed()
    after.tick(None, now=START + timedelta(hours=1, minutes=5))
    key, _ = _answer(world, "n")
    assert "NON si e' presentato" in mail_memory.client_notes(CONTACT)
    assert _outcome(key)["followup_state"] == ""
    assert after.tick(None, now=START + timedelta(days=8)) == 0


def test_the_follow_up_falls_on_a_weekday():
    friday = datetime(2026, 9, 25, 17, 30)
    assert after.followup_due(friday) == datetime(2026, 10, 2, 10, 0)
    saturday = datetime(2026, 9, 26, 11, 0)
    assert after.followup_due(saturday) == datetime(2026, 10, 5, 10, 0)


# ── the follow-up ────────────────────────────────────────────────────

def _showed_up(world, notes="Interessato all'A.2"):
    _confirmed()
    after.tick(None, now=START + timedelta(hours=1, minutes=5))
    key, _ = _answer(world, "s")
    tgmod.handle_event(None, world["tg"], _text(notes))
    return key


def test_the_follow_up_comes_seven_days_later_from_the_notes(world):
    key = _showed_up(world)
    assert after.tick(None, now=datetime(2026, 9, 29, 9, 59)) == 0
    assert after.tick(None, now=datetime(2026, 9, 29, 10, 1)) == 1
    outcome = _outcome(key)
    assert outcome["followup_state"] == "awaiting_approval"
    rec = policy.store().get(outcome["followup_request_id"])
    assert rec["args"]["body"] == world["draft"]
    assert rec["args"]["message_id"].startswith(archivio.PREFISSO_ID)
    assert rec["args"]["cc"] == ["office@example.com"]
    handled = rules_mod.store().find_by_request(outcome["followup_request_id"])
    assert handled["rule_id"] == after.RULE_ID
    assert "Interessato all'A.2" in world["prompts"][-1]
    assert "Follow-up per Mario Rossi" in world["tg"].sent[-1]["text"]
    assert after.tick(None, now=datetime(2026, 9, 29, 11, 0)) == 0   # once


def test_no_follow_up_when_you_already_wrote_to_each_other(world):
    key = _showed_up(world)
    archivio.store().salva(2, _mime(
        "sales@example.com", CONTACT, f"Re: {SUBJECT}",
        "Le mando le planimetrie che abbiamo visto.", datetime(2026, 9, 24, 9, 0)),
        folder="INBOX.Sent")
    assert after.tick(None, now=datetime(2026, 9, 29, 10, 1)) == 0
    assert _outcome(key)["followup_state"] == "skipped"
    assert "vi siete gia' scritti" in world["tg"].sent[-1]["text"]
    assert world["prompts"] == []                     # no agent run


def test_an_approved_follow_up_is_sent_and_noted(world):
    key = _showed_up(world)
    after.tick(None, now=datetime(2026, 9, 29, 10, 1))
    rid = _outcome(key)["followup_request_id"]
    assert policy.store().approve(rid, by="test")
    assert execution.execute_approved(type("W", (), {"verbose": False})()) == 1
    assert world["sent"][0]["body"] == world["draft"]
    after.update_followups()
    assert _outcome(key)["followup_state"] == "sent"
    assert "follow-up inviato" in mail_memory.client_notes(CONTACT)


def test_the_follow_up_carries_the_account_signature(world, account_signature):
    account_signature(2, "Sales office")
    key = _showed_up(world)
    after.tick(None, now=datetime(2026, 9, 29, 10, 1))
    rec = policy.store().get(_outcome(key)["followup_request_id"])
    assert rec["args"]["body"] == world["draft"] + "\n\nSales office\n"
    assert rec["preview"]["body"] == rec["args"]["body"]
    assert "Sales office" in world["tg"].sent[-1]["text"]


def test_edit_from_telegram_rewrites_the_follow_up(world):
    key = _showed_up(world)
    after.tick(None, now=datetime(2026, 9, 29, 10, 1))
    old = _outcome(key)["followup_request_id"]
    world["draft"] = "Gentile Sig. Rossi, versione piu' breve."
    tgmod.retry(None, world["tg"], old, "piu' breve", rules_mod.store())
    assert policy.store().get(old)["status"] == policy.REJECTED
    new = _outcome(key)["followup_request_id"]
    assert new != old
    assert policy.store().get(new)["args"]["body"].endswith("versione piu' breve.")
    assert "piu' breve" in world["prompts"][-1]
    assert "PREVIOUS DRAFT" in world["prompts"][-1]


# ── on the desktop too ───────────────────────────────────────────────

def _outcome_toasts(world):
    return [t for t in world["toasts"] if t["actions"]
            and t["actions"][0][1].startswith("gigamail://outcome/")]


def test_the_question_also_reaches_the_desktop(world):
    _confirmed()
    after.tick(None, now=START + timedelta(minutes=61))
    toasts = _outcome_toasts(world)
    assert len(toasts) == 1
    assert "Mario Rossi" in toasts[0]["body"]
    key = _questions(world["tg"])[0]["buttons"][0][0]["callback_data"].split(":")[1]
    # clicking the notification opens the question, the buttons answer it
    assert [u for _, u in toasts[0]["actions"]] == [
        f"gigamail://outcome/{key}", f"gigamail://outcome/{key}/s",
        f"gigamail://outcome/{key}/n", f"gigamail://outcome/{key}/p"]
    assert desktop_notify._toast_tag(toasts[0]["actions"]) == f"outcome_{key}"


def test_without_telegram_the_question_still_goes_out(world, monkeypatch):
    monkeypatch.setattr(telegram_channel, "channel", lambda: None)
    _confirmed()
    assert after.tick(None, now=START + timedelta(minutes=61)) == 1
    assert len(_outcome_toasts(world)) == 1
    assert len(after.unanswered()) == 1


def test_the_notification_button_records_and_asks_for_notes(world, monkeypatch):
    _confirmed()
    after.tick(None, now=START + timedelta(minutes=61))
    url = _outcome_toasts(world)[0]["actions"][1][1]          # .../s
    answers = iter(["Vuole l'A.2 con box", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert cli.cmd_open_url(type("A", (), {"url": url})()) == 0
    notes = mail_memory.client_notes(CONTACT)
    assert "si e' presentato" in notes and "Vuole l'A.2 con box" in notes
    assert after.unanswered() == []
    assert len(_questions(world["tg"])) == 1   # Telegram does not ask again


def test_gigamail_debrief_asks_the_unanswered_ones(world, monkeypatch):
    monkeypatch.setattr(telegram_channel, "channel", lambda: None)
    _confirmed()
    after.tick(None, now=START + timedelta(minutes=61))
    answers = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert cli.main(["debrief"]) == 0
    assert "NON si e' presentato" in mail_memory.client_notes(CONTACT)
    assert after.unanswered() == []


def test_edit_from_the_desktop_rewrites_the_follow_up(world):
    key = _showed_up(world)
    after.tick(None, now=datetime(2026, 9, 29, 10, 1))
    old = _outcome(key)["followup_request_id"]
    assert policy.store().revoke(old, by="cli:test edit: shorter")
    assert cli._retry_di_regola(old, "piu' breve")
    world["draft"] = "Gentile Sig. Rossi, breve."
    assert after.tick(None, now=datetime.now()) == 1
    new = _outcome(key)["followup_request_id"]
    assert new != old
    assert policy.store().get(new)["args"]["body"] == "Gentile Sig. Rossi, breve."
    assert "piu' breve" in world["prompts"][-1]


# ── the notes also serve ordinary drafts ─────────────────────────────

def test_the_reply_draft_reads_the_contact_notes(world):
    mail_memory.add_note(CONTACT, "22/09 — interessato all'A.2, vuole il box")
    msg = {"id": "1", "subject": f"Re: {SUBJECT}",
           "from": {"emailAddress": {"name": "Mario", "address": CONTACT}},
           "body_text": "Buongiorno, ci sono novita'?"}
    prompt = drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 2, msg)
    assert "THE USER'S NOTES ON THIS CONTACT" in prompt
    assert "vuole il box" in prompt


def test_notes_accumulate():
    mail_memory.add_note(CONTACT, "first")
    mail_memory.add_note(CONTACT, "second")
    assert mail_memory.client_notes(CONTACT) == "first\nsecond"


# ── the one-day Italian table moves over ─────────────────────────────

def test_rows_of_the_italian_table_are_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE esiti (account_id INTEGER, thread_key TEXT, inizio TEXT,"
            " con TEXT, video INTEGER, chiave TEXT, chiesto_il REAL, esito TEXT,"
            " note TEXT, risposto_il REAL, followup_dal REAL, followup_stato TEXT,"
            " followup_rid TEXT)")
        conn.execute("INSERT INTO esiti VALUES (2,'a@example.com|x','2026-09-30T18:00',"
                     "'Anna',0,'0123abcd',1.0,'presentato','',2.0,3.0,'da_fare','')")
    store = appointments.AppointmentStore(path)
    row = store.outcome_by_key("0123abcd")
    assert row["outcome"] == "showed_up"
    assert row["followup_state"] == "due"
    assert row["person"] == "Anna"
    with sqlite3.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='esiti'").fetchone()
