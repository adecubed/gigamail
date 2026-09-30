"""Gli allegati devono seguire quello che la mail DICE.

Due guasti veri, 19 e 23 settembre 2026. La regola aveva una terna fissa
di planimetrie: a chi chiedeva un quadrilocale sono partiti tre trilocali
del primo piano, e la mail giusta, quella che elencava gli appartamenti
davvero richiesti, e' uscita senza nessun file pur scrivendo "in allegato
trova le planimetrie".
"""
import re

import pytest

from gigamail import policy
from gigamail import server as srv
from gigamail.core import attachments, extensions


@pytest.fixture(autouse=True)
def store_isolato(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


# ── quali codici cita il testo: lo decidono le estensioni ────────────

class _Codici(extensions.Extension):
    name = "codici_prova"

    def cited_codes(self, text):
        return re.findall(r"\b[A-Z]\.[0-9]\.[0-9]\b", text or "")


def test_senza_estensioni_nessun_codice():
    """Il core non sa che forma abbia un codice: senza estensioni resta
    la lista fissa della regola."""
    assert attachments.codici_citati("La scheda A.3.2 in allegato.") == []


def test_codici_dalle_estensioni_in_ordine_e_senza_ripetizioni(estensione):
    estensione(_Codici())
    testo = "A.3.2 e B.0.1, poi di nuovo A.3.2."
    assert attachments.codici_citati(testo) == ["A.3.2", "B.0.1"]


def test_estensione_accesa_ma_assente_non_passa_in_silenzio(monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EXTENSIONS", "inesistente")
    with pytest.raises(extensions.ExtensionError):
        attachments.codici_citati("A.3.2")


# ── la mail promette un allegato? ────────────────────────────────────

@pytest.mark.parametrize("testo", [
    "In allegato trova le planimetrie di ciascuna soluzione.",
    "in allegati le schede",
    "Le allego la scheda tecnica.",
    "Trova la planimetria allegata.",
])
def test_promessa_riconosciuta(testo):
    assert attachments.promette_allegati(testo)


@pytest.mark.parametrize("testo", [
    "Le confermo l'appuntamento per giovedi' alle 17:00.",
    "I prezzi di partenza sono quelli indicati.",
    "",
])
def test_nessuna_promessa(testo):
    assert not attachments.promette_allegati(testo)


# ── il tool non spedisce una promessa a vuoto ────────────────────────

def test_send_mail_rifiuta_la_promessa_senza_file(monkeypatch):
    monkeypatch.setattr(srv, "_resolve_attachments",
                        lambda aid, nomi: ([], []))
    r = srv.send_mail(account_id=1, to="c@example.com", subject="Quadrilocali",
                      body="In allegato trova le planimetrie. Saluti")
    assert r["status"] == "error"
    assert "allegat" in r["error"].lower()
    # la richiesta di approvazione non nasce nemmeno
    assert policy.store().list_pending() == []


def test_reply_mail_rifiuta_la_promessa_senza_file(monkeypatch):
    monkeypatch.setattr(srv, "_resolve_attachments",
                        lambda aid, nomi: ([], []))
    r = srv.reply_mail(account_id=1, message_id="1",
                       body="Le allego le planimetrie richieste.")
    assert r["status"] == "error"
    assert policy.store().list_pending() == []


def test_mail_senza_promessa_passa_liscia(monkeypatch):
    monkeypatch.setattr(srv, "_resolve_attachments",
                        lambda aid, nomi: ([], []))
    monkeypatch.setattr(
        srv.core_accounts, "get_active_account", lambda: {"email": "io@x.it"})
    r = srv.send_mail(account_id=1, to="c@example.com", subject="Appuntamento",
                      body="Le confermo giovedi' alle 17:00.")
    assert r["status"] == "approval_required"


def test_promessa_con_file_risolti_passa(monkeypatch):
    monkeypatch.setattr(
        srv, "_resolve_attachments",
        lambda aid, nomi: ([{"name": "A.3.2.pdf", "path": "x/A.3.2.pdf"}], []))
    monkeypatch.setattr(srv, "_attachments_preview", lambda r: [])
    monkeypatch.setattr(
        srv.core_accounts, "get_active_account", lambda: {"email": "io@x.it"})
    r = srv.send_mail(account_id=1, to="c@example.com", subject="Quadrilocali",
                      body="In allegato trova la planimetria di A.3.2.",
                      attachments=["A.3.2.pdf"])
    assert r["status"] == "approval_required"
