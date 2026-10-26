"""A sent confirmation must reach the calendar, or someone must hear that
it did not.

On 02/10 a reply sent through the MCP server confirmed an appointment and
the calendar never saw it: the headless agent cannot start inside the AI
client that runs the server ("Not logged in"), and the failed read looked
like a mail without appointments. No audit line, no notice."""
import json
import threading
from datetime import datetime

import pytest

from gigamail import agent_bridge, policy
from gigamail.core import appointments, mail_router, telegram_channel

# Friday 2 October 2026, 16:08
SENT = datetime(2026, 10, 2, 16, 8)
SUBJECT = "Re: Nuovo messaggio di Anna sul tuo immobile, Via Roma 10"
CLIENT = "anna.verdi@example.com"
BODY = ("Gentile Anna,\nvenerdi 9 ottobre alle 17:00 va benissimo: le "
        "confermo l'appuntamento.\nCordiali saluti")
CONFIRMED = '{"stato":"confermato","inizio":"2026-10-09T17:00","con":"Anna"}'


class FakeCalendar:
    def __init__(self, fails: bool = False):
        self.created, self.fails = [], fails

    def create_event(self, subject, start, end, location='', body='',
                     attendees=None):
        if self.fails:
            raise RuntimeError("calendar unreachable")
        self.created.append({"subject": subject, "start": start})
        return {"id": f"ev{len(self.created)}"}

    def update_event(self, event_id, **kwargs):
        return {"id": event_id, **kwargs}

    def delete_event(self, event_id):
        return True

    def get_events(self, days_ahead=7, **kw):
        return []


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, text, buttons=None, html=False):
        self.sent.append(text)
        return True


@pytest.fixture()
def cal(monkeypatch, tmp_path, appointments_on):
    fake = FakeCalendar()
    monkeypatch.setattr(appointments, "calendar_router", fake)
    appointments.set_store(
        appointments.AppointmentStore(tmp_path / ".appointments.db"))
    monkeypatch.setattr(appointments, "_propri", lambda: (set(), set()))
    monkeypatch.setattr(appointments, "_nomi_propri", lambda: [])
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    yield fake
    appointments.set_store(None)


