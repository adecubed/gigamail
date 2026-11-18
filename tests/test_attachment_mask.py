"""Mail and attachments read by an agent can be masked, per account.

The agent reads a mail's body through read_message and an attachment
through read_attachment. With the account's switch on, personal data in
that text is replaced by placeholders before it leaves GigaMail; the
switch is off by default and no MCP tool can change it.
"""
import importlib
import re

import pytest
from fastapi.testclient import TestClient

from gigamail import server
from gigamail.core import attachment_mask

EMAIL = "mario.rossi@example.com"
IBAN = "IT60X0542811101000000123456"
BALLOT = f"Voter: {EMAIL}\nIBAN: {IBAN}\nVote: candidate B\n"
ALL_TYPES = list(attachment_mask.TYPES)
PLACEHOLDER = re.compile(r"\[[A-Z0-9_]+_[0-9a-f]{8}\]")


@pytest.fixture
def settings(monkeypatch):
    """App settings kept in memory, and no saved user masks."""
    store = {}
    monkeypatch.setattr(attachment_mask.accounts, "get_setting",
                        lambda key, default="": store.get(key, default))
    monkeypatch.setattr(attachment_mask.accounts, "set_setting",
                        lambda key, value: store.__setitem__(key, str(value)))
    monkeypatch.setattr(attachment_mask.ade_masker, "get_user_masks", lambda aid: [])
    return store


@pytest.fixture
def mailbox(monkeypatch, settings):
    """read_attachment serves text files from memory: mailbox[name] = text."""
    files = {}
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: {"id": 1})
    monkeypatch.setattr(server.mail_router, "get_attachment",
                        lambda **kw: files[kw["filename"]].encode("utf-8"))
    return files


# ── the module ───────────────────────────────────────────────────────

def test_off_by_default_and_per_account(settings):
    assert attachment_mask.enabled(1) is False
    attachment_mask.set_enabled(1, True)
    assert attachment_mask.enabled(1) is True
    assert attachment_mask.enabled(2) is False
    assert attachment_mask.enabled(None) is False
    attachment_mask.set_enabled(1, False)
    assert attachment_mask.enabled(1) is False


def test_an_unreadable_setting_masks(monkeypatch):
    def broken(*a, **kw):
        raise OSError("database locked")
    monkeypatch.setattr(attachment_mask.accounts, "get_setting", broken)
    assert attachment_mask.enabled(1) is True


def test_mask_hides_values_and_keeps_the_rest(settings):
    masked, hidden = attachment_mask.mask(1, BALLOT)
    assert EMAIL not in masked and IBAN not in masked
    assert "Vote: candidate B" in masked
    assert hidden == 2
    assert len(PLACEHOLDER.findall(masked)) == 2


def test_same_value_same_placeholder_across_attachments(settings):
    first, _ = attachment_mask.mask(1, f"From {EMAIL}, vote A")
    second, _ = attachment_mask.mask(1, f"Second ballot, {EMAIL.upper()} again")
    other, _ = attachment_mask.mask(1, "From anna.bianchi@example.com, vote A")
    ph = PLACEHOLDER.search(first).group(0)
    assert ph.startswith("[EMAIL_")
    assert ph in second
    assert ph not in other


def test_placeholders_depend_on_a_local_secret(settings):
    first, _ = attachment_mask.mask(1, EMAIL)
    settings.pop("attachment_mask_secret")
    second, _ = attachment_mask.mask(1, EMAIL)
    assert first != second


def test_user_masks_of_the_account_are_applied(settings, monkeypatch):
    monkeypatch.setattr(
        attachment_mask.ade_masker, "get_user_masks",
        lambda aid: [{"id": 7, "value": "Mario Rossi", "label_type": "NOME"}] if aid == 1 else [])
    masked, hidden = attachment_mask.mask(1, "Signed: Mario Rossi")
    assert "Mario Rossi" not in masked
    assert "[NOME_" in masked and hidden == 1
    assert attachment_mask.mask(2, "Signed: Mario Rossi") == ("Signed: Mario Rossi", 0)


