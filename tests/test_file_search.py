"""The PC file search: roots, exclusions, walk, matching, excerpts, limits.

Every tree is built under tmp_path. On some machines tmp_path itself sits
under AppData, so the autouse fixture `allow_tmp` makes the real exclusion
rule judge a path under tmp_path as if it were /scratch; synthetic paths are
judged as they are.
"""
import ntpath
import os
import posixpath
import threading
import time
import zipfile
from types import SimpleNamespace

import pytest

from gigamail.core import file_search, rule_requests


def make(root, rel, text="", size=None, mtime=None):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size if size is not None else text.encode("utf-8"))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def spy_extractor(monkeypatch):
    """Records every path the extractor is asked to read. The assertion is
    made by the test on the main thread: a failure raised inside the worker
    thread would just kill the thread."""
    opened = []

    def spy(path, name="", **kw):
        opened.append(path)
        return "harmless", "text"
    monkeypatch.setattr(file_search.file_extractor, "extract_text", spy)
    return opened


def names(result):
    return [r["name"] for r in result["results"]]


SCRATCH = os.sep + "scratch"


@pytest.fixture(autouse=True)
def allow_tmp(tmp_path, monkeypatch):
    """The real exclusion rule judges a path under tmp_path as if tmp_path
    were /scratch, so where pytest put tmp_path (under AppData here) does not
    decide the outcome. Paths outside tmp_path (the synthetic ones) are judged
    as they are. Production code knows nothing about this."""
    bases = {os.path.normcase(str(tmp_path)),
             os.path.normcase(os.path.realpath(str(tmp_path)))}
    original = rule_requests.excluded_reason

    def mapped(real):
        norm = os.path.normcase(real)
        for base in bases:
            if norm == base or norm.startswith(base.rstrip(os.sep) + os.sep):
                return original(SCRATCH + real[len(base):])
        return original(real)

    monkeypatch.setattr(rule_requests, "excluded_reason", mapped)

    # Where pytest put tmp_path, a folder above it (AppData on Windows) can be
    # hidden: tmp_path and what is above it are read as plain.
    original_attrs = file_search.read_attributes

    def attrs(path):
        norm = os.path.normcase(path)
        for base in bases:
            if norm == base or base.startswith(norm.rstrip(os.sep) + os.sep):
                return 0
        return original_attrs(path)

    monkeypatch.setattr(file_search, "read_attributes", attrs)
    return str(tmp_path)


# --- clean_query -------------------------------------------------------------

def test_clean_query_lowers_case_and_strips_accents():
    assert file_search.clean_query("  Contratto  AFFITTO Perché ") == [
        "contratto", "affitto", "perche"]


@pytest.mark.parametrize("query", ["", "   ", "a b c d e f g"])
def test_clean_query_refuses_zero_and_seven_words(query):
    with pytest.raises(ValueError, match="word"):
        file_search.clean_query(query)


def test_clean_query_accepts_six_words():
    assert len(file_search.clean_query("aa bb cc dd ee ff")) == 6


def test_clean_query_refuses_a_one_character_word():
    with pytest.raises(ValueError, match="2 characters"):
        file_search.clean_query("invoice a")


def test_clean_query_refuses_more_than_100_characters():
    with pytest.raises(ValueError, match="100"):
        file_search.clean_query("x" * 101)
    assert file_search.clean_query("x" * 100) == ["x" * 100]


@pytest.mark.parametrize("bad", ["\u200b", "\u202e", "\x01", "\u2028"])
def test_clean_query_refuses_invisible_characters(bad):
    with pytest.raises(ValueError, match="character"):
        file_search.clean_query(f"invoice{bad}2026")


# --- default_roots -----------------------------------------------------------

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    return home


def test_default_roots_keeps_the_existing_user_folders(fake_home):
    (fake_home / "Documents").mkdir()
    (fake_home / "Downloads").mkdir()
    roots = file_search.default_roots()
    assert roots == [os.path.realpath(str(fake_home / "Documents")),
                     os.path.realpath(str(fake_home / "Downloads"))]


