# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Allegati: solo i file che l'utente ha registrato per quell'account."""
import pytest

from ade_mail_agent import server
from ade_mail_agent.core import attachments as att


@pytest.fixture
def identity(tmp_path, monkeypatch):
    """Un account con un solo file registrato, e un segreto fuori."""
    reg = tmp_path / "registrati"
    reg.mkdir()
    (reg / "A.1.4.pdf").write_bytes(b"%PDF-1.4 planimetria")
    segreto = tmp_path / "passwords.txt"
    segreto.write_text("roba che non deve uscire")
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])
    return reg, segreto


def test_allega_un_file_registrato(identity):
    reg, _ = identity
    risolti, mancanti = server._resolve_attachments(2, ["A.1.4"])
    assert mancanti == []
    assert [f["name"] for f in risolti] == ["A.1.4.pdf"]
    assert risolti[0]["path"] == str(reg / "A.1.4.pdf")


def test_percorso_arbitrario_non_e_allegabile(identity):
    """Il punto della funzione: un percorso fuori dall'identity non
    diventa un allegato. Senza questo, send_mail sarebbe il modo piu'
    comodo per far uscire un file qualunque dal disco."""
    _, segreto = identity
    for tentativo in (str(segreto), "passwords", "../passwords.txt",
                      r"C:\Windows\win.ini", "/etc/passwd"):
        risolti, mancanti = server._resolve_attachments(2, [tentativo])
        assert risolti == [], tentativo
        assert mancanti == [tentativo]


def test_nome_sconosciuto_non_parte_a_meta(identity):
    """Un nome che non risolve deve fermare la richiesta, non produrre
    una mail senza la planimetria che il testo promette."""
    risolti, mancanti = server._resolve_attachments(2, ["A.1.4", "B.9.9"])
    assert [f["name"] for f in risolti] == ["A.1.4.pdf"]
    assert mancanti == ["B.9.9"]


def test_anteprima_mostra_nome_percorso_e_dimensione(identity):
    """L'umano approva sapendo quale file esce e quanto pesa."""
    risolti, _ = server._resolve_attachments(2, ["A.1.4"])
    prev = server._attachments_preview(risolti)
    assert prev[0]["name"] == "A.1.4.pdf"
    assert prev[0]["path"].endswith("A.1.4.pdf")
    assert prev[0]["size_kb"] is not None


def test_payload_legge_i_byte_veri(identity):
    import base64
    risolti, _ = server._resolve_attachments(2, ["A.1.4"])
    payload = server._attachments_payload(risolti)
    assert payload[0]["type"] == "application/pdf"
    assert base64.b64decode(payload[0]["data_b64"]) == b"%PDF-1.4 planimetria"


def test_nessun_allegato_resta_nessun_allegato(identity):
    assert server._resolve_attachments(2, None) == ([], [])
    assert server._resolve_attachments(2, []) == ([], [])
    assert server._attachments_payload(None) == []


def test_codice_puntato_non_pesca_la_scheda_sbagliata(tmp_path, monkeypatch):
    """Regressione: os.path.splitext('B.1.3') -> ('B.1', '.3'), quindi il
    nome cercato diventava 'B.1' e come sottostringa pescava B.1.1, B.1.2,
    B.1.4. Nessun errore: la mail partiva con la planimetria di un altro
    appartamento. Vale anche per read_knowledge_file, che leggeva il file
    sbagliato."""
    from ade_mail_agent.core import identity_reader
    reg = tmp_path / "schede"
    reg.mkdir()
    for code in ("B.1.1", "B.1.2", "B.1.3", "B.1.4", "A.1.4"):
        (reg / f"{code}.pdf").write_bytes(b"%PDF " + code.encode())
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])

    trovati = identity_reader.find_files_by_names([str(reg)], ["B.1.3"])
    assert [f["name"] for f in trovati] == ["B.1.3.pdf"]

    risolti, mancanti = server._resolve_attachments(2, ["B.1.3", "A.1.4"])
    assert mancanti == []
    assert [f["name"] for f in risolti] == ["B.1.3.pdf", "A.1.4.pdf"]

    # l'estensione vera si toglie ancora
    risolti, _ = server._resolve_attachments(2, ["B.1.3.pdf"])
    assert [f["name"] for f in risolti] == ["B.1.3.pdf"]


def test_nome_ambiguo_non_sceglie_da_solo(tmp_path, monkeypatch):
    """Se un nome resta ambiguo la richiesta si ferma: meglio chiedere che
    allegare la planimetria di un altro appartamento."""
    reg = tmp_path / "schede"
    reg.mkdir()
    (reg / "B.2.1 bilo.pdf").write_bytes(b"%PDF a")
    (reg / "B.2.1 no balcone.pdf").write_bytes(b"%PDF b")
    monkeypatch.setattr(att, "identity_paths", lambda aid: [str(reg)])
    risolti, mancanti = server._resolve_attachments(2, ["B.2.1"])
    assert risolti == []
    assert len(mancanti) == 1 and "ambiguo" in mancanti[0]
