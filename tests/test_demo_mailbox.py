"""Casella su file: il router la serve come le altre, e non esce niente.

Il valore della casella finta sta nel fatto che i chiamanti non se ne
accorgono. Se la forma dei messaggi diverge da quella di IMAP e Graph,
quello che si riprende non e' quello che gira in produzione.
"""
import json

import pytest

from ade_mail_agent.core import accounts, demo_mailbox, mail_router

MITTENTE = "io@studio.example"

MESSAGGI = [
    {"id": "1001", "folder": "Lead", "subject": "Informazioni A12",
     "from": {"name": "Giulia Rossi", "address": "giulia@example.com"},
     "to": [MITTENTE], "body": "Vorrei sapere il prezzo dell'A12."},
    {"id": "1002", "folder": "inbox", "subject": "Fattura",
     "from": {"name": "Studio Marelli", "address": "amm@marelli.example"},
     "to": [MITTENTE], "body": "In allegato la fattura."},
]


@pytest.fixture()
def demo_account(tmp_path):
    seme = tmp_path / "casella.json"
    demo_mailbox.scrivi_seme(str(seme), MESSAGGI,
                             [{"id": "Lead", "name": "Lead", "displayName": "Lead"}])
    aid = accounts.add_demo_account("Demo", MITTENTE, str(seme))
    accounts.set_active_account(aid)
    yield aid
    accounts.delete_account(aid)


def test_le_cartelle_hanno_le_loro_mail(demo_account):
    lead = mail_router.get_messages(demo_account, folder="Lead")
    assert [m["id"] for m in lead] == ["1001"]
    inbox = mail_router.get_messages(demo_account, folder="inbox")
    assert [m["id"] for m in inbox] == ["1002"]


def test_il_messaggio_ha_la_forma_di_sempre(demo_account):
    m = mail_router.get_message(demo_account, "1001")
    assert m["from"]["emailAddress"]["address"] == "giulia@example.com"
    assert m["body"]["content"].startswith("Vorrei sapere")
    assert m["toRecipients"][0]["emailAddress"]["address"] == MITTENTE


def test_le_barriere_antispam_vedono_posta_autenticata(demo_account):
    """Senza dmarc=pass le regole non partirebbero mai, e in ripresa
    sembrerebbe un guasto."""
    h = mail_router.get_message_headers(demo_account, "1001")
    assert any("dmarc=pass" in v for v in h["authentication-results"])


def test_la_risposta_va_al_mittente_originale_e_non_esce(demo_account):
    """Il confine strutturale: rispondere non sposta il destinatario. E il
    messaggio resta nel file, non parte da nessuna parte."""
    esito = mail_router.reply_message(demo_account, "1001", body="Il prezzo e' 395.000.")
    assert esito["success"] is True
    inviate = mail_router.get_messages(demo_account, folder="sentitems")
    assert len(inviate) == 1
    inviata = mail_router.get_message(demo_account, inviate[0]["id"])
    assert inviata["toRecipients"][0]["emailAddress"]["address"] == "giulia@example.com"
    assert inviata["subject"] == "Re: Informazioni A12"


def test_cancellare_mette_nel_cestino(demo_account):
    assert mail_router.delete_message(demo_account, "1002") is True
    assert mail_router.get_messages(demo_account, folder="inbox") == []
    assert [m["id"] for m in mail_router.get_messages(demo_account, folder="deleteditems")] == ["1002"]


def test_riparti_rimette_tutto_al_via(demo_account):
    mail_router.set_read_status(demo_account, "1001", is_read=True)
    mail_router.delete_message(demo_account, "1002")
    demo_mailbox.reset(accounts.get_account_by_id(demo_account))
    assert mail_router.get_messages(demo_account, folder="inbox")[0]["id"] == "1002"
    assert mail_router.get_messages(demo_account, folder="Lead")[0]["isRead"] is False


def test_il_calendario_demo_e_vuoto_e_non_chiede_login(demo_account):
    from ade_mail_agent.core import calendar_router
    assert calendar_router.provider() == "demo"
    assert calendar_router.get_events() == []


def test_il_seme_non_viene_modificato(demo_account, tmp_path):
    """Si lavora sulla copia: il file di partenza resta buono per la ripresa
    successiva."""
    prima = json.loads((tmp_path / "casella.json").read_text(encoding="utf-8"))
    mail_router.set_read_status(demo_account, "1001", is_read=True)
    dopo = json.loads((tmp_path / "casella.json").read_text(encoding="utf-8"))
    assert prima == dopo
