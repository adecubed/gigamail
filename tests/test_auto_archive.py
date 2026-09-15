"""Archiviazione automatica: sposta le mail di un mittente, ma solo quando
nessuna regola ha piu' bisogno di trovarle nella posta in arrivo."""
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

from ade_mail_agent.core import mail_router
from ade_mail_agent.core import rules as rules_mod
from ade_mail_agent.watcher import archive

ACCOUNT = 902
W = SimpleNamespace(verbose=False)


def _msg(mid, mittente, minuti_fa=1):
    quando = datetime.now(timezone.utc) - timedelta(minutes=minuti_fa)
    return {"id": mid, "subject": "x", "receivedDateTime": format_datetime(quando),
            "from": {"emailAddress": {"address": mittente}}}


@pytest.fixture()
def casella(monkeypatch):
    impostazioni, spostate, posta = {}, [], []
    monkeypatch.setattr(archive.core_accounts, "get_setting",
                        lambda k, d="": impostazioni.get(k, d))
    monkeypatch.setattr(archive.core_accounts, "set_setting",
                        lambda k, v: impostazioni.__setitem__(k, v))
    monkeypatch.setattr(mail_router, "get_messages", lambda **kw: list(posta))

    def _sposta(account_id=None, message_id="", folder_id="", source_folder=None):
        spostate.append((account_id, message_id, folder_id, source_folder))
        return True
    monkeypatch.setattr(mail_router, "move_to_folder", _sposta)
    archive._falliti.clear()
    archive.aggiungi(ACCOUNT, ["idealista.it"], "INBOX.idealista",
                     dal=time.time() - 3600)
    yield posta, spostate
    archive._falliti.clear()


def _regola():
    return rules_mod.store().create(
        account_id=ACCOUNT, trigger_kind="senders",
        trigger_values=["reply@idealista.it"], reply_style="cordiale",
        doc_paths=[], mode="semi", created_by="test",
        hello_verified_at=time.time())


def test_newsletter_senza_regola_si_sposta_subito(casella):
    posta, spostate = casella
    posta[:] = [_msg("n1", "news@quotidiano.idealista.it")]
    assert archive.archivia(W) == 1
    assert spostate == [(ACCOUNT, "n1", "INBOX.idealista", "INBOX")]


def test_la_richiesta_resta_finche_la_regola_non_ha_finito(casella):
    """IMAP cambia l'id di una mail spostata: una bozza in approvazione o da
    rifare non la ritroverebbe piu'."""
    posta, spostate = casella
    rid = _regola()
    posta[:] = [_msg("r1", "reply@idealista.it")]
    assert archive.archivia(W) == 0, "la regola non l'ha ancora vista"
    rules_mod.store().record(rid, ACCOUNT, "r1", "reply@idealista.it",
                             "awaiting_approval", "", "req_x")
    assert archive.archivia(W) == 0, "in approvazione: resta dov'e'"
    rules_mod.store().set_status(rid, "r1", "sent")
    assert archive.archivia(W) == 1
    assert spostate == [(ACCOUNT, "r1", "INBOX.idealista", "INBOX")]


def test_bozza_fallita_resta_nella_posta_in_arrivo(casella):
    posta, spostate = casella
    rid = _regola()
    posta[:] = [_msg("f1", "reply@idealista.it")]
    rules_mod.store().record(rid, ACCOUNT, "f1", "reply@idealista.it", "failed")
    assert archive.archivia(W) == 0 and spostate == []


def test_posta_vecchia_e_altri_domini_non_si_toccano(casella):
    posta, spostate = casella
    posta[:] = [_msg("old", "news@idealista.it", minuti_fa=24 * 60),
                _msg("x1", "truffa@idealista.it.esempio.com"),
                _msg("x2", "cliente@gmail.com")]
    assert archive.archivia(W) == 0 and spostate == []


def test_spostamento_fallito_non_si_ripete_allinfinito(casella, monkeypatch):
    posta, _ = casella
    tentativi = []
    monkeypatch.setattr(mail_router, "move_to_folder",
                        lambda *a, **k: tentativi.append(1) or False)
    posta[:] = [_msg("n2", "news@idealista.it")]
    for _ in range(6):
        archive.archivia(W)
    assert len(tentativi) == archive._TENTATIVI_MAX


def test_senza_configurazione_non_legge_la_posta(monkeypatch):
    monkeypatch.setattr(archive.core_accounts, "get_setting", lambda k, d="": "")
    monkeypatch.setattr(mail_router, "get_messages",
                        lambda **kw: pytest.fail("non doveva leggere la posta"))
    assert archive.archivia(W) == 0


def test_del_dominio():
    assert archive.del_dominio("Reply@Idealista.it", ["idealista.it"])
    assert archive.del_dominio("news@mailing.idealista.it", ["idealista.it"])
    assert not archive.del_dominio("a@notidealista.it", ["idealista.it"])
    assert not archive.del_dominio("senza-chiocciola", ["idealista.it"])