def test_text_with_nothing_to_hide_is_unchanged(settings):
    assert attachment_mask.mask(1, "Vote: candidate B") == ("Vote: candidate B", 0)
    assert attachment_mask.mask(1, "") == ("", 0)


# ── recognised types ─────────────────────────────────────────────────

def test_every_recognised_type_is_masked_unless_taken_out(settings):
    assert attachment_mask.types(1) == ALL_TYPES
    attachment_mask.save_types(1, [t for t in ALL_TYPES if t != "EMAIL"])
    masked, hidden = attachment_mask.mask(1, BALLOT)
    assert EMAIL in masked and IBAN not in masked and hidden == 1
    assert attachment_mask.types(2) == ALL_TYPES
    assert EMAIL not in attachment_mask.mask(2, BALLOT)[0]


def test_a_type_taken_out_is_not_picked_up_as_another(settings):
    # A VAT number left in clear must not come back masked as a phone.
    attachment_mask.save_types(1, [t for t in ALL_TYPES if t != "PARTITA_IVA"])
    assert attachment_mask.mask(1, "VAT 12345678903") == ("VAT 12345678903", 0)


def test_saved_masks_apply_whatever_the_types(settings, monkeypatch):
    monkeypatch.setattr(attachment_mask.ade_masker, "get_user_masks",
                        lambda aid: [{"id": 7, "value": "Mario Rossi", "label_type": "NOME"}])
    attachment_mask.save_types(1, [])
    masked, hidden = attachment_mask.mask(1, f"Mario Rossi, {EMAIL}")
    assert "Mario Rossi" not in masked and EMAIL in masked and hidden == 1


def test_unknown_types_are_refused_and_an_unreadable_choice_masks_all(settings):
    with pytest.raises(ValueError):
        attachment_mask.save_types(1, ["EMAIL", "PASSPORT"])
    settings["mask_types_account_1"] = "{not json"
    assert attachment_mask.types(1) == ALL_TYPES


# ── field rules ──────────────────────────────────────────────────────

FORM = (
    "Test award 2026 - Ballot\n"
    "Full name Mario Rossi\n"
    "Address: Via Roma 10, Milano\n"
    "Best film Candidate B\n"
    "Signed by MARIO  ROSSI\n"
)


def rule(label, action="placeholder", value=""):
    return {"label": label, "action": action, "value": value}


def test_a_field_becomes_a_placeholder_wherever_its_value_appears(settings):
    attachment_mask.save_field_rules(1, [rule("Full name")])
    r = attachment_mask.apply(1, FORM)
    assert "Mario Rossi" not in r.text and "MARIO" not in r.text
    ph = re.search(r"\[FULL_NAME_[0-9a-f]{8}\]", r.text).group(0)
    assert f"Full name {ph}\n" in r.text
    assert f"Signed by {ph}\n" in r.text          # other case, other spacing
    assert "Best film Candidate B" in r.text
    assert (r.hidden, r.invented, r.unmatched) == (2, False, [])


def test_a_field_can_get_an_invented_name_always_the_same(settings):
    attachment_mask.save_field_rules(1, [rule("Full name", "fake_name")])
    r = attachment_mask.apply(1, FORM)
    assert "Mario Rossi" not in r.text and r.invented is True
    invented = re.search(r"Full name (.+)\n", r.text).group(1)
    first, second, last = invented.split(" ", 2)
    assert first in attachment_mask._FIRST_NAMES and second in attachment_mask._FIRST_NAMES
    assert first != second
    one = next(n for n in attachment_mask._LAST_NAMES if last.startswith(n + "-"))
    other = last[len(one) + 1:]
    assert other in attachment_mask._LAST_NAMES and other != one
    assert f"Signed by {invented}\n" in r.text
    again = attachment_mask.apply(1, "Full name: mario rossi\nBest film Candidate A\n")
    assert f"Full name: {invented}\n" in again.text
    other = attachment_mask.apply(1, "Full name: Anna Bianchi\n")
    assert invented not in other.text and "Anna Bianchi" not in other.text


