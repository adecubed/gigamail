# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Allegati: solo i file che l'utente ha registrato per quell'account."""
import pytest

from gigamail import server
from gigamail.core import attachments as att


@pytest.fixture
def identity(tmp_path, monkeypatch):
    """Un account con un solo file registrato, e un segreto fuori."""
    reg = tmp_path / "registrati"
    reg.mkdir()
    (reg / "A.7.4.pdf").write_bytes(b"%PDF-1.4 planimetria")
    segreto = tmp_path / "passwords.txt"
    segreto.write_text("roba che non deve uscire")
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])
    return reg, segreto


def test_allega_un_file_registrato(identity):
    reg, _ = identity
    risolti, mancanti = server._resolve_attachments(2, ["A.7.4"])
    assert mancanti == []
    assert [f["name"] for f in risolti] == ["A.7.4.pdf"]
    assert risolti[0]["path"] == str(reg / "A.7.4.pdf")


def test_a_name_never_reaches_a_file_outside_the_registered_ones(identity):
    """By name the agent gets only registered files: a name, a relative
    path or a path that does not exist never becomes an attachment."""
    _, secret = identity
    for attempt in ("passwords", "../passwords.txt", str(secret) + ".missing"):
        resolved, missing = server._resolve_attachments(2, [attempt])
        assert resolved == [], attempt
        assert len(missing) == 1 and attempt in missing[0]


def test_a_full_path_is_taken_and_marked_outside(identity, tmp_path):
    """The one way to a file outside the registered ones: its full path.
    The request carries the mark, the preview shows it with the path, and
    the content is fixed like any other attachment."""
    reg, secret = identity
    resolved, missing = server._resolve_attachments(2, ["A.7.4", str(secret)])
    assert missing == []
    inside, outside = resolved
    assert "outside" not in inside
    assert outside["outside"] is True and outside["name"] == "passwords.txt"
    assert outside["size"] == secret.stat().st_size and outside["sha256"]
    shown = server._attachments_preview(resolved)
    assert "outside" not in shown[0]
    assert shown[1]["outside"] is True and shown[1]["path"].endswith("passwords.txt")
    # a registered file asked by its path is not an outside file
    (same,), _ = server._resolve_attachments(2, [str(reg / "A.7.4.pdf")])
    assert "outside" not in same
    # changed after the request: nothing leaves
    secret.write_text("something else")
    with pytest.raises(att.AttachmentChanged):
        server._attachments_payload([outside])


def test_what_a_full_path_never_reaches(identity, tmp_path):
    from gigamail.core.data_paths import app_root
    program = tmp_path / "setup.exe"
    program.write_bytes(b"MZ")
    own = app_root() / "approvals-test.txt"
    own.write_text("GigaMail's own data")
    try:
        for path in (program, own, tmp_path):
            resolved, missing = server._resolve_attachments(2, [str(path)])
            assert resolved == [] and len(missing) == 1, path
    finally:
        own.unlink()


def test_a_rule_never_takes_a_path(identity):
    """Only the tools an agent calls on the user's request take a path:
    the watcher's rules resolve names, and a path there matches nothing."""
    _, secret = identity
    resolved, missing = att.resolve(2, [str(secret)])
    assert resolved == [] and missing == [str(secret)]


def test_an_outside_file_is_announced_and_cannot_be_approved_from_telegram(identity, tmp_path, monkeypatch):
    from gigamail import policy
    _, secret = identity
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    try:
        resolved, _ = server._resolve_attachments(2, ["A.7.4", str(secret)])
        args = {"to": "mario.rossi@example.com", "body": "hello", "attachments": resolved}
        preview = {"to": "mario.rossi@example.com", "subject": "Visit", "body": "hello",
                   "attachments": server._attachments_preview(resolved)}
        assert [f["name"] for f in policy.outside_files(args)] == ["passwords.txt"]
        labels = policy.attachment_labels(preview)
        assert labels[0] == "A.7.4.pdf"
        assert labels[1].startswith("passwords.txt (") and str(secret.parent) in labels[1]
        assert str(secret.parent) in policy.outside_warning(preview)
        assert str(secret.parent) in policy.full_preview_text("send_mail", preview)
        assert policy.outside_warning({"attachments": preview["attachments"][:1]}) == ""

        rid = policy.store().create("send_mail", args, preview)
        assert policy.store().approve(rid, by="telegram:1") is False
        assert policy.store().approve(rid, by="telegram:1+pin") is False
        assert policy.store().get(rid)["status"] == policy.PENDING
        assert policy.store().approve(rid, by="console:tester (console click)") is True
        # a mail with registered files only is approved from Telegram as before
        plain = policy.store().create("send_mail", {**args, "attachments": resolved[:1]}, {})
        assert policy.store().approve(plain, by="telegram:1") is True
    finally:
        policy.set_store(None)