@pytest.fixture()
def tg(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(telegram_channel, "channel", lambda: fake)
    return fake


@pytest.fixture()
def audit():
    """The appointment lines written to the audit during the test."""
    path = policy._audit_path()
    try:
        with open(path, encoding="utf-8") as f:
            start = len(f.readlines())
    except FileNotFoundError:
        start = 0

    def lines():
        try:
            with open(path, encoding="utf-8") as f:
                rows = [json.loads(x) for x in f.readlines()[start:] if x.strip()]
        except FileNotFoundError:
            return []
        return [r for r in rows if r["tool"] == "appointment"]
    return lines


def _agent_not_logged_in(monkeypatch):
    def _run(prompt, timeout=None):
        raise agent_bridge.AgentUnavailable(
            "Agent exited with error (1): Not logged in · Please run /login")
    monkeypatch.setattr(appointments.agent_bridge, "run", _run)


def _agent(monkeypatch, answer: str, prompts=None):
    def _run(prompt, timeout=None):
        if prompts is not None:
            prompts.append(prompt)
        return answer
    monkeypatch.setattr(appointments.agent_bridge, "run", _run)


def _send_reply(monkeypatch):
    """send_message as reply_message calls it, then wait for the
    calendar thread it starts."""
    monkeypatch.setattr(mail_router, "_send_backend",
                        lambda **kw: {"success": True})
    monkeypatch.setattr(mail_router, "_account", lambda aid=None: {"id": 2})
    before = set(threading.enumerate())
    result = mail_router.send_message(account_id=2, to=CLIENT,
                                      subject=SUBJECT, body=BODY,
                                      reply_to_id="101")
    for t in set(threading.enumerate()) - before:
        if t.name == "gigamail-appointment":
            t.join(timeout=10)
    return result


# -- the incident ------------------------------------------------------

def test_failed_read_is_no_longer_silent(monkeypatch, cal, tg, audit):
    """The 02/10 confirmation: the mail goes out, the agent cannot read
    it. Now the audit says so, the mail waits for the watcher and, with no
    watcher running, the human hears it."""
    monkeypatch.setattr(appointments, "_watcher_running", lambda: False)
    _agent_not_logged_in(monkeypatch)

    assert _send_reply(monkeypatch)["success"] is True

    assert cal.created == []
    failed = [r for r in audit() if r["outcome"] == "read_failed"]
    assert len(failed) == 1
    assert "Not logged in" in failed[0]["detail"]
    assert failed[0]["args"]["thread"] == appointments.thread_key(SUBJECT, CLIENT)
    pending = appointments.store().pending_reads()
    assert [(p["subject"], p["counterpart"]) for p in pending] == [(SUBJECT, CLIENT)]
    assert len(tg.sent) == 1
    assert CLIENT in tg.sent[0] and "could not read it" in tg.sent[0]
    assert "by hand" in tg.sent[0]


def test_with_the_watcher_running_the_read_just_waits(monkeypatch, cal, tg,
                                                      audit):
    """The watcher will read it within a couple of minutes: telling the
    human now would be a false alarm on every mail sent from the MCP
    server."""
    monkeypatch.setattr(appointments, "_watcher_running", lambda: True)
    _agent_not_logged_in(monkeypatch)

    _send_reply(monkeypatch)

    assert tg.sent == []
    assert [r["outcome"] for r in audit()] == ["read_failed", "read_queued"]
    assert len(appointments.store().pending_reads()) == 1


def test_watcher_puts_the_queued_confirmation_in_the_calendar(
        monkeypatch, cal, tg, audit):
    appointments.segui(2, SUBJECT, CLIENT)
    appointments.store().pending_read_add(2, SUBJECT, BODY, CLIENT,
                                          "agent unavailable",
                                          sent_at=SENT.timestamp())
    prompts = []
    _agent(monkeypatch, CONFIRMED, prompts)

    assert appointments.retry_pending_reads() == 1

    assert [c["start"] for c in cal.created] == ["2026-10-09T17:00"]
    assert appointments.store().pending_reads() == []
    row = appointments.store().get(2, appointments.thread_key(SUBJECT, CLIENT))
    assert row["stato"] == "confermato" and row["event_id"] == "ev1"
    assert "confirmed" in [r["outcome"] for r in audit()]
    # "venerdi 9 ottobre" is read against the day the mail left.
    assert "2026-10-02T16:08" in prompts[0]
    assert tg.sent == []


def test_watcher_gives_up_and_tells_the_human(monkeypatch, cal, tg, audit):
    appointments.store().pending_read_add(2, SUBJECT, BODY, CLIENT,
                                          "agent unavailable",
                                          sent_at=SENT.timestamp())
    _agent_not_logged_in(monkeypatch)

    for _ in range(appointments._TENTATIVI_MAX - 2):
        appointments.retry_pending_reads()
    assert len(appointments.store().pending_reads()) == 1
    assert tg.sent == []

    appointments.retry_pending_reads()

    assert appointments.store().pending_reads() == []
    assert "read_gave_up" in [r["outcome"] for r in audit()]
    assert len(tg.sent) == 1 and "update the calendar by hand" in tg.sent[0]
    appointments.retry_pending_reads()
    assert len(tg.sent) == 1


def test_watcher_tick_retries_the_queued_reads(monkeypatch, cal):
    from gigamail import watcher as watcher_mod

    appointments.store().pending_read_add(2, SUBJECT, BODY, CLIENT,
                                          "agent unavailable",
                                          sent_at=SENT.timestamp())
    _agent(monkeypatch, CONFIRMED)
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: [])

    assert watcher_mod.Watcher().sweep_appointments() == 1
    assert len(cal.created) == 1


# -- the calendar refuses ----------------------------------------------

