"""What the agent writes with placeholders is restored before approval.

An account that masks what agents read hands the agent "[IBAN_1a2b3c4d]"
instead of the IBAN. When the agent writes a mail with that placeholder,
GigaMail puts the real value back before the approval request is stored:
the human approves the mail as it will leave, with a line saying what it
reveals, and what goes back to the agent stays masked. The masker also
recognises US and international data.
"""
import re

import pytest

from gigamail import policy, server
from gigamail.core import ade_masker, attachment_mask, mask_vault

EMAIL = "mario.rossi@example.com"
IBAN = "IT60X0542811101000000123456"
PLACEHOLDER = re.compile(r"\[[A-Z0-9_]+_[0-9a-f]{8}\]")


@pytest.fixture
def settings(monkeypatch, tmp_path):
    """App settings in memory, no saved user masks, a vault and an
    approval store of this test only, one active account."""
    store = {}
    monkeypatch.setattr(attachment_mask.accounts, "get_setting",
                        lambda key, default="": store.get(key, default))
    monkeypatch.setattr(attachment_mask.accounts, "set_setting",
                        lambda key, value: store.__setitem__(key, str(value)))
    monkeypatch.setattr(attachment_mask.ade_masker, "get_user_masks", lambda aid: [])
    monkeypatch.setattr(mask_vault, "_path", lambda: tmp_path / "mask_vault.db")
    account = {"id": 1, "email": "owner@example.com"}
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: account)
    monkeypatch.setattr(server.core_accounts, "get_account_by_id", lambda aid: account)
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield store
    policy.set_store(None)


def _types(text):
    return {(c["type"], c["value"]) for c in ade_masker.detect(text)}


def _masked(text, account_id=1):
    """Switch the mask on and read `text` as an agent would."""
    attachment_mask.set_enabled(account_id, True)
    return attachment_mask.apply(account_id, text).text


def _placeholder_of(masked, label):
    return re.search(r"\[" + label + r"_[0-9a-f]{8}\]", masked).group(0)


# ── US and international data ────────────────────────────────────────

def test_us_numbers_are_recognised():
    found = _types(
        "SSN 123-45-6789, ITIN 912-70-1234, EIN 12-3456789.\n"
        "Routing number 021000021, account no. 123456789012.\n"
        "Card 4111 1111 1111 1111, call (415) 555-0132.\n"
        "Ship to 1600 Main Street, Apt 5, Springfield, IL 62701.\n")
    assert {("SSN", "123-45-6789"), ("ITIN", "912-70-1234"), ("EIN", "12-3456789"),
            ("US_ROUTING", "021000021"), ("US_BANK_ACCOUNT", "123456789012"),
            ("CREDIT_CARD", "4111 1111 1111 1111"), ("US_PHONE", "(415) 555-0132"),
            ("US_ADDRESS", "1600 Main Street, Apt 5, Springfield, IL 62701")} <= found


@pytest.mark.parametrize("text", [
    "SSN 000-12-3456", "SSN 666-12-3456", "SSN 123-00-4567", "SSN 123-45-0000",
    "EIN 17-1234567",
    "routing number 111000026",           # checksum
    "order 111000025",                     # a valid routing number, no keyword
    "card 4111 1111 1111 1112",            # Luhn
    "on 2026-11-18 at 10:30, 15 people, version 1.2.3, ticket #4521",
])
def test_numbers_that_only_look_like_them_are_left_alone(text):
    assert ade_masker.detect(text) == []


def test_international_data_is_recognised():
    found = _types("Call +44 20 7946 0958. VAT DE123456789. "
                   "IBAN GB82 WEST 1234 5698 7654 32.")
    assert {("INTL_PHONE", "+44 20 7946 0958"), ("EU_VAT", "DE123456789"),
            ("IBAN", "GB82 WEST 1234 5698 7654 32")} <= found


def test_an_iban_of_the_wrong_length_for_its_country_is_left_alone():
    # A valid British IBAN with two characters too many.
    assert not [c for c in ade_masker.detect("GB82 WEST 1234 5698 7654 3200")
                if c["type"] == "IBAN"]


def test_italian_street_addresses_are_recognised():
    found = _types("Sede in Via Roma 10, 20100 Milano. Ritiro in Piazza della "
                   "Repubblica, 3 oppure in Corso dell'Orso 4/B.")
    assert ("INDIRIZZO", "Via Roma 10, 20100 Milano") in found
    assert ("INDIRIZZO", "Piazza della Repubblica, 3") in found
    assert ("INDIRIZZO", "Corso dell'Orso 4/B") in found


