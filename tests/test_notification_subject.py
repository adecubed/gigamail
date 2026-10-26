"""Approval notifications name the mail they are about.

On a phone, "Reply to Anna. Approve?" followed by the draft did not say
which mail it answered; the desktop toast for a reply showed a raw
"replying_to={...}" summary cut at 160 characters.
"""
import pytest

from gigamail import policy
from gigamail.core import desktop_notify, telegram_channel

PREVIEW = {"replying_to": {"from": {"emailAddress": {"address": "anna.verdi@example.com",
                                                     "name": "Anna Verdi"}},
                           "subject": "Re: Trilocale in Via\r\n Roma 10"},
           "body": "Gentile Sig.ra Verdi, a venerdi'."}


class FakeTG:
    chat_id = 1
    approve_enabled = False

    def __init__(self):
        self.sent = []

    def send(self, text, buttons=None, html=False):
        self.sent.append(text)
        return True


@pytest.fixture()
def channels(monkeypatch):
    seen = {"toast": [], "tg": FakeTG()}
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    monkeypatch.setattr(policy, "_notify_command", lambda: None)
    monkeypatch.setattr(policy, "audit", lambda *a, **k: None)
    monkeypatch.setattr(desktop_notify, "notify",
                        lambda title, body, **kw: seen["toast"].append(body) or True)
    monkeypatch.setattr(telegram_channel, "channel", lambda: seen["tg"])

    class _Thread:                      # run the Telegram send inline
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr("threading.Thread", _Thread)
    return seen


def test_the_subject_line_goes_under_the_first_line():
    text = policy.with_subject("✍️ Risposta a Anna Verdi. Approvi?\n\nGentile...", PREVIEW)
    assert text.splitlines()[:2] == ["✍️ Risposta a Anna Verdi. Approvi?",
                                     "📧 «Re: Trilocale in Via Roma 10»"]


def test_no_second_subject_when_the_text_already_has_it():
    text = "E' arrivata una mail da a@example.com — «Re: Trilocale in Via Roma 10».\nBozza"
    assert policy.with_subject(text, PREVIEW) == text


def test_no_subject_no_line():
    assert policy.with_subject("Approvi?", {"body": "x"}) == "Approvi?"


def test_a_message_gets_the_subject_on_both_channels(channels):
    policy.notify_approval_requested("req_1", "reply_mail", PREVIEW,
                                     message="✍️ Risposta a Anna Verdi. Approvi?\n\nGentile...")
    assert "📧 «Re: Trilocale in Via Roma 10»" in channels["toast"][-1]
    assert "Re: Trilocale in Via Roma 10" in channels["tg"].sent[-1]


def test_a_tool_request_toast_is_readable(channels):
    policy.notify_approval_requested("req_2", "reply_mail", PREVIEW)
    toast = channels["toast"][-1]
    assert "replying_to=" not in toast
    assert "📧 «Re: Trilocale in Via Roma 10»" in toast
    assert "→ anna.verdi@example.com" in toast
    # Telegram gets the full preview, with a readable "replying to" line
    # (safe_html wraps addresses in <code>, so they can't be tapped)
    tg = channels["tg"].sent[-1]
    assert "In risposta a: <code>anna.verdi@example.com</code>" in tg
    assert "— «Re: Trilocale in Via Roma 10»" in tg
    assert "emailAddress" not in tg


def test_a_new_mail_uses_its_own_subject(channels):
    preview = {"to": "mario.rossi@example.com", "subject": "Planimetrie", "body": "..."}
    policy.notify_approval_requested("req_3", "send_mail", preview)
    assert "📧 «Planimetrie»" in channels["toast"][-1]
    assert "→ mario.rossi@example.com" in channels["toast"][-1]