def test_a_field_can_get_a_fixed_text(settings):
    attachment_mask.save_field_rules(1, [rule("Address", "fixed", "Via Garibaldi 1")])
    r = attachment_mask.apply(1, FORM)
    assert "Address: Via Garibaldi 1\n" in r.text
    assert "Via Roma 10" not in r.text and r.invented is False


def test_a_label_alone_on_its_line_takes_the_next_line(settings):
    attachment_mask.save_field_rules(1, [rule("Full name")])
    r = attachment_mask.apply(1, "Full name\n  Mario Rossi\nBest film Candidate B\n")
    assert "Mario Rossi" not in r.text and r.hidden == 1
    assert "Best film Candidate B" in r.text


def test_a_short_label_does_not_take_the_line_of_a_longer_one(settings):
    attachment_mask.save_field_rules(1, [rule("Name", "fixed", "X"), rule("Name and surname")])
    r = attachment_mask.apply(1, "Name and surname Mario Rossi\nNames of the films: none\n")
    assert r.text.startswith("Name and surname [NAME_AND_SURNAME_")
    assert "Names of the films: none" in r.text
    assert r.unmatched == ["Name"]


def test_a_short_value_is_replaced_only_next_to_its_label(settings):
    attachment_mask.save_field_rules(1, [rule("Row")])
    r = attachment_mask.apply(1, "Row B\nBest film Candidate B\n")
    assert "Best film Candidate B" in r.text and r.hidden == 1


def test_a_field_rule_wins_over_the_detectors(settings):
    attachment_mask.save_field_rules(1, [rule("Email", "fixed", "hidden@example.com")])
    r = attachment_mask.apply(1, f"Email {EMAIL}\nWrite to {EMAIL}\nIBAN {IBAN}\n")
    assert r.text.count("hidden@example.com") == 2
    assert EMAIL not in r.text and IBAN not in r.text and "[IBAN_" in r.text


def test_a_field_that_is_not_there_is_reported(settings):
    attachment_mask.save_field_rules(1, [rule("Full name"), rule("Tax code")])
    r = attachment_mask.apply(1, FORM)
    assert r.unmatched == ["Tax code"]


def test_rules_belong_to_their_account(settings):
    attachment_mask.save_field_rules(1, [rule("Full name")])
    assert attachment_mask.field_rules(2) == []
    assert "Mario Rossi" in attachment_mask.apply(2, FORM).text


@pytest.mark.parametrize("bad", [
    [{"label": "", "action": "placeholder"}],
    [{"label": "Full name", "action": "erase"}],
    [{"label": "Address", "action": "fixed", "value": " "}],
    [{"label": "Full name"}, {"label": "full  NAME"}],
    [{"label": "x" * 81}],
    "Full name",
])
def test_unusable_rules_are_refused(settings, bad):
    with pytest.raises(ValueError):
        attachment_mask.save_field_rules(1, bad)
    assert attachment_mask.field_rules(1) == []


def test_rules_that_cannot_be_read_stop_the_masking(settings):
    settings["mask_attachment_fields_account_1"] = "{not json"
    with pytest.raises(ValueError):
        attachment_mask.apply(1, FORM)


# ── read_attachment ──────────────────────────────────────────────────

def test_read_attachment_is_in_clear_when_the_switch_is_off(mailbox):
    mailbox["ballot.txt"] = BALLOT
    r = server.read_attachment(message_id="42", filename="ballot.txt")
    assert r == {"filename": "ballot.txt", "kind": "text", "text": BALLOT.strip()}