def test_long_runs_of_digits_and_words_do_not_stall_the_masker():
    import time
    start = time.perf_counter()
    for text in ("+" + "1 " * 3000 + "x", "+" + "1" * 5000 + "(",
                 "Via " + "Aaaa " * 3000 + "x", "routing" + " " * 5000):
        ade_masker.detect(text)
    assert time.perf_counter() - start < 2


def test_the_new_types_are_masked_unless_taken_out(settings):
    text = "SSN 123-45-6789, card 4111 1111 1111 1111."
    assert "123-45-6789" not in _masked(text)
    attachment_mask.save_types(1, [t for t in attachment_mask.TYPES if t != "SSN"])
    masked = attachment_mask.apply(1, text).text
    assert "123-45-6789" in masked and "4111" not in masked


# ── the vault ────────────────────────────────────────────────────────

def test_no_vault_until_a_masked_read(settings):
    attachment_mask.for_agent(1, f"IBAN {IBAN}")      # switch off
    assert not mask_vault.exists()
    _masked(f"IBAN {IBAN}")
    assert mask_vault.exists()


def test_a_placeholder_comes_back_as_its_value(settings):
    ph = _placeholder_of(_masked(f"Pay to {IBAN}."), "IBAN")
    r = mask_vault.restore(f"Our IBAN is {ph}, thanks.")
    assert r.text == f"Our IBAN is {IBAN}, thanks."
    assert r.revealed == [{"placeholder": ph, "label": "IBAN"}] and r.unknown == []


def test_a_placeholder_the_vault_does_not_know_is_reported(settings):
    _masked(f"Pay to {IBAN}.")
    r = mask_vault.restore("Send it to [IBAN_00000000].")
    assert r.text == "Send it to [IBAN_00000000]." and r.unknown == ["[IBAN_00000000]"]


def test_only_the_allowed_placeholders_are_restored(settings):
    masked = _masked(f"{EMAIL} {IBAN}")
    email, iban = _placeholder_of(masked, "EMAIL"), _placeholder_of(masked, "IBAN")
    r = mask_vault.restore(f"{email} {iban}", allowed={email})
    assert r.text == f"{EMAIL} {iban}"


def test_an_invented_name_comes_back_as_the_real_one(settings):
    attachment_mask.save_field_rules(1, [{"label": "Full name", "action": "fake_name"}])
    masked = _masked("Full name Mario Rossi\n")
    fake = masked.split("Full name ", 1)[1].strip()
    assert fake != "Mario Rossi"
    assert mask_vault.restore(f"Dear {fake},").text == "Dear Mario Rossi,"


def test_a_fixed_text_is_not_restored(settings):
    attachment_mask.save_field_rules(
        1, [{"label": "Full name", "action": "fixed", "value": "the client"}])
    _masked("Full name Mario Rossi\n")
    assert mask_vault.restore("Dear the client,").text == "Dear the client,"


def test_one_replacement_for_two_values_is_never_restored(settings):
    mask_vault.remember(1, [("[X_1a2b3c4d]", "first value", "X", "placeholder")])
    mask_vault.remember(1, [("[X_1a2b3c4d]", "another value", "X", "placeholder")])
    r = mask_vault.restore("[X_1a2b3c4d]")
    assert r.text == "[X_1a2b3c4d]" and r.unknown == ["[X_1a2b3c4d]"]


def test_remask_writes_the_values_back_as_placeholders(settings):
    ph = _placeholder_of(_masked(f"Pay to {IBAN}."), "IBAN")
    revealed = mask_vault.restore(ph).revealed
    out = mask_vault.remask({"preview": {"body": f"IBAN {IBAN}", "cc": [IBAN]}}, revealed)
    assert out == {"preview": {"body": f"IBAN {ph}", "cc": [ph]}}


def test_the_warning_says_what_is_revealed():
    revealed = [{"placeholder": "[IBAN_1]", "label": "IBAN"},
                {"placeholder": "[EMAIL_1]", "label": "EMAIL"},
                {"placeholder": "[EMAIL_2]", "label": "EMAIL"}]
    assert "(2 EMAIL, 1 IBAN)" in mask_vault.describe(revealed, "en")
    assert "rivela" in mask_vault.describe(revealed, "it")
    assert mask_vault.describe([], "en") == ""


