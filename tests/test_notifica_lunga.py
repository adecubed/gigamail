"""La bozza si legge INTERA sul telefono.

Chi approva da Telegram vedeva i primi 400 caratteri e basta: una
risposta con quattro appartamenti, metrature e prezzi si fermava alla
seconda riga, e il resto esisteva solo nella console. Peggio, oltre i
4000 caratteri il canale tagliava il testo senza dirlo.
"""
import time

import pytest

from gigamail.core import rules as rules_mod
from gigamail.core.telegram_channel import Telegram
from gigamail.watcher import notify

BOZZA_LUNGA = "\n".join(
    [f"- A.{p}.{n}: bilocale di 62,3{n} mq con balcone di 10,3{n} mq, "
     f"totale commerciale 72,7{n} mq, prezzo 28{n}.000 euro, "
     f"con box 31{n}.000 euro." for p in range(4) for n in range(1, 5)])


@pytest.fixture(autouse=True)
def store(tmp_path):
    rules_mod.set_store(rules_mod.RuleStore(tmp_path / "rules.db"))
    yield
    rules_mod.set_store(None)


def _regola():
    rid = rules_mod.store().create(
        account_id=1, trigger_kind="senders", trigger_values=["x@y.it"],
        reply_style="", doc_paths=[], mode="semi", created_by="test",
        hello_verified_at=time.time())
    return rules_mod.store().get(rid)


def _msg():
    return {"id": "1", "subject": "Bilocale in Via Roma",
            "from": {"emailAddress": {"address": "cliente@x.it"}}}


# ── il testo della notifica ──────────────────────────────────────────

def test_la_bozza_entra_intera_nella_notifica():
    assert len(BOZZA_LUNGA) > 400          # prima veniva tagliata qui
    testo = notify._semi_notify_text(_regola(), _msg(), BOZZA_LUNGA, "req_1")
    assert BOZZA_LUNGA in testo
    assert "req_1" in testo                # e l'istruzione per approvare resta


def test_una_bozza_enorme_dichiara_il_taglio(monkeypatch):
    monkeypatch.setattr(notify, "_NOTIFY_BODY_CHARS", 50)
    testo = notify._semi_notify_text(_regola(), _msg(), BOZZA_LUNGA, "req_1")
    assert notify._TRONCATO in testo


def test_anche_lavviso_di_invio_automatico_porta_tutto():
    testo = notify._auto_notify_text(_regola(), _msg(), BOZZA_LUNGA, ok=True)
    assert BOZZA_LUNGA in testo


# ── lo spezzettamento per Telegram ───────────────────────────────────

def test_testo_corto_resta_un_pezzo_solo():
    assert Telegram.a_pezzi("ciao") == ["ciao"]


def test_testo_lungo_spezzato_e_nulla_si_perde():
    testo = "\n".join(f"riga numero {i} con un po' di testo" for i in range(600))
    pezzi = Telegram.a_pezzi(testo)
    assert len(pezzi) > 1
    assert all(len(p) <= Telegram.TG_MAX_CHARS for p in pezzi)
    # nessuna riga persa per strada
    unite = "\n".join(pezzi)
    for i in (0, 313, 599):
        assert f"riga numero {i} con" in unite


def test_il_taglio_non_spezza_unentita_html():
    """Meta' entita' fa fallire l'invio con parse_mode HTML: il messaggio
    non arriverebbe affatto."""
    testo = ("&amp; " * 2000).strip()
    for pezzo in Telegram.a_pezzi(testo, limite=100):
        assert pezzo.count("&") == pezzo.count(";")


def test_i_bottoni_vanno_sullultimo_pezzo(monkeypatch):
    inviati = []

    class Finto(Telegram):
        def __init__(self):
            self.chat_id = 1

        def _call(self, metodo, **params):
            inviati.append(params)
            return {"result": {"message_id": len(inviati)}}

    tg = Finto()
    testo = "x" * (Telegram.TG_MAX_CHARS * 2 + 10)
    bottoni = [[{"text": "Approva", "callback_data": "ok"}]]
    ultimo = tg.send_message(testo, buttons=bottoni)
    assert len(inviati) == 3
    assert "reply_markup" not in inviati[0] and "reply_markup" not in inviati[1]
    assert inviati[-1]["reply_markup"] == {"inline_keyboard": bottoni}
    assert ultimo == 3                     # l'id e' quello con i bottoni