def test_read_attachment_masks_when_the_switch_is_on(mailbox):
    mailbox["ballot.txt"] = BALLOT
    attachment_mask.set_enabled(1, True)
    r = server.read_attachment(message_id="42", filename="ballot.txt")
    assert EMAIL not in r["text"] and IBAN not in r["text"]
    assert "Vote: candidate B" in r["text"]
    assert r["masked"] is True
    assert "placeholder" in r["note"]


def test_read_attachment_follows_the_account_it_reads(mailbox):
    mailbox["ballot.txt"] = BALLOT
    attachment_mask.set_enabled(2, True)
    assert EMAIL in server.read_attachment(message_id="42", filename="ballot.txt")["text"]
    r = server.read_attachment(message_id="42", filename="ballot.txt", account_id=2)
    assert EMAIL not in r["text"]


def test_no_note_when_nothing_was_hidden(mailbox):
    mailbox["notes.txt"] = "Vote: candidate B"
    attachment_mask.set_enabled(1, True)
    r = server.read_attachment(message_id="42", filename="notes.txt")
    assert r["text"] == "Vote: candidate B"
    assert r["masked"] is True and "note" not in r


def test_a_masker_failure_never_releases_the_clear_text(mailbox, monkeypatch):
    mailbox["ballot.txt"] = BALLOT

    def broken(*a, **kw):
        raise RuntimeError("masker down")
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply", broken)
    r = server.read_attachment(message_id="42", filename="ballot.txt")
    assert EMAIL not in r["text"] and IBAN not in r["text"]
    assert "Not read" in r["text"]
    assert r["masked"] is True


def test_read_attachment_applies_field_rules_and_says_what_is_invented(mailbox):
    mailbox["ballot.txt"] = FORM
    attachment_mask.set_enabled(1, True)
    attachment_mask.save_field_rules(1, [rule("Full name", "fake_name"), rule("Tax code")])
    r = server.read_attachment(message_id="42", filename="ballot.txt")
    assert "Mario Rossi" not in r["text"]
    assert "invented" in r["note"]
    assert r["fields_not_found"] == ["Tax code"]


def test_field_rules_do_nothing_while_the_switch_is_off(mailbox):
    mailbox["ballot.txt"] = FORM
    attachment_mask.save_field_rules(1, [rule("Full name")])
    r = server.read_attachment(message_id="42", filename="ballot.txt")
    assert "Mario Rossi" in r["text"] and "masked" not in r


def test_unreadable_rules_never_release_the_clear_text(mailbox, settings):
    mailbox["ballot.txt"] = FORM
    attachment_mask.set_enabled(1, True)
    settings["mask_attachment_fields_account_1"] = "{not json"
    r = server.read_attachment(message_id="42", filename="ballot.txt")
    assert "Mario Rossi" not in r["text"] and "Not read" in r["text"]


# ── read_message ─────────────────────────────────────────────────────

MAIL_BODY = (
    f"Good morning,\nplease call me on 333 1234567 or write to {EMAIL}.\n"
    "Full name: Mario Rossi\nThe visit is on Friday at 17:00.\n"
)


@pytest.fixture
def inbox(monkeypatch, settings):
    """read_message serves one plain-text mail from memory."""
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: {"id": 1})
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {
        "id": "42", "subject": "Visit on Friday",
        "from": {"emailAddress": {"address": "client@example.com"}},
        "body": {"contentType": "text", "content": MAIL_BODY},
        "attachments": [],
    })


def test_read_message_is_in_clear_when_the_switch_is_off(inbox):
    r = server.read_message(message_id="42")
    assert EMAIL in r["body"]["content"] and "masked" not in r


