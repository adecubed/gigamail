"""File di conoscenza: whitelist rigida sui percorsi registrati."""
import os

import pytest

from ade_mail_agent.core import file_extractor, identity_reader


@pytest.fixture()
def knowledge_dir(tmp_path):
    d = tmp_path / "conoscenza"
    d.mkdir()
    (d / "listino_prezzi.txt").write_text("Consulenza: 100 EUR/ora", encoding="utf-8")
    (d / "condizioni.txt").write_text("Pagamento a 30 giorni", encoding="utf-8")
    # file fuori whitelist, nella cartella PADRE
    (tmp_path / "segreto.txt").write_text("NON deve essere leggibile", encoding="utf-8")
    return d


def test_list_all_files_solo_dai_percorsi_registrati(knowledge_dir, tmp_path):
    files = identity_reader.list_all_files([str(knowledge_dir)])
    names = {f["name"] for f in files}
    assert names == {"listino_prezzi.txt", "condizioni.txt"}
    assert "segreto.txt" not in names


def test_find_by_names_match_parziale(knowledge_dir):
    hits = identity_reader.find_files_by_names([str(knowledge_dir)], ["listino"])
    assert len(hits) == 1
    assert hits[0]["name"] == "listino_prezzi.txt"


def test_traversal_nel_nome_non_esce_dalla_whitelist(knowledge_dir):
    """Un nome ostile con '..' non deve raggiungere file fuori dai percorsi
    registrati: il match avviene SOLO contro la lista dei file whitelistati."""
    for hostile in ("../segreto", "..\\segreto", "segreto",
                    "../../segreto.txt", "c:/windows/win.ini"):
        hits = identity_reader.find_files_by_names([str(knowledge_dir)], [hostile])
        for h in hits:
            # qualunque match deve restare dentro la cartella registrata
            assert os.path.commonpath(
                [os.path.abspath(h["path"]), str(knowledge_dir)]
            ) == str(knowledge_dir)


def test_percorso_registrato_inesistente_ignorato(tmp_path):
    assert identity_reader.list_all_files([str(tmp_path / "non-esiste")]) == []


def test_file_singolo_registrato(tmp_path):
    f = tmp_path / "singolo.txt"
    f.write_text("contenuto", encoding="utf-8")
    files = identity_reader.list_all_files([str(f)])
    assert len(files) == 1 and files[0]["name"] == "singolo.txt"


@pytest.fixture()
def planimetrie_dir(tmp_path):
    d = tmp_path / "schede"
    d.mkdir()
    for n in ("A.2.1.pdf", "A.0.1.pdf", "A.0.2.pdf", "B.2.1 no balcone.pdf",
              "B.3.1.pdf", "rimanenze commerciali.txt"):
        (d / n).write_bytes(b"x")
    return d


def test_find_relevant_codici_puntati(planimetrie_dir):
    """Il caso reale: 'manda la planimetria A.2.1' deve trovare A.2.1.pdf,
    non B.2.1 (che prima vinceva perche' 'al' matchava dentro 'balcone')."""
    hits = identity_reader.find_relevant_files([str(planimetrie_dir)],
                                               "manda la planimetria A.2.1 al cliente")
    names = [h["name"] for h in hits]
    assert names[0] == "A.2.1.pdf"
    assert "B.2.1 no balcone.pdf" not in names


def test_find_relevant_codici_multipli(planimetrie_dir):
    hits = identity_reader.find_relevant_files([str(planimetrie_dir)],
                                               "invia le schede A.0.1 e A.0.2")
    names = {h["name"] for h in hits}
    assert {"A.0.1.pdf", "A.0.2.pdf"} <= names


def test_find_relevant_parole_intere(planimetrie_dir):
    hits = identity_reader.find_relevant_files([str(planimetrie_dir)],
                                               "mandami il file delle rimanenze")
    assert [h["name"] for h in hits] == ["rimanenze commerciali.txt"]


def test_find_relevant_query_generica_zero_rumore(planimetrie_dir):
    assert identity_reader.find_relevant_files([str(planimetrie_dir)],
                                               "ciao come stai") == []


def test_extract_text_txt(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("Riga uno\nRiga due", encoding="utf-8")
    text, kind = file_extractor.extract_text(str(f), original_filename="doc.txt")
    assert "Riga uno" in text
