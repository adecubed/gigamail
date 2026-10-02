# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""L'allegato approvato e' legato al suo contenuto, non solo al percorso.

Fra l'approvazione e l'invio il file su disco si puo' sostituire
(Loopjacking): l'umano approva A.7.4.pdf e parte un altro contenuto con
lo stesso nome. L'hash fissato alla creazione della richiesta chiude la
finestra: se i byte cambiano, non parte niente."""
import base64
import hashlib

import pytest

from gigamail import policy, server
from gigamail.core import attachments as att

ORIGINALE = b"%PDF-1.4 planimetria A.7.4"


@pytest.fixture
def identity(tmp_path, monkeypatch):
    reg = tmp_path / "registrati"
    reg.mkdir()
    f = reg / "A.7.4.pdf"
    f.write_bytes(ORIGINALE)
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])
    return f


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    account = {"id": 1, "email": "me@example.test"}
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: account)
    monkeypatch.setattr(server.core_accounts, "get_account_by_id", lambda aid: account)
    monkeypatch.setattr(policy, "notify_approval_requested", lambda *a, **kw: None)
    yield
    policy.set_store(None)


def test_resolve_fissa_hash_e_dimensione(identity):
    risolti, mancanti = att.resolve(1, ["A.7.4"])
    assert mancanti == []
    assert risolti[0]["sha256"] == hashlib.sha256(ORIGINALE).hexdigest()
    assert risolti[0]["size"] == len(ORIGINALE)


def test_anteprima_mostra_l_impronta_fissata(identity):
    risolti, _ = att.resolve(1, ["A.7.4"])
    identity.write_bytes(b"altro contenuto, piu' lungo di prima")
    prev = att.preview(risolti)
    assert prev[0]["sha256"] == hashlib.sha256(ORIGINALE).hexdigest()[:12]
    # il peso e' quello approvato, non quello del file sostituito
    assert prev[0]["size_kb"] == round(len(ORIGINALE) / 1024, 1)


def test_payload_passa_se_il_file_non_e_cambiato(identity):
    risolti, _ = att.resolve(1, ["A.7.4"])
    out = att.payload(risolti)
    assert base64.b64decode(out[0]["data_b64"]) == ORIGINALE


def test_payload_rifiuta_un_file_sostituito(identity):
    risolti, _ = att.resolve(1, ["A.7.4"])
    identity.write_bytes(b"%PDF-1.4 un altro appartamento")
    with pytest.raises(att.AttachmentChanged, match="cambiato"):
        att.payload(risolti)


def test_richiesta_legacy_senza_hash_non_parte(identity):
    legacy = [{"name": "A.7.4.pdf", "path": str(identity)}]
    with pytest.raises(att.AttachmentChanged, match="non fissa"):
        att.payload(legacy)


def test_attachment_changed_e_un_value_error():
    assert issubclass(att.AttachmentChanged, ValueError)


def test_send_mail_approvata_non_spedisce_il_file_sostituito(
        identity, approvals, monkeypatch):
    sent = []
    monkeypatch.setattr(server.mail_router, "send_message",
                        lambda **kw: sent.append(kw) or {"success": True})
    pending = server.send_mail("client@example.test", "Planimetria",
                               "in allegato la planimetria",
                               attachments=["A.7.4"])
    record = policy.store().get(pending["request_id"])
    assert record["args"]["attachments"][0]["sha256"] == \
        hashlib.sha256(ORIGINALE).hexdigest()
    policy.store().approve(pending["request_id"])
    identity.write_bytes(b"%PDF-1.4 sostituito dopo l'approvazione")
    with pytest.raises(att.AttachmentChanged):
        server.send_mail("client@example.test", "Planimetria",
                         "in allegato la planimetria",
                         request_id=pending["request_id"])
    assert sent == []