# ── MCP tools that write ─────────────────────────────────────────────

def _call(tool, **kw):
    fn = getattr(tool, "fn", tool)
    return fn(**kw)


def test_send_mail_restores_the_value_for_the_human_and_not_for_the_agent(settings):
    ph = _placeholder_of(_masked(f"Pay to {IBAN}."), "IBAN")
    out = _call(server.send_mail, to="client@example.com", subject="Payment",
                body=f"Please pay to {ph}.")
    assert out["status"] == "approval_required"
    # The agent: its own text, and the warning.
    assert IBAN not in str(out) and ph in out["preview"]["body"]
    assert out["preview"]["reveals"] == [{"placeholder": ph, "label": "IBAN"}]
    # The human: the mail as it will leave, and what executes is the same.
    rec = policy.store().get(out["request_id"])
    assert f"Please pay to {IBAN}." in rec["preview"]["body"]
    assert f"Please pay to {IBAN}." in rec["args"]["body"]
    assert "rivela" in rec["preview"]["reveals_warning"]
    # Calling again while it waits gives the masked preview back.
    again = _call(server.send_mail, to="client@example.com", subject="Payment",
                  body=f"Please pay to {ph}.", request_id=out["request_id"])
    assert again["status"] == "awaiting_approval" and IBAN not in str(again)


def test_send_mail_restores_a_masked_recipient(settings):
    ph = _placeholder_of(_masked(f"Write to {EMAIL}."), "EMAIL")
    out = _call(server.send_mail, to=ph, subject="Hello", body="Hello.")
    rec = policy.store().get(out["request_id"])
    assert rec["args"]["to"] == EMAIL and EMAIL not in str(out)


def test_an_unknown_placeholder_stops_the_mail(settings):
    _masked(f"Pay to {IBAN}.")
    out = _call(server.send_mail, to="client@example.com", subject="Payment",
                body="Please pay to [IBAN_00000000].")
    assert out["status"] == "error" and "[IBAN_00000000]" in out["error"]
    assert out["request_id"] is None


def test_a_mail_without_placeholders_has_no_warning(settings):
    _masked(f"Pay to {IBAN}.")
    out = _call(server.send_mail, to="client@example.com", subject="Hi", body="Hi.")
    assert "reveals" not in out["preview"]


def test_reply_mail_restores_the_body(settings, monkeypatch):
    ph = _placeholder_of(_masked(f"Pay to {IBAN}."), "IBAN")
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {
        "id": "42", "subject": "Invoice",
        "from": {"emailAddress": {"address": "client@example.com"}}})
    out = _call(server.reply_mail, message_id="42", body=f"The IBAN is {ph}.")
    rec = policy.store().get(out["request_id"])
    assert rec["args"]["body"].startswith(f"The IBAN is {IBAN}.")
    assert IBAN not in str(out) and out["preview"]["reveals"]


def test_save_draft_restores_the_values(settings, monkeypatch):
    from gigamail.core import drafts
    ph = _placeholder_of(_masked(f"Pay to {IBAN}."), "IBAN")
    saved = {}

    class Store:
        def save(self, **kw):
            saved.update(kw)
            return {"draft_id": 7}

    monkeypatch.setattr(drafts, "store", lambda: Store())
    monkeypatch.setattr(drafts, "sync", lambda draft_id: {"in_mailbox": True})
    out = _call(server.save_draft, body=f"IBAN: {ph}", to="client@example.com",
                subject="Invoice")
    assert out["success"] and saved["body"].startswith(f"IBAN: {IBAN}")


def test_create_event_restores_the_location(settings, monkeypatch):
    masked = _masked("Meet at Via Roma 10, 20100 Milano.")
    ph = _placeholder_of(masked, "ADDRESS")
    monkeypatch.setattr(server.calendar_router, "capture_destination", lambda: {})
    out = _call(server.create_event, subject="Visit", start="2026-12-01T10:00:00",
                end="2026-12-01T11:00:00", location=ph)
    rec = policy.store().get(out["request_id"])
    assert rec["args"]["location"] == "Via Roma 10, 20100 Milano"
    assert "Via Roma" not in str(out)


