# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Il PIN che serve per approvare da un canale senza Hello."""
import pytest

from ade_mail_agent.core import approval_pin as ap


def test_il_pin_non_viene_mai_conservato_in_chiaro():
    """Un PIN in chiaro nello store sarebbe leggibile da chiunque apra il
    file: chi lo legge puo' approvare l'invio di mail dal telefono."""
    salvato = ap.hash_pin("739104")
    assert "739104" not in salvato
    assert salvato.startswith("scrypt$")
    assert ap.verify_pin("739104", salvato)
    assert not ap.verify_pin("739105", salvato)


def test_sale_diverso_a_ogni_impostazione():
    """Due PIN uguali non devono produrre lo stesso record: altrimenti chi
    legge lo store sa che due installazioni hanno lo stesso PIN."""
    assert ap.hash_pin("739104") != ap.hash_pin("739104")


def test_senza_pin_impostato_non_si_approva():
    """Un record mancante non deve diventare un lasciapassare: e' il modo
    in cui un controllo si trasforma in un buco durante una migrazione."""
    assert not ap.verify_pin("739104", "")
    assert not ap.verify_pin("739104", None)
    assert not ap.verify_pin("", ap.hash_pin("739104"))
    assert not ap.verify_pin("739104", "scrypt$rotto")
    assert not ap.verify_pin("739104", "md5$aa$bb")


@pytest.mark.parametrize("pin,ok", [
    ("739104", True), ("4907", True),
    ("123", False),            # troppo corto
    ("1234567890123", False),  # troppo lungo
    ("abcd", False),           # non cifre
    ("7391 04", False),
    ("0000", False),           # tutte uguali
    ("1234", False),           # fra i piu' provati al mondo
    ("", False),
])
def test_pin_deboli_rifiutati_alla_scelta(pin, ok):
    """Meglio dirlo mentre lo si sceglie che scoprirlo dopo: lo spazio dei
    PIN e' minuscolo e i primi tentativi di chiunque sono sempre quelli."""
    assert ap.valid_pin(pin)[0] is ok
    if not ok:
        assert ap.valid_pin(pin)[1]     # e spiega il perche'


def test_riconosce_un_messaggio_che_sembra_un_pin():
    """Serve a non scambiare per PIN una frase scritta in chat."""
    assert ap.looks_like_pin("739104")
    assert ap.looks_like_pin(" 4907 ")
    assert not ap.looks_like_pin("approva la mail")
    assert not ap.looks_like_pin("")
    assert not ap.looks_like_pin("12")
