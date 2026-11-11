# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Destinatari: anteprima e busta devono dire la stessa cosa."""
from gigamail import policy
from gigamail.core.addresses import split_addresses


def test_stringa_con_piu_indirizzi_non_e_un_destinatario():
    """Regressione: `to` arrivava intera in busta — un solo RCPT TO
    malformato invece di due destinatari, con l'invio che tornava success
    e "accepted: 1". Meta' della gente non riceveva niente e nessuno lo
    vedeva."""
    assert split_addresses("ufficio@agenzia.example, ops@agenzia.example") == [
        "ufficio@agenzia.example", "ops@agenzia.example"]
    assert split_addresses("a@x.it; b@y.it") == ["a@x.it", "b@y.it"]
    assert split_addresses("Nome Cognome <b@y.it>") == ["b@y.it"]
    assert split_addresses(["a@x.it", "b@y.it"]) == ["a@x.it", "b@y.it"]
    assert split_addresses("") == [] and split_addresses(None) == []
    assert split_addresses("solo@uno.it") == ["solo@uno.it"]


def test_anteprima_e_busta_non_possono_divergere():
    """L'anteprima che l'umano approva elenca ESATTAMENTE gli indirizzi
    che finiranno in busta: stesso split, una funzione sola."""
    to = "ufficio@agenzia.example, ops@agenzia.example"
    d = policy.describe_recipients(to, cc=["c@z.it"], bcc=None)
    assert [r["address"] for r in d["recipients"]] == (
        split_addresses(to) + split_addresses(["c@z.it"]))
    assert d["count"] == 3
    assert all(r["explicit"] for r in d["recipients"])
    assert "warning" not in d


def test_nome_nudo_resta_segnalato_dopo_lo_split():
    """Lo split non deve ingoiare l'avviso: un nome nudo o un gruppo puo'
    ancora espandersi a N destinatari dopo l'approvazione."""
    d = policy.describe_recipients("tutti-ufficio, a@x.it")
    assert d["count"] == 2
    assert [r["explicit"] for r in d["recipients"]] == [False, True]
    assert "tutti-ufficio" in d["warning"]


def test_a_list_element_holding_several_addresses_is_split_too():
    """The console sends the CC field as typed, as one element of a list:
    two people in copy were one malformed recipient, and neither got it."""
    assert split_addresses(["a@example.com, b@example.com"]) == [
        "a@example.com", "b@example.com"]
    assert split_addresses(["Mario Rossi <a@example.com>; b@example.com", "c@example.com"]) == [
        "a@example.com", "b@example.com", "c@example.com"]
    assert split_addresses([" ", ""]) == []


def test_two_people_in_copy_are_two_recipients_of_the_envelope(monkeypatch):
    from gigamail.core import imap_client

    sent = {}

    class Server:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def sendmail(self, sender, recipients, text):
            sent["recipients"] = list(recipients)
            sent["text"] = text
            return {}

    monkeypatch.setattr(imap_client.smtplib, "SMTP", Server)
    out = imap_client.send_message(
        "smtp.example.com", 587, "me@example.com", "secret", "notary@example.com",
        "Re: deed", "Fine.", cc=["a@example.com, b@example.com"])
    assert sent["recipients"] == ["notary@example.com", "a@example.com", "b@example.com"]
    assert "Cc: a@example.com, b@example.com" in sent["text"]
    assert out["success"] is True


def test_addresses_pasted_in_other_shapes_are_still_one_each():
    nl = chr(10)
    assert split_addresses(["a@example.com b@example.com"]) == ["a@example.com", "b@example.com"]
    assert split_addresses("a@example.com" + nl + "b@example.com") == [
        "a@example.com", "b@example.com"]
    assert split_addresses('"Rossi, Mario" <a@example.com>, b@example.com') == [
        "a@example.com", "b@example.com"]
    assert split_addresses(["mailto:a@example.com", None, "<b@example.com>"]) == [
        "a@example.com", "b@example.com"]


def test_what_no_server_can_deliver_to_is_named():
    from gigamail.core.addresses import malformed
    assert malformed(["a@example.com, Mario Rossi <b@example.com>"]) == []
    assert malformed("Mario Rossi a@example.com") == ["Mario Rossi a@example.com"]
    # a bare name may be an alias the server knows: not ours to refuse
    assert malformed("staff") == []


def test_a_malformed_recipient_stops_the_send_before_it_starts(monkeypatch):
    from gigamail.core import imap_client, mail_router

    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    monkeypatch.setattr(mail_router, "_account", lambda account_id=None: {
        "id": 1, "type": "imap", "email": "me@example.com"})
    called = []
    monkeypatch.setattr(imap_client, "send_message",
                        lambda *a, **k: called.append(1) or {"success": True})
    out = mail_router._send_backend(
        account_id=1, to="notary@example.com", subject="Re: deed", body="Fine.",
        cc=["Mario Rossi a@example.com"])
    assert out["success"] is False and called == []
    assert out["error"] == 'Not a valid recipient: "Mario Rossi a@example.com". Nothing was sent.'