def test_default_roots_drops_a_root_nested_in_another_and_a_missing_one(
        fake_home, monkeypatch):
    docs = fake_home / "Documents"
    (docs / "OneDriveCopy").mkdir(parents=True)
    (fake_home / "Desktop").mkdir()
    monkeypatch.setenv("OneDrive", str(docs / "OneDriveCopy"))
    monkeypatch.setenv("OneDriveConsumer", str(fake_home / "does-not-exist"))
    monkeypatch.setenv("OneDriveCommercial", str(docs))  # same root twice
    roots = file_search.default_roots()
    assert sorted(roots) == sorted([os.path.realpath(str(docs)),
                                    os.path.realpath(str(fake_home / "Desktop"))])


def test_default_roots_empty_when_nothing_exists(fake_home):
    assert file_search.default_roots() == []


# --- checked_folder ----------------------------------------------------------

def test_checked_folder_returns_the_resolved_path(tmp_path):
    (tmp_path / "work").mkdir()
    assert file_search.checked_folder(str(tmp_path / "work")) == os.path.realpath(
        str(tmp_path / "work"))


HIDDEN_SYSTEM = 0x2 | 0x4


def _reader_hiding(monkeypatch, hidden):
    """Make the attribute reader report hidden+system for the given paths."""
    keys = {os.path.normcase(os.path.realpath(str(p))) for p in hidden}

    def attrs(path):
        return HIDDEN_SYSTEM if os.path.normcase(path) in keys else 0

    monkeypatch.setattr(file_search, "read_attributes", attrs)


def test_checked_folder_refuses_a_folder_whose_ancestor_is_hidden(
        tmp_path, monkeypatch):
    inner = tmp_path / "a" / "b" / "c"
    inner.mkdir(parents=True)
    _reader_hiding(monkeypatch, [tmp_path / "a" / "b"])
    with pytest.raises(ValueError, match="hidden or system folder"):
        file_search.checked_folder(str(inner))
    with pytest.raises(ValueError, match="hidden or system folder"):
        file_search.checked_folder(str(tmp_path / "a" / "b"))
    assert file_search.checked_folder(str(tmp_path / "a")) == os.path.realpath(
        str(tmp_path / "a"))


def test_search_and_default_roots_inherit_the_hidden_folder_check(
        tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    (home / "Desktop").mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    _reader_hiding(monkeypatch, [home / "Documents"])
    assert file_search.default_roots() == [os.path.realpath(str(home / "Desktop"))]
    with pytest.raises(ValueError, match="hidden or system folder"):
        file_search.search(["x1"], [str(home / "Documents")])


def test_checked_folder_accepts_a_normal_folder_when_the_drive_root_is_hidden(
        tmp_path, monkeypatch):
    (tmp_path / "work").mkdir()
    real = os.path.realpath(str(tmp_path / "work"))
    root = os.path.splitdrive(real)[0] + os.sep if os.name == "nt" else os.sep
    keys = {os.path.normcase(root)}
    monkeypatch.setattr(file_search, "read_attributes",
                        lambda p: HIDDEN_SYSTEM if os.path.normcase(p) in keys else 0)
    assert file_search.checked_folder(str(tmp_path / "work")) == real


@pytest.mark.skipif(os.name != "nt", reason="the hidden attribute is a Windows one")
def test_checked_folder_refuses_a_really_hidden_folder_and_its_subfolder(tmp_path):
    import ctypes
    hidden = tmp_path / "secret"
    (hidden / "sub").mkdir(parents=True)
    assert ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2)
    # The autouse fixture reads tmp_path and above as plain; "secret" is below.
    with pytest.raises(ValueError, match="hidden or system folder"):
        file_search.checked_folder(str(hidden))
    with pytest.raises(ValueError, match="hidden or system folder"):
        file_search.checked_folder(str(hidden / "sub"))


def test_checked_folder_refuses_a_relative_path():
    with pytest.raises(ValueError, match="absolute"):
        file_search.checked_folder("work/files")


