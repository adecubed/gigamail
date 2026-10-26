"""Content search over the registered knowledge files (FTS5 chunks)."""
import json
import os

import pytest

from gigamail import server as srv
from gigamail.core import identity_reader, knowledge_index
from gigamail.watcher import drafting


@pytest.fixture()
def kb(tmp_path):
    d = tmp_path / "knowledge"
    d.mkdir()
    (d / "terms.txt").write_text(
        "Deposit: ten percent when the contract is signed.\n\n"
        "Pets: small dogs and cats are welcome.", encoding="utf-8")
    rows = "".join(f"B.{i}.2;{60 + i};{100000 + i * 1000}\n" for i in range(300))
    (d / "list_2026.csv").write_text(
        "Code;Sqm;Price\n" + rows + "X.4.2;95;210000 terrace\n", encoding="utf-8")
    return d


def test_a_word_only_in_the_content_finds_the_file(kb):
    hits = knowledge_index.search([str(kb)], "Do you accept pets?")
    assert hits and hits[0]["name"] == "terms.txt"
    assert "small dogs" in hits[0]["excerpt"]


@pytest.mark.parametrize("asked", ["X.4.2", "x-4-2", "X42", "x_4_2"])
def test_a_code_matches_whatever_the_separators(kb, asked):
    hits = knowledge_index.search([str(kb)], f"How much is {asked}?")
    assert hits and "210000 terrace" in hits[0]["excerpt"]


def test_every_spreadsheet_chunk_carries_the_header_row(kb):
    hits = knowledge_index.search([str(kb)], "X.4.2")
    assert hits[0]["excerpt"].splitlines()[0] == "Code;Sqm;Price"
    chunks = knowledge_index.chunk_text(
        "[Foglio: Prices]\nCode | Price\n" + "".join(f"X{i} | {i}\n" for i in range(500)))
    assert len(chunks) > 1
    assert all(c.startswith("[Foglio: Prices]\nCode | Price\n") for c in chunks)


def test_a_long_line_is_split_and_nothing_is_lost():
    line = " ".join(f"word{i}" for i in range(400))
    chunks = knowledge_index.chunk_text(line)
    assert len(chunks) > 1
    assert all(len(c) <= knowledge_index.CHUNK_CHARS for c in chunks)
    assert " ".join(chunks).split() == line.split()


def test_a_changed_file_is_indexed_again(kb):
    f = kb / "terms.txt"
    f.write_text("Deposit: twenty percent.", encoding="utf-8")
    os.utime(f, (1_000_000_000, 1_000_000_000))
    hits = knowledge_index.search([str(kb)], "deposit")
    assert hits and "twenty" in hits[0]["excerpt"]
    assert not any("small dogs" in h["excerpt"] for h in
                   knowledge_index.search([str(kb)], "dogs"))


def test_a_deleted_file_is_dropped(kb):
    assert knowledge_index.search([str(kb)], "dogs")
    os.remove(kb / "terms.txt")
    assert knowledge_index.search([str(kb)], "dogs") == []


def test_a_file_no_longer_registered_never_comes_out(kb, tmp_path):
    """The index keeps it, the whitelist of the call does not."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("Nothing here.", encoding="utf-8")
    assert knowledge_index.search([str(kb)], "dogs")
    assert knowledge_index.search([str(other)], "dogs") == []
    assert knowledge_index.search([str(other / "notes.txt")], "dogs") == []


@pytest.mark.parametrize("hostile", [
    '"', '" OR 1', "dogs*", "NEAR(dogs pets)", "dogs OR NOT pets",
    "path:terms", "^dogs", "{text}: dogs", "", "   ", "?!", "AND OR NOT",
])
def test_fts_syntax_in_the_mail_never_breaks_the_query(kb, hostile):
    assert isinstance(knowledge_index.search([str(kb)], hostile), list)


def test_an_unreadable_file_leaves_no_error_text_in_the_index(tmp_path):
    d = tmp_path / "k"
    d.mkdir()
    (d / "sheet_A12.pdf").write_bytes(b"not a pdf")
    assert knowledge_index.search([str(d)], "pdf readable error A12") == []


def test_images_are_not_indexed(tmp_path):
    d = tmp_path / "k"
    d.mkdir()
    (d / "plan_A12.png").write_bytes(b"\x89PNG A12")
    assert knowledge_index.allowed_files([str(d)]) == []


def test_the_tool_searches_only_the_registered_paths(kb, tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("api key: hunter2 dogs", encoding="utf-8")
    monkeypatch.setattr(srv, "_identity_paths", lambda aid=None: [str(kb)])
    out = srv.search_knowledge("dogs hunter2 api key")
    assert out and all(set(h) == {"name", "path", "excerpt", "score"} for h in out)
    assert "hunter2" not in json.dumps(out)
    for h in out:
        assert os.path.commonpath([os.path.abspath(h["path"]), str(kb)]) == str(kb)


def test_the_agent_bar_finds_the_content_when_no_name_matches(kb):
    out = identity_reader.read_relevant_excerpts([str(kb)], "can I bring my cats?")
    assert out.startswith("DATI SPECIFICI DALLA DOCUMENTAZIONE:")
    assert "small dogs and cats" in out


def test_a_short_rule_document_goes_in_whole(kb):
    rule = {"doc_paths": [str(kb / "terms.txt")]}
    assert drafting._rule_docs_text(rule, "pets") == drafting._rule_docs_text(rule)


def test_a_long_rule_document_without_matches_is_cut_as_before(tmp_path):
    doc = tmp_path / "long.txt"
    doc.write_text("".join(f"line {i} garden\n" for i in range(2000)), encoding="utf-8")
    rule = {"doc_paths": [str(doc)]}
    assert (drafting._rule_docs_text(rule, "submarine")
            == drafting._rule_docs_text(rule))
