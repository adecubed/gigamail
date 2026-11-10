"""What the agent will not read well in a document, said when it is attached."""
import pytest

from gigamail.core import doc_check, file_extractor


@pytest.fixture(autouse=True)
def fresh():
    doc_check._cache.clear()
    yield
    doc_check._cache.clear()


def _codes(report):
    return [n["code"] for n in report["notes"]]


def test_a_plain_short_document_has_nothing_to_say(tmp_path):
    f = tmp_path / "terms.txt"
    f.write_text("Deposit: ten percent.", encoding="utf-8")
    report = doc_check.check(str(f))
    assert report["name"] == "terms.txt" and report["chars"] == 21
    assert report["notes"] == []


def test_a_document_longer_than_a_prompt_takes_says_so(tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("row\n" * 10000, encoding="utf-8")
    note = doc_check.check(str(f))["notes"][0]
    assert note["code"] == doc_check.TOO_LONG
    assert note["chars"] > note["limit"] == doc_check.PROMPT_DOC_CHARS


def test_a_workbook_with_several_sheets_names_them(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Available"
    wb.active.append(["Code", "Price"])
    old = wb.create_sheet("Old prices")
    old.append(["Code", "Price"])
    f = tmp_path / "list.xlsx"
    wb.save(f)
    notes = doc_check.check(str(f))["notes"]
    assert notes == [{"code": doc_check.SHEETS, "names": ["Available", "Old prices"]}]
    # one sheet is the ordinary case: nothing to say
    wb.remove(old)
    one = tmp_path / "one.xlsx"
    wb.save(one)
    assert doc_check.check(str(one))["notes"] == []


def test_a_document_without_text_or_unreadable_says_which(tmp_path, monkeypatch):
    empty = tmp_path / "plan.txt"
    empty.write_text("  \n", encoding="utf-8")
    assert _codes(doc_check.check(str(empty))) == [doc_check.NO_TEXT]
    assert _codes(doc_check.check(str(tmp_path / "gone.txt"))) == [doc_check.UNREADABLE]
    assert _codes(doc_check.check(str(tmp_path))) == [doc_check.UNREADABLE]   # a folder


def test_a_document_slow_to_read_says_how_long(tmp_path, monkeypatch):
    f = tmp_path / "list.txt"
    f.write_text("Code;Price", encoding="utf-8")
    clock = iter([100.0, 112.5])
    monkeypatch.setattr(doc_check.time, "time", lambda: next(clock))
    assert doc_check.check(str(f))["notes"] == [{"code": doc_check.SLOW, "seconds": 12.5}]


def test_the_document_is_read_again_only_when_it_changes(tmp_path, monkeypatch):
    f = tmp_path / "terms.txt"
    f.write_text("Deposit: ten percent.", encoding="utf-8")
    reads = []
    real = file_extractor.extract_text
    monkeypatch.setattr(file_extractor, "extract_text",
                        lambda p: reads.append(p) or real(p))
    doc_check.check(str(f))
    doc_check.check(str(f))
    assert len(reads) == 1
    f.write_text("Deposit: twenty percent, and more words.", encoding="utf-8")
    assert doc_check.check(str(f))["chars"] == 40
    assert len(reads) == 2


def test_the_route_gives_numbers_and_never_the_content(tmp_path):
    from fastapi.testclient import TestClient

    from gigamail import http_api
    f = tmp_path / "long.txt"
    f.write_text("secret price 123456\n" * 3000, encoding="utf-8")
    with TestClient(http_api.app) as c:
        r = c.post("/documents/check", json={"paths": [str(f), str(tmp_path / "gone.txt")]})
    assert r.status_code == 200
    out = r.json()
    assert [o["name"] for o in out] == ["long.txt", "gone.txt"]
    assert out[0]["notes"][0]["code"] == "too_long"
    assert out[1]["notes"][0]["code"] == "unreadable"
    assert "secret price" not in r.text
