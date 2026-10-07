# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""One confirmation per appointment.

A client replied accepting a time for a video call. Within six minutes
three paths each drafted a reply_mail request for that same mail: the
confirmation drafted at once by the watcher (and it said "at our office"),
a reply asked from Telegram, and the mail with the Zoom link. The payload
dedup only catches identical texts, so three requests reached the human;
two were approved and both went out.
"""
from datetime import datetime

import pytest

from gigamail import agent_bridge, policy, server
from gigamail import watcher as watcher_mod
from gigamail.core import (
    appointments,
    desktop_notify,
    mail_router,
    reply_guard,
    telegram_channel,
    video_call,
    zoom,
)
from gigamail.core import rules as rules_mod
from gigamail.watcher import pipeline, tg_risposte

NOW = datetime(2026, 10, 5, 9, 0)
MAIL = {"id": "7100", "subject": "Re: Video call per il trilocale",
        "from": {"emailAddress": {"address": "anna.verdi@example.com",
                                  "name": "Anna Verdi"}},
        "body_text": "Buongiorno, va bene mercoledi' 7 alle 16:00."}
ACCEPTED = ('{"stato":"proposto","inizio":"2026-10-07T16:00",'
            '"scelta_unica":true,"accetta":true}')


class FakeTG:
    chat_id = 123456789
    approve_enabled = True

    def __init__(self):
        self.sent = []
        self._next = 9000

    def send_message(self, text, buttons=None, html=False):
        self._next += 1
        self.sent.append(text)
        return self._next

    def send(self, text, buttons=None, html=False):
        return bool(self.send_message(text, buttons, html))

    def clear_buttons(self, message_id):
        return True

    action_buttons = staticmethod(telegram_channel.Telegram.action_buttons)
    is_trusted = telegram_channel.Telegram.is_trusted


class Cal:
    def create_event(self, subject, start, end, location="", body="",
                     attendees=None):
        return {"id": "ev-1"}

    def update_event(self, event_id, **kw):
        return {}

    def delete_event(self, event_id):
        return True

    def get_events(self, days_ahead=7, **kw):
        return []


@pytest.fixture()
def world(tmp_path, monkeypatch, appointments_on):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    appointments.set_store(appointments.AppointmentStore(tmp_path / "a.db"))
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    w = {"tg": FakeTG(), "prompts": [], "notified": [],
         "draft": "Dear Ms Verdi, I confirm Wednesday the 7th at 16:00."}
    cal = Cal()
    monkeypatch.setattr(appointments, "calendar_router", cal)
    monkeypatch.setattr(video_call, "calendar_router", cal)
    monkeypatch.setattr(appointments, "libero",
                        lambda start, end, escludi="": True)
    monkeypatch.setattr(mail_router, "get_message",
                        lambda **kw: dict(MAIL)
                        if str(kw.get("message_id")) == MAIL["id"] else {})
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: [dict(MAIL)])

    def run(prompt, **kw):
        w["prompts"].append(prompt)
        # the appointment reader asks for JSON, the drafts for prose
        return ACCEPTED if "riguarda un APPUNTAMENTO" in prompt else w["draft"]
    monkeypatch.setattr(agent_bridge, "run", run)
    monkeypatch.setattr(tg_risposte, "_cc", lambda aid: [])
    monkeypatch.setattr(video_call, "_cc", lambda aid: [])
    monkeypatch.setattr(video_call, "_firma", lambda aid: "Sales office")
    monkeypatch.setattr(video_call.telegram_channel, "channel", lambda: None)
    monkeypatch.setattr(telegram_channel, "channel", lambda: w["tg"])
    monkeypatch.setattr(desktop_notify, "notify", lambda *a, **kw: True)
    monkeypatch.setattr(policy, "notify_approval_requested",
                        lambda rid, tool, preview, **kw: w["notified"].append(rid) or True)
    # Zoom through the user's personal link: no HTTP in the test
    monkeypatch.setattr(zoom, "configurato", lambda: False)
    monkeypatch.setattr(video_call, "link_fisso", lambda: "https://zoom.example.com/j/1")
    yield w
    policy.set_store(None)
    rules_mod.set_store(None)
    appointments.set_store(None)


def _pending():
    return policy.store().list_pending()


@pytest.fixture()
def sweep_now(monkeypatch):
    """appointments.sweep with a fixed clock, through the watcher."""
    original = appointments.sweep

    def with_clock(*a, **kw):
        kw.setdefault("adesso", NOW)
        return original(*a, **kw)
    monkeypatch.setattr(appointments, "sweep", with_clock)

    def run():
        watcher = watcher_mod.Watcher(interval=60)
        monkeypatch.setattr(watcher, "heartbeat", lambda: None)
        return watcher.sweep_appointments()
    return run


# ── the video call: the link mail is the confirmation ────────────────

def test_an_accepted_video_call_gets_exactly_one_confirmation(world, sweep_now):
    appointments.segna_video(2, "Video call per il trilocale",
                             "anna.verdi@example.com")
    assert sweep_now() == 1
    [req] = _pending()
    assert req["tool"] == "reply_mail"
    assert "https://zoom.example.com/j/1" in req["args"]["body"]
    row = rules_mod.store().find_by_request(req["request_id"])
    assert row["rule_id"] == video_call.RULE_ID
    # the confirmation drafted at once stepped aside: no "at our office"
    assert not any("Confirm the appointment" in p for p in world["prompts"])
    assert rules_mod.store().get_handled(tg_risposte.RULE_ID, MAIL["id"]) is None


def test_a_reply_asked_from_telegram_while_one_is_pending_is_refused(world, sweep_now):
    appointments.segna_video(2, "Video call per il trilocale",
                             "anna.verdi@example.com")
    sweep_now()
    [first] = _pending()
    key = tg_risposte.register_context(2, MAIL)
    world["tg"].sent.clear()
    assert tg_risposte.rispondi(None, world["tg"], key, "ok, confirm") is None
    assert len(_pending()) == 1
    assert first["request_id"] in world["tg"].sent[-1]
    assert "already waiting for approval" in world["tg"].sent[-1]


def test_the_agent_asking_through_mcp_gets_the_pending_request_back(world, sweep_now):
    appointments.segna_video(2, "Video call per il trilocale",
                             "anna.verdi@example.com")
    sweep_now()
    [first] = _pending()
    out = server.reply_mail(message_id=MAIL["id"], body="Confirmed, see you then.",
                            account_id=2)
    assert out["status"] == "approval_required"
    assert out["request_id"] == first["request_id"]
    assert out["deduplicated"] is True
    assert "https://zoom.example.com/j/1" in out["preview"]["body"]
    assert len(_pending()) == 1


def test_after_a_rejection_the_mail_can_be_answered_again(world, sweep_now):
    appointments.segna_video(2, "Video call per il trilocale",
                             "anna.verdi@example.com")
    sweep_now()
    [first] = _pending()
    assert policy.store().reject(first["request_id"], by="test")
    key = tg_risposte.register_context(2, MAIL)
    rid = tg_risposte.rispondi(None, world["tg"], key, "propose Thursday instead")
    assert rid and rid != first["request_id"]


# ── an office appointment: the confirmation drafted at once owns it ──

def test_an_office_appointment_still_gets_its_confirmation(world, sweep_now):
    appointments.segui(2, "Video call per il trilocale", "anna.verdi@example.com")
    assert sweep_now() == 1
    [req] = _pending()
    assert req["args"]["body"] == world["draft"]
    assert "at our office" in world["prompts"][-1]


def test_a_video_call_without_zoom_gets_a_video_call_confirmation(world, sweep_now, monkeypatch):
    monkeypatch.setattr(video_call, "link_fisso", lambda: "")
    appointments.segna_video(2, "Video call per il trilocale",
                             "anna.verdi@example.com")
    sweep_now()
    [req] = _pending()
    assert req["args"]["body"] == world["draft"]
    assert "by video call" in world["prompts"][-1]
    assert "at our office" not in world["prompts"][-1]


# ── the shared guard ─────────────────────────────────────────────────

def test_existing_reply_reads_both_stores(world):
    rs = rules_mod.store()
    assert reply_guard.existing_reply(MAIL["id"]) is None
    rid = policy.store().create("reply_mail", {"message_id": MAIL["id"],
                                               "body": "x", "account_id": 2},
                                {"body": "x"})
    # an MCP request has no handled row: found through the approval store
    assert reply_guard.existing_reply(MAIL["id"]) == {
        "state": reply_guard.PENDING, "request_id": rid, "rule_id": ""}
    policy.store().reject(rid, by="test")
    assert reply_guard.existing_reply(MAIL["id"]) is None
    # a handled row whose request was approved counts as pending too
    rid2 = policy.store().create("reply_mail", {"to": "a@example.com",
                                                "message_id": MAIL["id"]},
                                 {"body": "y"})
    rs.record("rule-a", 2, MAIL["id"], "anna.verdi@example.com",
              "awaiting_approval", "", rid2)
    policy.store().approve(rid2, by="test")
    assert reply_guard.existing_reply(MAIL["id"])["state"] == reply_guard.PENDING
    assert reply_guard.existing_reply(MAIL["id"], exclude_rule="rule-a") is None
    # sent wins over pending
    rs.record("rule-b", 2, MAIL["id"], "anna.verdi@example.com", "sent")
    found = reply_guard.existing_reply(MAIL["id"])
    assert found["state"] == reply_guard.SENT and found["rule_id"] == "rule-b"


def test_a_rule_skips_a_mail_another_path_already_answered(world, monkeypatch):
    rs = rules_mod.store()
    rid = policy.store().create("reply_mail", {"to": "anna.verdi@example.com"},
                                {"body": "link"})
    rs.record(video_call.RULE_ID, 2, MAIL["id"], "anna.verdi@example.com",
              "awaiting_approval", "", rid)
    rule = {"rule_id": "rule-x", "account_id": 2, "mode": "semi",
            "daily_cap": 10, "cooldown_hours": 0, "first_contact": "semi"}
    monkeypatch.setattr(mail_router, "get_message_headers",
                        lambda **kw: pytest.fail("the rule must stop before the barriers"))
    w = watcher_mod.Watcher(interval=60)
    assert pipeline.process_message(w, rule, MAIL) == "skipped"
    row = rs.get_handled("rule-x", MAIL["id"])
    assert row["reason"] == "already-answered:" + video_call.RULE_ID
    assert len(_pending()) == 1


def test_a_rejected_draft_does_not_block_the_rule(world, monkeypatch):
    rs = rules_mod.store()
    rid = policy.store().create("reply_mail", {"to": "anna.verdi@example.com"},
                                {"body": "old"})
    rs.record(tg_risposte.RULE_ID, 2, MAIL["id"], "anna.verdi@example.com",
              "awaiting_approval", "", rid)
    policy.store().reject(rid, by="test")
    assert reply_guard.existing_reply(MAIL["id"]) is None
    assert [r["rule_id"] for r in rs.replies_to(MAIL["id"])] == [tg_risposte.RULE_ID]
