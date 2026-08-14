"""File di conoscenza: whitelist rigida sui percorsi registrati."""
import os

import pytest

import identity_reader
import file_extractor


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


def test_extract_text_txt(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("Riga uno\nRiga due", encoding="utf-8")
    text, kind = file_extractor.extract_text(str(f), original_filename="doc.txt")
    assert "Riga uno" in text