@pytest.mark.parametrize("raw", ["\\\\server\\share\\x", "//server/share/x"])
def test_checked_folder_refuses_a_network_path_without_touching_the_disk(
        raw, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the disk was touched")
    monkeypatch.setattr(os.path, "realpath", boom)
    monkeypatch.setattr(os.path, "exists", boom)
    monkeypatch.setattr(os.path, "isdir", boom)
    with pytest.raises(ValueError, match="network"):
        file_search.checked_folder(raw)


def test_checked_folder_refuses_a_link_that_resolves_to_the_network(
        tmp_path, monkeypatch):
    real = "\\\\server\\share\\x"
    monkeypatch.setattr(os.path, "realpath", lambda p: real)
    with pytest.raises(ValueError, match="network"):
        file_search.checked_folder(str(tmp_path / "link"))


def test_checked_folder_refuses_a_missing_folder(tmp_path):
    with pytest.raises(ValueError, match="exist"):
        file_search.checked_folder(str(tmp_path / "nope"))


def test_checked_folder_refuses_a_file(tmp_path):
    path = make(tmp_path, "a.txt", "hello")
    with pytest.raises(ValueError, match="folder"):
        file_search.checked_folder(path)


def test_checked_folder_refuses_a_folder_under_a_dot_folder(tmp_path):
    (tmp_path / ".ssh" / "keys").mkdir(parents=True)
    with pytest.raises(ValueError, match="dot"):
        file_search.checked_folder(str(tmp_path / ".ssh" / "keys"))


def test_checked_folder_refuses_appdata(tmp_path):
    (tmp_path / "AppData" / "Local").mkdir(parents=True)
    with pytest.raises(ValueError, match="AppData"):
        file_search.checked_folder(str(tmp_path / "AppData" / "Local"))


def test_checked_folder_refuses_gigamail_data(tmp_path, monkeypatch):
    (tmp_path / "gm").mkdir()
    monkeypatch.setattr(file_search.attachments, "is_gigamail_data",
                        lambda real: os.path.basename(real) == "gm")
    with pytest.raises(ValueError, match="GigaMail"):
        file_search.checked_folder(str(tmp_path / "gm"))


# --- excluded ----------------------------------------------------------------

def test_excluded_judges_the_whole_path():
    path = os.path.abspath(os.path.join(os.sep, "Users", "mario", "AppData", "x.txt"))
    assert "AppData" in file_search.excluded(path, is_dir=False)
    dot = os.path.abspath(os.path.join(os.sep, "data", ".git", "config"))
    assert file_search.excluded(dot, is_dir=False)


@pytest.mark.skipif(os.name != "nt", reason="Windows system folders")
def test_excluded_refuses_the_windows_folders_for_a_high_root(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    for path in (r"C:\Windows\System32\config\SAM",
                 r"C:\Program Files\App\readme.txt"):
        assert file_search.excluded(path, is_dir=False)
    assert file_search.excluded(r"C:\Windows", is_dir=True)
    assert file_search.excluded(r"C:\Users\mario\Documents\a.txt",
                                is_dir=False) == ""


def test_the_system_and_library_rules_hold_in_both_path_shapes():
    # The pure rule, as tests/test_rule_requests.py runs it, for a path under
    # a high root such as C:\ or /.
    nt = (ntpath, [r"C:\Windows", r"C:\Program Files"], r"C:\Users\mario")
    assert rule_requests.folder_reason(r"C:\Windows\System32\config\SAM", *nt)
    assert rule_requests.folder_reason(r"C:\Program Files\App\a.txt", *nt)
    assert rule_requests.folder_reason(r"C:\Users\mario\Documents\a.txt", *nt) == ""
    posix = (posixpath, ["/etc", "/usr", "/var"], "/Users/mario")
    assert rule_requests.folder_reason("/etc/passwd", *posix)
    assert rule_requests.folder_reason("/Users/mario/Library/Keychains/x.keychain", *posix)
    assert rule_requests.folder_reason("/Users/mario/Documents/a.txt", *posix) == ""


def test_the_walk_judges_the_whole_path_not_the_part_below_the_root(
        tmp_path, monkeypatch):
    system = os.path.normcase(os.path.join(SCRATCH, "winlike"))
    monkeypatch.setattr(rule_requests, "_system_dirs", lambda: [system])
    make(tmp_path, "winlike/secret alpha.txt", "alpha")
    make(tmp_path, "fine/alpha.txt", "alpha")
    assert names(file_search.search(["alpha"], [str(tmp_path)])) == ["alpha.txt"]
    with pytest.raises(ValueError, match="system folder"):
        file_search.checked_folder(str(tmp_path / "winlike"))


def test_a_whole_drive_or_filesystem_root_is_refused():
    with pytest.raises(ValueError, match="root"):
        file_search.checked_folder(os.path.abspath(os.sep))


def test_excluded_refuses_programs_and_network_paths():
    root = os.path.abspath(os.path.join(os.sep, "data"))
    assert file_search.excluded(os.path.join(root, "setup.EXE"), is_dir=False)
    assert file_search.excluded("//server/share/a.txt", is_dir=False)
    # a folder named like a program is a folder
    assert file_search.excluded(os.path.join(root, "tools.exe"), is_dir=True) == ""


def test_excluded_refuses_gigamail_data(tmp_path, monkeypatch):
    monkeypatch.setattr(file_search.attachments, "is_gigamail_data",
                        lambda real: "gm" in real)
    assert file_search.excluded(str(tmp_path / "gm" / "x.db"), is_dir=False)


@pytest.mark.parametrize("attrs", [0x2, 0x4, 0x6])
def test_excluded_refuses_hidden_and_system_attributes(tmp_path, monkeypatch, attrs):
    path = make(tmp_path, "plain.txt", "hello")
    real_stat = os.stat

    def fake(p, *a, **k):
        st = real_stat(p, *a, **k)
        return SimpleNamespace(st_file_attributes=attrs, st_mode=st.st_mode)
    monkeypatch.setattr(file_search.os, "stat", fake)
    assert file_search.excluded(path, is_dir=False)


@pytest.mark.skipif(os.name != "nt", reason="Windows file attributes")
def test_a_hidden_file_and_a_hidden_folder_are_not_searched(tmp_path):
    import ctypes
    make(tmp_path, "shown/report alpha.txt")
    hidden_file = make(tmp_path, "shown/hidden alpha.txt")
    hidden_dir = os.path.dirname(make(tmp_path, "secret/inside alpha.txt"))
    for p in (hidden_file, hidden_dir):
        assert ctypes.windll.kernel32.SetFileAttributesW(p, 0x2)
    found = file_search.search(["alpha"], [str(tmp_path)])
    assert names(found) == ["report alpha.txt"]


# --- is_online_only ----------------------------------------------------------

@pytest.mark.parametrize("attrs,expected", [(0x400000, True), (0x40000, True),
                                            (0x1000, True), (0x20, False), (0x2, False)])
def test_is_online_only_reads_the_windows_attributes(tmp_path, monkeypatch, attrs,
                                                     expected):
    path = make(tmp_path, "a.txt", "x")
    monkeypatch.setattr(file_search.os, "stat",
                        lambda p, *a, **k: SimpleNamespace(st_file_attributes=attrs))
    assert file_search.is_online_only(path) is expected


def test_is_online_only_is_false_without_attributes_or_on_error(tmp_path, monkeypatch):
    path = make(tmp_path, "a.txt", "x")
    monkeypatch.setattr(file_search.os, "stat", lambda p, *a, **k: SimpleNamespace())
    assert file_search.is_online_only(path) is False

    def boom(*a, **k):
        raise OSError("gone")
    monkeypatch.setattr(file_search.os, "stat", boom)
    assert file_search.is_online_only(path) is False


# --- search: matching --------------------------------------------------------

def test_name_match_needs_every_word_ignoring_case_and_accents(tmp_path):
    make(tmp_path, "Contratto Affitto Perché.pdf", "")
    make(tmp_path, "contratto lavoro.pdf", "")
    found = file_search.search(file_search.clean_query("AFFITTO perche contratto"),
                               [str(tmp_path)])
    assert names(found) == ["Contratto Affitto Perché.pdf"]
    assert found["results"][0]["match"] == "name"
    assert found["stopped_by"] == []


def test_result_fields(tmp_path):
    path = make(tmp_path, "sub/budget notes.txt", "numbers", mtime=1_700_000_000)
    found = file_search.search(["budget"], [str(tmp_path)])
    (hit,) = found["results"]
    assert hit["path"] == path
    assert hit["size"] == len("numbers")
    assert hit["modified"].startswith("2023-11-1")  # local time, ISO
    assert hit["online_only"] is False
    assert found["visited"] >= 2


def test_content_match_in_txt_and_csv(tmp_path):
    make(tmp_path, "notes.txt", "Please call Mario about the lease renewal")
    make(tmp_path, "table.csv", "id,topic\n1,lease renewal\n")
    make(tmp_path, "other.txt", "nothing relevant")
    found = file_search.search(["lease", "renewal"], [str(tmp_path)])
    assert sorted(names(found)) == ["notes.txt", "table.csv"]
    assert {r["match"] for r in found["results"]} == {"content"}


def test_a_file_without_a_known_extension_is_not_read_as_text(tmp_path):
    make(tmp_path, "blob.bin", "secret lease inside")
    found = file_search.search(["lease"], [str(tmp_path)])
    assert found["results"] == []
    named = make(tmp_path, "lease.bin", "x")
    assert file_search.search(["lease"], [str(tmp_path)])["results"][0]["path"] == named


def test_name_matches_come_first_then_newest_first(tmp_path):
    make(tmp_path, "old-name tax.txt", "", mtime=1_000_000_000)
    make(tmp_path, "new-name tax.txt", "", mtime=1_600_000_000)
    make(tmp_path, "old-body.txt", "tax", mtime=1_500_000_000)
    make(tmp_path, "newest-body.txt", "tax", mtime=1_700_000_000)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert names(found) == ["new-name tax.txt", "old-name tax.txt",
                            "newest-body.txt", "old-body.txt"]


def test_an_unreadable_file_is_not_a_match_and_does_not_stop_the_search(
        tmp_path, monkeypatch):
    make(tmp_path, "broken.txt", "tax")
    make(tmp_path, "fine.txt", "tax")

    def extract(path, name="", **kw):
        if path.endswith("broken.txt"):
            raise RuntimeError("corrupt")
        return "tax", "text"
    monkeypatch.setattr(file_search.file_extractor, "extract_text", extract)
    assert names(file_search.search(["tax"], [str(tmp_path)])) == ["fine.txt"]


# --- search: what is never searched -----------------------------------------

def test_dot_folders_appdata_dot_files_and_programs_are_not_searched(tmp_path):
    make(tmp_path, ".git/config alpha.txt", "alpha")
    make(tmp_path, "AppData/Local/alpha.txt", "alpha")
    make(tmp_path, ".hidden alpha.txt", "alpha")
    make(tmp_path, "alpha installer.exe", "alpha")
    make(tmp_path, "ok/alpha.txt", "alpha")
    found = file_search.search(["alpha"], [str(tmp_path)])
    assert names(found) == ["alpha.txt"]


def test_a_symlinked_folder_is_not_followed(tmp_path):
    outside = tmp_path / "outside"
    make(outside, "target alpha.txt", "alpha")
    root = tmp_path / "root"
    root.mkdir()
    try:
        os.symlink(str(outside), str(root / "link"), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this OS refuses symlinks")
    make(root, "plain alpha.txt", "alpha")
    found = file_search.search(["alpha"], [str(root)])
    assert names(found) == ["plain alpha.txt"]


def test_a_symlinked_file_is_not_followed(tmp_path):
    target = make(tmp_path, "outside/alpha.txt", "alpha")
    root = tmp_path / "root"
    root.mkdir()
    try:
        os.symlink(target, str(root / "alpha link.txt"))
    except (OSError, NotImplementedError):
        pytest.skip("this OS refuses symlinks")
    assert file_search.search(["alpha"], [str(root)])["results"] == []


# --- search: limits ----------------------------------------------------------

def test_max_results_stops_the_search_and_is_named(tmp_path, monkeypatch):
    for i in range(8):
        make(tmp_path, f"report {i}.txt", "")
    monkeypatch.setattr(file_search, "MAX_RESULTS", 3)
    found = file_search.search(["report"], [str(tmp_path)])
    assert len(found["results"]) == 3
    assert found["stopped_by"] == ["results"]


def test_a_one_word_query_never_returns_more_than_20_results(tmp_path):
    for i in range(30):
        make(tmp_path, f"aa file {i}.txt", "")
    found = file_search.search(["aa"], [str(tmp_path)])
    assert len(found["results"]) == file_search.MAX_RESULTS == 20
    assert "results" in found["stopped_by"]


def test_max_entries_stops_the_search_and_is_named(tmp_path, monkeypatch):
    for i in range(10):
        make(tmp_path, f"f{i}.txt", "")
    monkeypatch.setattr(file_search, "MAX_ENTRIES", 4)
    found = file_search.search(["zzzz"], [str(tmp_path)])
    assert found["stopped_by"] == ["entries"]
    assert found["visited"] == 4


def test_the_time_limit_stops_the_search_and_is_named(tmp_path):
    for i in range(10):
        make(tmp_path, f"report {i}.txt", "")
    ticks = iter(range(0, 10_000, 6))
    found = file_search.search(["report"], [str(tmp_path)], clock=lambda: next(ticks))
    assert found["stopped_by"] == ["time"]
    assert len(found["results"]) < 10


def test_max_content_files_limits_the_files_opened(tmp_path, monkeypatch):
    for i in range(6):
        make(tmp_path, f"n{i}.txt", "tax")
    opened = []
    real = file_search.file_extractor.extract_text

    def spy(path, name="", **kw):
        opened.append(path)
        return real(path, name, **kw)
    monkeypatch.setattr(file_search.file_extractor, "extract_text", spy)
    monkeypatch.setattr(file_search, "MAX_CONTENT_FILES", 2)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert len(opened) == 2
    assert len(found["results"]) == 2
    assert "content_files" in found["stopped_by"]


def test_a_file_over_the_size_limit_is_found_by_name_only(tmp_path, monkeypatch):
    make(tmp_path, "big.txt", size=200)
    make(tmp_path, "tax big.txt", size=200)
    monkeypatch.setattr(file_search, "MAX_CONTENT_BYTES", 100)
    opened = spy_extractor(monkeypatch)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert opened == []
    assert names(found) == ["tax big.txt"]
    assert found["results"][0]["match"] == "name"
    assert found["stopped_by"] == []


def test_an_online_only_file_is_name_only_and_never_opened(tmp_path, monkeypatch):
    make(tmp_path, "cloud tax.txt", "tax")
    make(tmp_path, "cloud notes.txt", "tax")
    monkeypatch.setattr(file_search, "is_online_only", lambda p, attrs=None: True)
    opened = spy_extractor(monkeypatch)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert opened == []
    assert names(found) == ["cloud tax.txt"]
    assert found["results"][0]["online_only"] is True


# --- excerpt -----------------------------------------------------------------

def test_excerpt_is_one_line_short_and_holds_the_word(tmp_path):
    text = ("intro line\n" * 80 + "the Lease renewal is due\n\n  next\tmonth\n"
            + "outro line\n" * 80)
    path = make(tmp_path, "notes.txt", text)
    out = file_search.excerpt(path, ["lease"])
    assert "\n" not in out and "\t" not in out
    assert len(out) <= file_search.EXCERPT_CHARS
    assert "lease" in out.lower()


def test_excerpt_matches_accented_text(tmp_path):
    path = make(tmp_path, "notes.txt", "Una caffè Perché buona")
    assert "Perché" in file_search.excerpt(path, ["perche"])


def test_excerpt_is_empty_when_nothing_to_show(tmp_path, monkeypatch):
    path = make(tmp_path, "notes.txt", "nothing here")
    assert file_search.excerpt(path, ["tax"]) == ""
    blob = make(tmp_path, "blob.bin", "tax")
    assert file_search.excerpt(blob, ["tax"]) == ""
    big = make(tmp_path, "big.txt", "tax" * 10)
    monkeypatch.setattr(file_search, "MAX_CONTENT_BYTES", 5)
    assert file_search.excerpt(big, ["tax"]) == ""
    monkeypatch.setattr(file_search, "MAX_CONTENT_BYTES", 5 * 1024 * 1024)
    monkeypatch.setattr(file_search, "is_online_only", lambda p, attrs=None: True)
    assert file_search.excerpt(path, ["nothing"]) == ""


def test_excerpt_of_a_missing_file_is_empty(tmp_path):
    assert file_search.excerpt(str(tmp_path / "gone.txt"), ["tax"]) == ""


# --- same_file ---------------------------------------------------------------

def test_same_file_ignores_dot_dot(tmp_path):
    path = make(tmp_path, "a/b.txt", "x")
    other = os.path.join(str(tmp_path), "a", "..", "a", "b.txt")
    assert file_search.same_file(path, other)
    assert not file_search.same_file(path, make(tmp_path, "a/c.txt", "x"))


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths")
def test_same_file_ignores_case_and_slashes_on_windows(tmp_path):
    path = make(tmp_path, "a/b.txt", "x")
    assert file_search.same_file(path, path.upper().replace("\\", "/"))


def test_constants_are_the_planned_ones():
    assert (file_search.MAX_RESULTS, file_search.MAX_SECONDS, file_search.MAX_ENTRIES,
            file_search.MAX_CONTENT_FILES, file_search.MAX_CONTENT_BYTES,
            file_search.EXCERPT_CHARS) == (20, 15, 20000, 300, 5 * 1024 * 1024, 240)
    assert file_search.CONTENT_EXTENSIONS == (
        ".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv")


def test_search_is_fast_on_a_small_tree(tmp_path):
    for i in range(50):
        make(tmp_path, f"d{i % 5}/f{i}.txt", "hello")
    start = time.monotonic()
    file_search.search(["hello"], [str(tmp_path)])
    assert time.monotonic() - start < 5


# --- bounds on one extraction ------------------------------------------------

def make_zip(root, rel, declared_mb):
    path = os.path.join(str(root), rel)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * (declared_mb * 1024 * 1024))
    return path


def test_a_zip_declaring_more_than_20_mb_is_skipped_without_extraction(
        tmp_path, monkeypatch):
    make_zip(tmp_path, "huge.docx", 21)
    make(tmp_path, "garbage.xlsx", "this is not a zip")
    opened = spy_extractor(monkeypatch)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert found["results"] == []
    assert file_search.excerpt(str(tmp_path / "huge.docx"), ["tax"]) == ""
    assert opened == []


def test_a_zip_within_the_limit_is_extracted(tmp_path, monkeypatch):
    make_zip(tmp_path, "small.docx", 1)
    monkeypatch.setattr(file_search.file_extractor, "extract_text",
                        lambda *a, **k: ("the tax paper", "word"))
    assert names(file_search.search(["tax"], [str(tmp_path)])) == ["small.docx"]


def test_a_pdf_is_read_with_the_page_cap(tmp_path, monkeypatch):
    make(tmp_path, "a.pdf", "x")
    seen = {}

    def spy(path, name="", **kw):
        seen.update(kw)
        return "tax", "pdf"
    monkeypatch.setattr(file_search.file_extractor, "extract_text", spy)
    file_search.search(["tax"], [str(tmp_path)])
    assert seen == {"max_pdf_pages": 50}
    assert file_search.MAX_PDF_PAGES == 50


def test_the_extractor_caps_pdf_pages(tmp_path, monkeypatch):
    class Page:
        def __init__(self, n):
            self.n = n

        def extract_text(self):
            return f"page {self.n}"

    class Pdf:
        pages = [Page(i) for i in range(10)]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    import sys
    import types
    fake = types.SimpleNamespace(open=lambda path: Pdf())
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)
    from gigamail.core import file_extractor
    assert file_extractor.extract_text("a.pdf", max_pdf_pages=3)[0] == (
        "page 0\npage 1\npage 2")
    assert file_extractor.extract_text("a.pdf")[0].endswith("page 9")


def test_a_word_after_the_scanned_characters_is_not_a_match(tmp_path):
    assert file_search.MAX_SCANNED_CHARS == 200000
    make(tmp_path, "late.txt", "a " * 100_005 + "needle")
    make(tmp_path, "early.txt", "needle " + "a " * 100_005)
    found = file_search.search(["needle"], [str(tmp_path)])
    assert names(found) == ["early.txt"]
    assert file_search.excerpt(str(tmp_path / "late.txt"), ["needle"]) == ""


def test_an_extraction_that_overruns_the_deadline_ends_the_search_with_time(
        tmp_path, monkeypatch):
    make(tmp_path, "slow.txt", "tax")
    release = threading.Event()
    monkeypatch.setattr(file_search.file_extractor, "extract_text",
                        lambda *a, **k: (release.wait(30), ("tax", "text"))[1])
    monkeypatch.setattr(file_search, "MAX_SECONDS", 1)
    try:
        found = file_search.search(["tax"], [str(tmp_path)], clock=lambda: 0.0)
    finally:
        release.set()
    assert found["results"] == []
    assert "time" in found["stopped_by"]


def test_text_is_folded_on_the_whole_string():
    assert file_search._fold("Perché CAFFÉ Straße") == "perche caffe strasse"


# --- name matches hold across the whole walk ---------------------------------

def test_a_name_match_in_a_later_folder_beats_content_matches_found_first(tmp_path):
    for i in range(20):
        make(tmp_path, f"a_first/body{i}.txt", "tax", mtime=1_700_000_000 + i)
    make(tmp_path, "z_later/tax return.pdf", "", mtime=1_000_000_000)
    for _ in range(2):
        found = file_search.search(["tax"], [str(tmp_path)])
        assert found["results"][0]["name"] == "tax return.pdf"
        assert found["results"][0]["match"] == "name"
        assert len(found["results"]) == 20
        assert "results" in found["stopped_by"]


def test_more_than_20_name_matches_keep_the_20_newest(tmp_path):
    for i in range(25):
        make(tmp_path, f"tax{i}.txt", "", mtime=1_600_000_000 + i)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert names(found) == [f"tax{i}.txt" for i in range(24, 4, -1)]
    assert "results" in found["stopped_by"]


def test_content_fills_only_the_slots_left_newest_first(tmp_path):
    make(tmp_path, "tax name.txt", "", mtime=1_000_000_000)
    make(tmp_path, "old.txt", "tax", mtime=1_100_000_000)
    make(tmp_path, "new.txt", "tax", mtime=1_700_000_000)
    found = file_search.search(["tax"], [str(tmp_path)])
    assert names(found) == ["tax name.txt", "new.txt", "old.txt"]


# --- every root is judged ----------------------------------------------------

def test_default_roots_drops_a_root_the_check_refuses(fake_home, monkeypatch):
    (fake_home / "Documents").mkdir()
    (fake_home / "AppData" / "Local" / "OneDrive").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(fake_home / "AppData" / "Local" / "OneDrive"))
    system = os.path.normcase(os.path.join(SCRATCH, "home", "Downloads"))
    (fake_home / "Downloads").mkdir()
    monkeypatch.setattr(rule_requests, "_system_dirs", lambda: [system])
    assert file_search.default_roots() == [os.path.realpath(str(fake_home / "Documents"))]