def test_read_message_masks_the_body_and_keeps_who_wrote(inbox):
    attachment_mask.set_enabled(1, True)
    attachment_mask.save_field_rules(1, [rule("Full name", "fake_name")])
    r = server.read_message(message_id="42")
    for text in (r["body"]["content"], r["body_text"], r["bodyPreview"]):
        assert EMAIL not in text and "333 1234567" not in text and "Mario Rossi" not in text
        assert "[EMAIL_" in text
    assert "Friday at 17:00" in r["body"]["content"]
    assert r["subject"] == "Visit on Friday"
    assert r["from"]["emailAddress"]["address"] == "client@example.com"
    assert r["masked"] is True
    assert "placeholder" in r["note"] and "invented" in r["note"]
    assert "fields_not_found" not in r


def test_the_same_value_has_one_placeholder_in_mail_and_attachment(inbox, mailbox):
    mailbox["ballot.txt"] = BALLOT
    attachment_mask.set_enabled(1, True)
    body = server.read_message(message_id="42")["body"]["content"]
    attached = server.read_attachment(message_id="42", filename="ballot.txt")["text"]
    ph = re.search(r"\[EMAIL_[0-9a-f]{8}\]", body).group(0)
    assert ph in attached


def test_links_do_not_give_back_what_the_body_hides(inbox, monkeypatch):
    monkeypatch.setattr(server.mail_router, "get_message", lambda **kw: {
        "id": "42", "subject": "Contacts",
        "body": {"contentType": "html", "content":
                 f'<p>Write to <a href="mailto:{EMAIL}">{EMAIL}</a> or see '
                 '<a href="https://example.com/call/333">the call page</a>.</p>'},
    })
    attachment_mask.set_enabled(1, True)
    r = server.read_message(message_id="42")
    assert EMAIL not in str(r["links"]) and EMAIL not in r["body"]["content"]
    assert {"text": "the call page", "url": "https://example.com/call/333"} in r["links"]
    assert any(link["url"].startswith("mailto:[EMAIL_") for link in r["links"])


def test_a_masker_failure_withholds_the_body(inbox, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("masker down")
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply", broken)
    r = server.read_message(message_id="42")
    assert r["body"]["content"] == "" and r["body_text"] == "" and r["bodyPreview"] == ""
    assert r["links"] == [] and "masking failed" in r["withheld"]
    assert EMAIL not in str(r)


def test_no_mcp_tool_switches_the_mask():
    names = [n for n in dir(server) if "mask" in n.lower() and not n.startswith("_")
             and callable(getattr(server, n))]
    assert names == []


# ── the console API ──────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, settings):
    from gigamail import http_api
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "local-test-token")
    monkeypatch.delenv("ADE_MAIL_DRYRUN", raising=False)
    importlib.reload(http_api)
    with TestClient(http_api.app, headers={"X-ADE-Token": "local-test-token"}) as c:
        yield c
    # The app was built with a token: leave the next test file the app
    # without one, as it would have found it.
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


def test_console_switches_the_mask(client, monkeypatch):
    from gigamail.http_api import accounts
    monkeypatch.setattr(accounts.core_accounts, "get_account_by_id",
                        lambda aid: {"id": aid} if aid == 1 else None)
    got = client.get("/accounts/1/attachment-mask").json()
    assert got == {"enabled": False, "fields": [], "types": ALL_TYPES, "all_types": ALL_TYPES}
    r = client.post("/accounts/1/attachment-mask", json={"enabled": True})
    assert r.json()["enabled"] is True
    assert attachment_mask.enabled(1) is True
    assert client.post("/accounts/9/attachment-mask", json={"enabled": True}).status_code == 404