def test_a_watcher_reply_waiting_is_shown_masked_to_the_agent(settings, monkeypatch):
    attachment_mask.set_enabled(1, True)
    rid = policy.store().create("reply_mail", {"message_id": "42", "body": f"IBAN {IBAN}"},
                                {"body": f"IBAN {IBAN}"})
    monkeypatch.setattr(server.reply_guard, "existing_reply",
                        lambda mid: {"state": server.reply_guard.PENDING, "request_id": rid})
    out = _call(server.reply_mail, message_id="42", body="Another reply.")
    assert out["request_id"] == rid and IBAN not in str(out)
    assert PLACEHOLDER.search(out["preview"]["body"])


def test_the_notification_carries_the_warning(settings, monkeypatch):
    from gigamail.core import desktop_notify
    seen = []
    monkeypatch.setattr(desktop_notify, "notify", lambda title, text, **kw: seen.append(text) or True)
    monkeypatch.delenv("GIGAMAIL_APPROVAL_NOTIFY_CMD", raising=False)
    ph = _placeholder_of(_masked(f"Pay to {IBAN}."), "IBAN")
    _call(server.send_mail, to="client@example.com", subject="Payment",
          body=f"Please pay to {ph}.")
    assert any("rivela" in t for t in seen)


# ── what the agent reads ─────────────────────────────────────────────

def test_subjects_are_masked_on_a_masking_account(settings, monkeypatch):
    subject = f"Refund to {IBAN}"
    monkeypatch.setattr(server.mail_router, "get_messages",
                        lambda **kw: [{"id": "1", "subject": subject}])
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {
        "id": "1", "subject": subject, "body": {"contentType": "text", "content": "Hi"}})
    assert _call(server.list_messages)[0]["subject"] == subject
    attachment_mask.set_enabled(1, True)
    assert IBAN not in _call(server.list_messages)[0]["subject"]
    assert IBAN not in _call(server.read_message, message_id="1")["subject"]


# ── drafts GigaMail asks for itself ──────────────────────────────────

def _incoming():
    return {"id": "42", "subject": "Payment",
            "from": {"emailAddress": {"address": "client@example.com"}},
            "body": {"contentType": "text", "content": f"Please refund {IBAN}."}}


def test_a_watcher_draft_restores_only_what_its_mail_carried(settings, monkeypatch):
    from gigamail import agent_bridge
    from gigamail.watcher import drafting
    other = _placeholder_of(_masked(f"Another client: {EMAIL}"), "EMAIL")
    prompts = []

    def agent(prompt, **kw):
        prompts.append(prompt)
        ph = PLACEHOLDER.search(prompt.split("=== MAIL IN ARRIVO")[1]).group(0)
        return f"Refund sent to {ph}. Copy to {other}."

    monkeypatch.setattr(agent_bridge, "run", agent)
    body = drafting.draft_reply({"rule_id": "r", "reply_style": ""}, 1, _incoming())
    assert IBAN not in prompts[0]
    assert f"Refund sent to {IBAN}." in body
    # A value this mail did not carry stays a placeholder.
    assert other in body and EMAIL not in body


def test_a_redraft_gives_the_agent_the_rejected_draft_masked(settings, monkeypatch):
    from gigamail import agent_bridge
    from gigamail.watcher import drafting
    attachment_mask.set_enabled(1, True)
    prompts = []
    monkeypatch.setattr(agent_bridge, "run",
                        lambda prompt, **kw: prompts.append(prompt) or "A reply.")
    drafting.draft_reply({"rule_id": "r", "reply_style": ""}, 1, _incoming(),
                         feedback=f"Use {EMAIL}", previous_body=f"Refund to {IBAN}.")
    assert IBAN not in prompts[0] and EMAIL not in prompts[0]


def test_the_console_draft_comes_back_with_the_values(settings, monkeypatch):
    from gigamail.http_api import agent as agent_api
    monkeypatch.setattr(agent_api.mail_router, "get_message", lambda *a, **kw: _incoming())
    monkeypatch.setattr(agent_api, "_documenti_context", lambda *a, **kw: "")
    monkeypatch.setattr(agent_api, "_suggest_attachments", lambda *a, **kw: [])
    attachment_mask.set_enabled(1, True)

    def agent(prompt, **kw):
        return "Refunded to " + PLACEHOLDER.search(prompt).group(0) + "."

    monkeypatch.setattr(agent_api.agent_bridge, "run", agent)
    req = agent_api.SmartDraftRequest(subject="Payment", sender="client@example.com")
    out = agent_api.smart_draft("42", req, account_id=1)
    assert out["draft"] == f"Refunded to {IBAN}."