def test_sent_confirmation_the_calendar_refuses_is_told(monkeypatch, cal, tg):
    cal.fails = True
    _agent(monkeypatch, CONFIRMED)

    appointments.after_sent(2, SUBJECT, BODY, CLIENT, adesso=SENT)

    assert appointments.store().pending_reads() == []
    assert len(tg.sent) == 1
    assert "Confirmation sent to " + CLIENT in tg.sent[0]
    assert "NOT updated" in tg.sent[0]


def test_cancellation_with_nothing_in_the_calendar_is_quiet(monkeypatch, cal,
                                                            tg):
    _agent(monkeypatch, '{"stato":"disdetto"}')
    appointments.after_sent(2, SUBJECT, "devo annullare", CLIENT, adesso=SENT)
    assert tg.sent == []


def test_mail_without_appointments_stays_quiet(monkeypatch, cal, tg, audit):
    _agent(monkeypatch, '{"stato":"nessuno"}')
    assert appointments.after_sent(2, SUBJECT, "ci sentiamo lunedi", CLIENT,
                                   adesso=SENT) is None
    assert tg.sent == [] and audit() == []
    assert appointments.store().pending_reads() == []


# -- leggi tells "nothing there" from "could not read" -----------------

def test_leggi_reports_why_it_could_not_read(monkeypatch):
    _agent_not_logged_in(monkeypatch)
    esito = appointments.leggi(BODY, SUBJECT, CLIENT, adesso=SENT)
    assert esito["stato"] == "nessuno" and "Not logged in" in esito["errore"]

    _agent(monkeypatch, "Sure, that is an appointment.")
    esito = appointments.leggi(BODY, SUBJECT, CLIENT, adesso=SENT)
    assert esito["stato"] == "nessuno" and "not JSON" in esito["errore"]

    _agent(monkeypatch, '{"stato":"nessuno"}')
    assert appointments.leggi(BODY, SUBJECT, CLIENT, adesso=SENT) == {
        "stato": "nessuno"}


# -- a client's reply the agent cannot read ----------------------------

REPLY = {"id": "201", "subject": SUBJECT,
         "from": {"emailAddress": {"address": CLIENT, "name": "Anna Verdi"}},
         "body_text": "Va bene venerdi 9 ottobre alle 17:00, grazie."}


def _sweep(notices):
    return appointments.sweep(
        2, [dict(REPLY)], adesso=SENT,
        avvisa=lambda *a: notices.append(appointments.testo_avviso(
            *a, lingua="en")))


def test_unread_client_reply_is_retried_then_given_up(monkeypatch, cal,
                                                      audit):
    """It used to count as a reply without appointments: marked seen,
    never read again, and the notice said nothing about the calendar."""
    appointments.segui(2, SUBJECT, CLIENT)
    _agent_not_logged_in(monkeypatch)
    notices = []

    _sweep(notices)
    assert len(notices) == 1
    assert "Va bene venerdi" in notices[0]
    assert "could not read it for the calendar. Retrying" in notices[0]
    assert not appointments.store().vista(2, "201")

    for _ in range(appointments._TENTATIVI_MAX - 2):
        _sweep(notices)
    assert len(notices) == 1

    _sweep(notices)
    assert len(notices) == 2 and "update the calendar by hand" in notices[1]
    assert appointments.store().vista(2, "201")
    _sweep(notices)
    assert len(notices) == 2

    failed = [r for r in audit() if r["outcome"] == "read_failed"]
    assert len(failed) == appointments._TENTATIVI_MAX
    assert failed[0]["args"]["message_id"] == "201"
    assert cal.created == []


def test_client_reply_read_on_retry_reaches_the_calendar(monkeypatch, cal):
    appointments.segui(2, SUBJECT, CLIENT)
    _agent_not_logged_in(monkeypatch)
    notices = []
    assert _sweep(notices) == 0

    _agent(monkeypatch, CONFIRMED)
    assert _sweep(notices) == 1

    assert [c["start"] for c in cal.created] == ["2026-10-09T17:00"]
    assert len(notices) == 2 and "added to the calendar" in notices[1]
    assert appointments.store().vista(2, "201")