def test_console_saves_field_rules(client, monkeypatch):
    from gigamail.http_api import accounts
    monkeypatch.setattr(accounts.core_accounts, "get_account_by_id", lambda aid: {"id": aid})
    fields = [{"label": " Full  name ", "action": "fake_name"}]
    r = client.post("/accounts/1/attachment-mask", json={"enabled": True, "fields": fields})
    assert r.json()["enabled"] is True
    assert r.json()["fields"] == [{"label": "Full name", "action": "fake_name", "value": ""}]
    # The switch alone leaves the rules as they are, and the other way round.
    client.post("/accounts/1/attachment-mask", json={"enabled": False})
    got = client.get("/accounts/1/attachment-mask").json()
    assert got["enabled"] is False and len(got["fields"]) == 1
    client.post("/accounts/1/attachment-mask", json={"fields": []})
    got = client.get("/accounts/1/attachment-mask").json()
    assert got["enabled"] is False and got["fields"] == []
    bad = client.post("/accounts/1/attachment-mask",
                      json={"fields": [{"label": "Address", "action": "fixed"}]})
    assert bad.status_code == 400


def test_console_chooses_the_types(client, monkeypatch):
    from gigamail.http_api import accounts
    monkeypatch.setattr(accounts.core_accounts, "get_account_by_id", lambda aid: {"id": aid})
    r = client.post("/accounts/1/attachment-mask", json={"types": ["IBAN", "EMAIL"]})
    assert r.json()["types"] == ["IBAN", "EMAIL"]
    assert r.json()["all_types"] == ALL_TYPES
    # A request with one bad part changes nothing.
    bad = client.post("/accounts/1/attachment-mask",
                      json={"types": [], "fields": [{"label": ""}]})
    assert bad.status_code == 400
    assert client.get("/accounts/1/attachment-mask").json()["types"] == ["IBAN", "EMAIL"]
    assert client.post("/accounts/1/attachment-mask",
                       json={"types": ["PASSPORT"]}).status_code == 400

# ── invented names: room for many people ─────────────────────────────

def test_invented_names_do_not_repeat_among_a_few_hundred_people():
    """With one first name and one surname there were 2,000 names, and
    among a hundred people two shared one nine times out of ten: an agent
    reading the forms took two people for the same one."""
    key = b"a fixed secret, so this test always draws the same names"
    names = {attachment_mask._fake_name(key, f"person {i}") for i in range(300)}
    assert len(names) == 300
    firsts, lasts = len(attachment_mask._FIRST_NAMES), len(attachment_mask._LAST_NAMES)
    assert firsts * (firsts - 1) * lasts * (lasts - 1) > 3_000_000


# ── the prompts GigaMail writes itself ───────────────────────────────
# The watcher's drafts, the follow-up after an appointment and the
# console's draft button put the mail's text in a prompt without any MCP
# tool: with the switch on, that text is masked too.

def test_for_agent_leaves_the_text_alone_while_the_switch_is_off(settings):
    assert attachment_mask.for_agent(1, MAIL_BODY) == (MAIL_BODY, "")


def test_for_agent_masks_and_says_so(settings):
    attachment_mask.set_enabled(1, True)
    attachment_mask.save_field_rules(1, [rule("Full name", "fake_name")])
    text, note = attachment_mask.for_agent(1, MAIL_BODY)
    assert EMAIL not in text and "Mario Rossi" not in text
    assert "The visit is on Friday at 17:00." in text
    assert "placeholder" in note and "invented" in note


def test_for_agent_raises_when_the_masking_fails(settings, monkeypatch):
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask.ade_masker, "detect",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        attachment_mask.for_agent(1, MAIL_BODY)


def _incoming():
    return {"id": "42", "subject": "Visit on Friday",
            "from": {"emailAddress": {"address": "client@example.com"}},
            "body": {"contentType": "text", "content": MAIL_BODY}}


def test_the_watcher_draft_prompt_is_in_clear_when_the_switch_is_off(settings):
    from gigamail.watcher import drafting
    prompt = drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 1, _incoming())
    assert EMAIL in prompt and "NOTE ON THE MAIL ABOVE" not in prompt