def test_the_notification_carries_the_path_of_an_outside_file(identity, monkeypatch):
    from gigamail import policy
    from gigamail.core import desktop_notify
    _, secret = identity
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    shown = []
    monkeypatch.setattr(desktop_notify, "notify",
                        lambda title, text, **kw: shown.append(text) or True)
    resolved, _ = server._resolve_attachments(2, [str(secret)])
    preview = {"to": "mario.rossi@example.com", "subject": "Visit", "body": "hello",
               "attachments": server._attachments_preview(resolved)}
    policy._notify_now("req_x", "send_mail", preview)
    assert shown and "OUTSIDE" in shown[0] and str(secret.parent) in shown[0]


def test_nome_sconosciuto_non_parte_a_meta(identity):
    """Un nome che non risolve deve fermare la richiesta, non produrre
    una mail senza la planimetria che il testo promette."""
    risolti, mancanti = server._resolve_attachments(2, ["A.7.4", "B.9.9"])
    assert [f["name"] for f in risolti] == ["A.7.4.pdf"]
    assert mancanti == ["B.9.9"]


def test_anteprima_mostra_nome_percorso_e_dimensione(identity):
    """L'umano approva sapendo quale file esce e quanto pesa."""
    risolti, _ = server._resolve_attachments(2, ["A.7.4"])
    prev = server._attachments_preview(risolti)
    assert prev[0]["name"] == "A.7.4.pdf"
    assert prev[0]["path"].endswith("A.7.4.pdf")
    assert prev[0]["size_kb"] is not None


def test_payload_legge_i_byte_veri(identity):
    import base64
    risolti, _ = server._resolve_attachments(2, ["A.7.4"])
    payload = server._attachments_payload(risolti)
    assert payload[0]["type"] == "application/pdf"
    assert base64.b64decode(payload[0]["data_b64"]) == b"%PDF-1.4 planimetria"


def test_nessun_allegato_resta_nessun_allegato(identity):
    assert server._resolve_attachments(2, None) == ([], [])
    assert server._resolve_attachments(2, []) == ([], [])
    assert server._attachments_payload(None) == []


def test_codice_puntato_non_pesca_la_scheda_sbagliata(tmp_path, monkeypatch):
    """Regressione: os.path.splitext('B.7.3') -> ('B.7', '.3'), quindi il
    nome cercato diventava 'B.7' e come sottostringa pescava B.7.1, B.7.2,
    B.7.4. Nessun errore: la mail partiva con la planimetria di un altro
    appartamento. Vale anche per read_knowledge_file, che leggeva il file
    sbagliato."""
    from gigamail.core import identity_reader
    reg = tmp_path / "schede"
    reg.mkdir()
    for code in ("B.7.1", "B.7.2", "B.7.3", "B.7.4", "A.7.4"):
        (reg / f"{code}.pdf").write_bytes(b"%PDF " + code.encode())
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])

    trovati = identity_reader.find_files_by_names([str(reg)], ["B.7.3"])
    assert [f["name"] for f in trovati] == ["B.7.3.pdf"]

    risolti, mancanti = server._resolve_attachments(2, ["B.7.3", "A.7.4"])
    assert mancanti == []
    assert [f["name"] for f in risolti] == ["B.7.3.pdf", "A.7.4.pdf"]

    # l'estensione vera si toglie ancora
    risolti, _ = server._resolve_attachments(2, ["B.7.3.pdf"])
    assert [f["name"] for f in risolti] == ["B.7.3.pdf"]


def test_nome_ambiguo_non_sceglie_da_solo(tmp_path, monkeypatch):
    """Se un nome resta ambiguo la richiesta si ferma: meglio chiedere che
    allegare la planimetria di un altro appartamento."""
    reg = tmp_path / "schede"
    reg.mkdir()
    (reg / "B.8.1 bilo.pdf").write_bytes(b"%PDF a")
    (reg / "B.8.1 no balcone.pdf").write_bytes(b"%PDF b")
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])
    risolti, mancanti = server._resolve_attachments(2, ["B.8.1"])
    assert risolti == []
    assert len(mancanti) == 1 and "ambiguo" in mancanti[0]
