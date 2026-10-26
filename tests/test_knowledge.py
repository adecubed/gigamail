"""File di conoscenza: whitelist rigida sui percorsi registrati."""
import os

import pytest

from gigamail.core import file_extractor, identity_reader


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
    for n in ("A.8.1.pdf", "A.6.1.pdf", "A.6.2.pdf", "B.8.1 no balcone.pdf",
              "B.9.1.pdf", "rimanenze commerciali.txt"):
        (d / n).write_bytes(b"x")
    return d


def test_find_relevant_codici_puntati(planimetrie_dir):
    """Il caso reale: 'manda la planimetria A.8.1' deve trovare A.8.1.pdf,
    non B.8.1 (che prima vinceva perche' 'al' matchava dentro 'balcone')."""
    hits = identity_reader.find_relevant_files([str(planimetrie_dir)],
                                               "manda la planimetria A.8.1 al cliente")
    names = [h["name"] for h in hits]
    assert names[0] == "A.8.1.pdf"
    assert "B.8.1 no balcone.pdf" not in names


def test_find_relevant_codici_multipli(planimetrie_dir):
    hits = identity_reader.find_relevant_files([str(planimetrie_dir)],
                                               "invia le schede A.6.1 e A.6.2")
    names = {h["name"] for h in hits}
    assert {"A.6.1.pdf", "A.6.2.pdf"} <= names


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


def test_an_empty_cell_keeps_the_columns_in_place(tmp_path):
    """A row with an empty cell used to lose it, and the price moved
    under the previous column's header."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Prices"
    ws.append(["Code", "Sqm", "Balcony", "Price", None])
    ws.append(["X.4.2", 95, None, 210000, None])
    ws.append([None, None, None, None, None])
    f = tmp_path / "list.xlsx"
    wb.save(f)
    text, kind = file_extractor.extract_text(str(f))
    assert kind == "excel"
    assert text.splitlines() == ["[Foglio: Prices]",
                                 "Code | Sqm | Balcony | Price",
                                 "X.4.2 | 95 |  | 210000"]


def test_an_old_xls_is_read_with_xlrd(tmp_path, monkeypatch):
    """openpyxl does not open .xls. No library here writes one, so the
    workbook xlrd returns is built from xlrd's own cells."""
    xlrd = pytest.importorskip("xlrd")
    from datetime import datetime

    from xlrd.sheet import Cell

    rows = [
        [Cell(xlrd.XL_CELL_TEXT, "Code"), Cell(xlrd.XL_CELL_TEXT, "Balcony"),
         Cell(xlrd.XL_CELL_TEXT, "Price"), Cell(xlrd.XL_CELL_TEXT, "Available")],
        [Cell(xlrd.XL_CELL_TEXT, "Y.2.5"), Cell(xlrd.XL_CELL_EMPTY, ""),
         Cell(xlrd.XL_CELL_NUMBER, 185000.0),
         Cell(xlrd.XL_CELL_DATE, xlrd.xldate.xldate_from_date_tuple((2027, 3, 1), 0))],
        [Cell(xlrd.XL_CELL_BLANK, ""), Cell(xlrd.XL_CELL_EMPTY, "")],
    ]

    class Sheet:
        name = "Old"
        nrows = len(rows)

        def row(self, r):
            return rows[r]

    class Book:
        datemode = 0

        def sheets(self):
            return [Sheet()]

    f = tmp_path / "old_list.xls"
    f.write_bytes(b"\xd0\xcf\x11\xe0")
    monkeypatch.setattr(xlrd, "open_workbook", lambda path: Book())
    text, kind = file_extractor.extract_text(str(f))
    assert kind == "excel"
    assert text.splitlines() == ["[Foglio: Old]",
                                 "Code | Balcony | Price | Available",
                                 f"Y.2.5 |  | 185000 | {datetime(2027, 3, 1)}"]


def test_a_broken_xls_raises_instead_of_returning_text(tmp_path):
    xlrd = pytest.importorskip("xlrd")
    f = tmp_path / "broken.xls"
    f.write_bytes(b"not an excel file")
    with pytest.raises(xlrd.XLRDError):
        file_extractor.extract_text(str(f))