def test_the_watcher_draft_prompt_is_masked_when_the_switch_is_on(settings):
    from gigamail.watcher import drafting
    attachment_mask.set_enabled(1, True)
    prompt = drafting.build_draft_prompt({"rule_id": "r", "reply_style": ""}, 1, _incoming())
    assert EMAIL not in prompt and "333 1234567" not in prompt
    assert PLACEHOLDER.search(prompt)
    assert "The visit is on Friday at 17:00." in prompt
    # The note comes after the mail, outside the untrusted block.
    assert prompt.index("=== FINE MAIL ===") < prompt.index("NOTE ON THE MAIL ABOVE")
    # Who wrote stays: without it the reply has nobody to go to.
    assert "client@example.com" in prompt


def test_no_watcher_draft_when_the_masking_fails(settings, monkeypatch):
    from gigamail import agent_bridge
    from gigamail.watcher import drafting
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(agent_bridge, "run", lambda *a, **kw: pytest.fail(
        "the agent must not be called with a mail that could not be masked"))
    with pytest.raises(drafting.MailConOrdini) as e:
        drafting.draft_reply({"rule_id": "r", "reply_style": ""}, 1, _incoming())
    assert e.value.reasons == ["mask_failed"]


def test_the_follow_up_prompt_is_masked_when_the_switch_is_on(settings, monkeypatch):
    from gigamail.watcher import after_appointment, tg_risposte
    monkeypatch.setattr(tg_risposte, "_doc_paths", lambda aid: [])
    monkeypatch.setattr(after_appointment.mail_memory, "client_notes", lambda email: "")
    row = {"account_id": 1, "thread_key": "client@example.com|visit on friday",
           "start": "2026-11-06T17:00", "video": False}
    assert EMAIL in after_appointment._prompt(row, _incoming())
    attachment_mask.set_enabled(1, True)
    prompt = after_appointment._prompt(row, _incoming())
    assert EMAIL not in prompt and PLACEHOLDER.search(prompt)
    assert "NOTE ON THE MAIL ABOVE" in prompt


def test_the_follow_up_shows_no_mail_when_the_masking_fails(settings, monkeypatch):
    from gigamail.watcher import after_appointment, tg_risposte
    monkeypatch.setattr(tg_risposte, "_doc_paths", lambda aid: [])
    monkeypatch.setattr(after_appointment.mail_memory, "client_notes", lambda email: "")
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    row = {"account_id": 1, "thread_key": "client@example.com|visit on friday",
           "start": "2026-11-06T17:00", "video": False}
    prompt = after_appointment._prompt(row, _incoming())
    assert EMAIL not in prompt and "333 1234567" not in prompt
    assert "masking failed" in prompt


def _console_draft(monkeypatch, seen):
    from gigamail.http_api import agent as agent_api
    monkeypatch.setattr(agent_api.mail_router, "get_message", lambda *a, **kw: _incoming())
    monkeypatch.setattr(agent_api.agent_bridge, "run",
                        lambda prompt, **kw: seen.append(prompt) or "A reply.")
    monkeypatch.setattr(agent_api, "_documenti_context", lambda *a, **kw: "")
    monkeypatch.setattr(agent_api, "_suggest_attachments", lambda *a, **kw: [])
    req = agent_api.SmartDraftRequest(subject="Visit on Friday", sender="client@example.com")
    return agent_api.smart_draft("42", req, account_id=1)


def test_the_console_draft_prompt_is_masked_when_the_switch_is_on(settings, monkeypatch):
    seen = []
    _console_draft(monkeypatch, seen)
    assert EMAIL in seen[-1]
    attachment_mask.set_enabled(1, True)
    out = _console_draft(monkeypatch, seen)
    assert out["draft"] == "A reply." and out["blocked"] is False
    assert EMAIL not in seen[-1] and PLACEHOLDER.search(seen[-1])
    assert "NOTE ON THE EMAIL ABOVE" in seen[-1]


def test_no_console_draft_when_the_masking_fails(settings, monkeypatch):
    from fastapi import HTTPException
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    seen = []
    with pytest.raises(HTTPException) as e:
        _console_draft(monkeypatch, seen)
    assert e.value.status_code == 503 and seen == []