def test_search_refuses_a_root_that_the_check_refuses(tmp_path):
    (tmp_path / "AppData").mkdir()
    with pytest.raises(ValueError, match="AppData"):
        file_search.search(["tax"], [str(tmp_path / "AppData")])
    with pytest.raises(ValueError, match="network"):
        file_search.search(["tax"], ["//server/share"])


# --- minor rules -------------------------------------------------------------

def test_a_doc_is_found_by_name_only(tmp_path, monkeypatch):
    make(tmp_path, "old letter.doc", "tax")
    make(tmp_path, "tax letter.doc", "")
    opened = spy_extractor(monkeypatch)
    assert ".doc" not in file_search.CONTENT_EXTENSIONS
    assert names(file_search.search(["tax"], [str(tmp_path)])) == ["tax letter.doc"]
    assert file_search.excerpt(str(tmp_path / "old letter.doc"), ["tax"]) == ""
    assert opened == []


@pytest.mark.skipif(not hasattr(__import__("_winapi") if os.name == "nt" else os,
                                "CreateJunction"), reason="Windows junctions")
def test_a_junction_is_not_followed(tmp_path):
    import _winapi
    outside = tmp_path / "outside"
    make(outside, "target alpha.txt", "alpha")
    root = tmp_path / "root"
    root.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "junction"))
    make(root, "plain alpha.txt", "alpha")
    assert names(file_search.search(["alpha"], [str(root)])) == ["plain alpha.txt"]


@pytest.mark.skipif(os.name != "nt", reason="Windows file attributes")
def test_an_online_only_folder_is_not_entered_and_is_named(tmp_path):
    import ctypes
    make(tmp_path, "cloud/inside alpha.txt", "alpha")
    make(tmp_path, "plain alpha.txt", "alpha")
    assert ctypes.windll.kernel32.SetFileAttributesW(str(tmp_path / "cloud"), 0x1000)
    found = file_search.search(["alpha"], [str(tmp_path)])
    assert names(found) == ["plain alpha.txt"]
    assert "online_only_folders" in found["stopped_by"]
