# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Destinatari: anteprima e busta devono dire la stessa cosa."""
from ade_mail_agent import policy
from ade_mail_agent.core.addresses import split_addresses


def test_stringa_con_piu_indirizzi_non_e_un_destinatario():
    """Regressione: `to` arrivava intera in busta — un solo RCPT TO
    malformato invece di due destinatari, con l'invio che tornava success
    e "accepted: 1". Meta' della gente non riceveva niente e nessuno lo
    vedeva."""
    assert split_addresses("info@fingroupspa.com, maderna@fingroupspa.com") == [
        "info@fingroupspa.com", "maderna@fingroupspa.com"]
    assert split_addresses("a@x.it; b@y.it") == ["a@x.it", "b@y.it"]
    assert split_addresses("Nome Cognome <b@y.it>") == ["b@y.it"]
    assert split_addresses(["a@x.it", "b@y.it"]) == ["a@x.it", "b@y.it"]
    assert split_addresses("") == [] and split_addresses(None) == []
    assert split_addresses("solo@uno.it") == ["solo@uno.it"]


def test_anteprima_e_busta_non_possono_divergere():
    """L'anteprima che l'umano approva elenca ESATTAMENTE gli indirizzi
    che finiranno in busta: stesso split, una funzione sola."""
    to = "info@fingroupspa.com, maderna@fingroupspa.com"
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
