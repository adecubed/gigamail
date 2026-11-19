"""The agent's PC file search (approved at the PC) and read_file.

Every tree is built under tmp_path; the default roots are patched to it,
so the real Documents, Desktop, Downloads and OneDrive are never walked.
On some machines tmp_path sits under AppData, so the fixture mirrors
`tests/test_file_search.py`'s `allow_tmp`: the real exclusion rule judges a
path under tmp_path as if it were /scratch. Production code knows nothing
about it.
"""
import asyncio
import json
import os
import threading
import time
from types import SimpleNamespace

import pytest

from gigamail import policy, server, tools_files
from gigamail.core import attachment_mask, file_search, rule_requests

SCRATCH = os.sep + "scratch"
MARKER = "MARKER-5c1e-file-text"
EMAIL = "mario.rossi@example.com"


def make(root, rel, text="", mtime=None):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """An approvals store in tmp_path, a tree under tmp_path as the only
    default root, the exclusion rule mapped as in test_file_search, the
    mask settings in memory and account 1 active."""
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

    # Where pytest put tmp_path, a folder above it can be hidden (AppData on
    # the CI's Windows runners): tmp_path and what is above it read as plain.
    original_attrs = file_search.read_attributes

    def attrs(path):
        norm = os.path.normcase(path)
        for base in bases:
            if norm == base or base.startswith(norm.rstrip(os.sep) + os.sep):
                return 0
        return original_attrs(path)

    monkeypatch.setattr(file_search, "read_attributes", attrs)

    tree = tmp_path / "docs"
    tree.mkdir()
    monkeypatch.setattr(file_search, "_candidate_roots", lambda: [str(tree)])

    settings = {}
    monkeypatch.setattr(attachment_mask.accounts, "get_setting",
                        lambda key, default="": settings.get(key, default))
    monkeypatch.setattr(attachment_mask.accounts, "set_setting",
                        lambda key, value: settings.__setitem__(key, str(value)))
    monkeypatch.setattr(attachment_mask.ade_masker, "get_user_masks", lambda aid: [])
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: {"id": 1})
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    # Abandoned extraction workers are counted per process: each test
    # starts from none.
    monkeypatch.setattr(tools_files, "_abandoned", [])

    approvals = policy.ApprovalStore(tmp_path / "approvals.db")
    policy.set_store(approvals)
    yield SimpleNamespace(tmp=tmp_path, tree=tree, root=os.path.realpath(str(tree)),
                          approvals=approvals)
    policy.set_store(None)


def _fill(world):
    """Two name matches, one content match, one file that does not match."""
    found = {
        "name_new": make(world.tree, "Invoice 2026 March.txt", "nothing here",
                         mtime=1_800_000_000),
        "name_old": make(world.tree, "old/invoice 2026.bin", "binary", mtime=1_700_000_000),
        "content": make(world.tree, "notes/letter.txt",
                        f"Dear client,\nthe invoice for 2026 is attached. {MARKER}\nBye"),
    }
    make(world.tree, "notes/other.txt", "nothing to see")
    return found


def _ask(query="invoice 2026", **kw):
    return tools_files.search_files(query=query, **kw)


def _approve(world, rid, complete=True):
    assert world.approvals.approve(rid, by="console:mario (console click)") is True
    if complete:
        server.execute_approved(rid)


def _searched(world, query="invoice 2026"):
    out = _ask(query)
    rid = out["request_id"]
    _approve(world, rid)
    return rid, tools_files.search_files(request_id=rid)


def _audit_text(since=0):
    """The audit log written after `since` characters (the log is shared by
    the whole test session)."""
    try:
        return policy._audit_path().read_text(encoding="utf-8")[since:]
    except FileNotFoundError:
        return ""


# --- the request -------------------------------------------------------------

def test_the_first_call_asks_for_approval_and_touches_no_folder(world, monkeypatch):
    _fill(world)

    calls = []

    def spy(name):
        # Recorded, not failed here: a call from a worker thread could not
        # fail the test.
        return lambda *a, **kw: calls.append(name)
    monkeypatch.setattr(os, "scandir", spy("scandir"))
    monkeypatch.setattr(os, "listdir", spy("listdir"))
    monkeypatch.setattr(file_search, "search", spy("search"))
    monkeypatch.setattr(file_search, "excerpt", spy("excerpt"))
    monkeypatch.setattr(file_search.file_extractor, "extract_text", spy("extract_text"))
    out = _ask("Invoice  2026")
    assert calls == []
    assert out["status"] == "approval_required"
    rec = world.approvals.get(out["request_id"])
    assert rec["tool"] == "search_files"
    assert rec["args"] == {"query": "invoice 2026", "roots": [world.root]}


def test_the_preview_names_the_words_and_the_folders(world):
    p = _ask("Invoice 2026")["preview"]
    assert p["action"] == "file_search"
    assert p["subject"] == "Search the PC's files: «invoice 2026»"
    lines = p["body"].splitlines()
    assert any(world.root in line for line in lines)
    assert any("AppData" in line for line in lines)
    assert ("The agent will be able to read the text of at most 20 files found, "
            "for 15 minutes.") in lines
    assert lines[-1] == "No search starts until you approve."


def test_the_preview_is_in_italian_for_an_italian_user(world, monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    p = _ask("fattura")["preview"]
    assert p["subject"] == "Cerca nei file del PC: «fattura»"
    lines = p["body"].splitlines()
    assert ("L'agente potrà leggere il testo di al massimo 20 file trovati, "
            "per 15 minuti.") in lines
    assert lines[-1] == "Non parte nessuna ricerca finché non approvi."


def test_a_named_folder_is_searched_instead_of_the_defaults(world):
    sub = world.tree / "clients"
    sub.mkdir()
    out = _ask(folder=str(sub))
    assert world.approvals.get(out["request_id"])["args"]["roots"] == [
        os.path.realpath(str(sub))]


@pytest.mark.parametrize("folder", ["docs/.private", "docs/AppData", "relative/path",
                                    r"\\server\share\docs"])
def test_an_excluded_folder_is_refused_at_request_time(world, folder):
    if not folder.startswith("\\") and folder != "relative/path":
        target = world.tmp / folder
        target.mkdir(parents=True)
        folder = str(target)
    with pytest.raises(ValueError):
        _ask(folder=folder)
    assert world.approvals.list_pending() == []


def test_a_network_folder_is_refused_before_the_disk_is_touched(world, monkeypatch):
    monkeypatch.setattr(os.path, "realpath",
                        lambda *a, **kw: pytest.fail("the disk was touched"))
    with pytest.raises(ValueError, match="network"):
        _ask(folder=r"\\server\share\docs")


def test_no_default_folder_means_no_request(world, monkeypatch):
    monkeypatch.setattr(file_search, "_candidate_roots", lambda: [])
    with pytest.raises(ValueError, match="folder"):
        _ask()
    assert world.approvals.list_pending() == []


def test_a_bad_query_is_refused(world):
    with pytest.raises(ValueError, match="2 characters"):
        _ask("a")


# --- after the approval ------------------------------------------------------

def test_after_approval_the_agent_gets_the_results_with_excerpts(world):
    found = _fill(world)
    rid, out = _searched(world)
    assert out["status"] == "ok" and out["request_id"] == rid
    assert out["query"] == "invoice 2026" and out["searched"] == [world.root]
    by_path = {r["path"]: r for r in out["results"]}
    assert set(by_path) == set(found.values())
    assert [r["match"] for r in out["results"]] == ["name", "name", "content"]
    content = by_path[found["content"]]
    assert "invoice for 2026" in content["excerpt"]
    assert by_path[found["name_new"]]["excerpt"] == ""
    assert content["size"] > 0 and content["modified"]
    assert out["read_until"]
    assert "untrusted" in out["note"] and "read_file" in out["note"]


def test_calling_again_gives_the_same_results_not_already_executed(world):
    _fill(world)
    rid, first = _searched(world)
    again = tools_files.search_files(query="ignored", request_id=rid)
    assert again["status"] == "ok"
    assert again["results"] == first["results"]


def test_approved_but_not_completed_runs_the_search_on_the_second_call(world):
    found = _fill(world)
    rid = _ask()["request_id"]
    _approve(world, rid, complete=False)
    out = tools_files.search_files(request_id=rid)
    assert out["status"] == "ok"
    assert {r["path"] for r in out["results"]} == set(found.values())
    assert world.approvals.get(rid)["execution_outcome"] == "ok"


def test_the_stored_result_holds_paths_and_no_text(world):
    found = _fill(world)
    rid, _ = _searched(world)
    pr = world.approvals.get(rid)["provider_result"]
    assert set(pr) == {"paths", "matches", "online_only", "ids", "stopped_by", "searched_at",
                       "roots"}
    assert set(pr["paths"]) == set(found.values())
    assert pr["matches"][found["content"]] == "content"
    assert MARKER not in json.dumps(pr) and "attached" not in json.dumps(pr)


def test_a_pending_or_rejected_request_returns_what_it_returned_before(world):
    rid = _ask()["request_id"]
    assert tools_files.search_files(request_id=rid)["status"] == \
        "awaiting_approval"
    world.approvals.reject(rid, by="console:mario")
    assert tools_files.search_files(request_id=rid)["status"] == "rejected"


def test_a_root_gone_before_the_approval_is_dropped(world):
    _fill(world)
    extra = world.tmp / "extra"
    extra.mkdir()
    args = {"query": "invoice 2026", "roots": [world.root, str(extra)]}
    extra.rmdir()
    out = tools_files._exec_search_files(args)
    assert out["provider_result"]["roots"] == [world.root]


def test_no_root_left_fails_the_search(world):
    extra = world.tmp / "extra"
    extra.mkdir()
    args = {"query": "invoice 2026", "roots": [str(extra)]}
    extra.rmdir()
    with pytest.raises(ValueError, match="folder"):
        tools_files._exec_search_files(args)


def test_after_the_window_the_search_lists_nothing(world, monkeypatch):
    _fill(world)
    rid, out = _searched(world)
    later = world.approvals.get(rid)["provider_result"]["searched_at"] + 901
    monkeypatch.setattr(tools_files, "_now", lambda: later)
    closed = tools_files.search_files(request_id=rid)
    assert closed["results"] == []
    assert "closed" in closed["note"]


def test_a_dry_run_returns_what_execute_dangerous_returns(world, monkeypatch):
    rid = _ask()["request_id"]
    _approve(world, rid, complete=False)
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    out = tools_files.search_files(request_id=rid)
    assert out.get("dryrun") is True


# --- masking -----------------------------------------------------------------

def test_excerpts_are_masked_when_the_account_masks(world):
    make(world.tree, "notes/contact.txt", f"invoice 2026 to pay, write to {EMAIL} now")
    attachment_mask.set_enabled(1, True)
    _, out = _searched(world)
    (hit,) = out["results"]
    assert hit["excerpt"] and EMAIL not in hit["excerpt"]
    assert hit["name"] == "contact.txt"


def test_a_masking_failure_withholds_the_excerpts(world, monkeypatch):
    make(world.tree, "notes/contact.txt", f"invoice 2026 to pay, write to {EMAIL} now")
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    _, out = _searched(world)
    (hit,) = out["results"]
    assert hit["excerpt"] == ""
    assert "withheld" in out["note"]
    assert EMAIL not in json.dumps(out)


# --- read_file ---------------------------------------------------------------

def test_read_file_returns_the_text_of_a_found_file(world):
    found = _fill(world)
    rid, _ = _searched(world)
    out = tools_files.read_file(path=found["content"], request_id=rid)
    assert MARKER in out["text"]
    assert out["path"] == found["content"]
    assert out["kind"] == "text" and out["truncated"] is False
    assert "untrusted" in out["warning"]


def test_read_file_accepts_the_same_file_written_differently(world):
    found = _fill(world)
    rid, _ = _searched(world)
    path = found["content"]
    variant = os.path.join(os.path.dirname(path), "..", "notes", os.path.basename(path))
    if os.name == "nt":
        variant = variant.upper().replace("\\", "/")
    out = tools_files.read_file(path=variant, request_id=rid)
    assert out["path"] == path and MARKER in out["text"]


def test_read_file_masks_like_an_attachment(world):
    make(world.tree, "notes/contact.txt", f"invoice 2026 to pay, write to {EMAIL} now")
    attachment_mask.set_enabled(1, True)
    rid, out = _searched(world)
    r = tools_files.read_file(path=out["results"][0]["path"], request_id=rid)
    assert EMAIL not in r["text"] and r["masked"] is True


def test_read_file_cuts_the_text_at_60000_characters(world):
    make(world.tree, "long invoice 2026.txt", "y" * 70000)
    rid, out = _searched(world)
    r = tools_files.read_file(path=out["results"][0]["path"], request_id=rid)
    assert len(r["text"]) == 60000 and r["truncated"] is True


def test_read_file_refuses_a_path_the_search_did_not_find(world):
    _fill(world)
    rid, _ = _searched(world)
    other = str(world.tree / "notes" / "other.txt")
    with pytest.raises(ValueError, match="not among"):
        tools_files.read_file(path=other, request_id=rid)


def test_read_file_refuses_a_network_path_without_touching_the_disk(world, monkeypatch):
    _fill(world)
    rid, _ = _searched(world)
    monkeypatch.setattr(os.path, "realpath",
                        lambda *a, **kw: pytest.fail("the disk was touched"))
    with pytest.raises(ValueError, match="not among"):
        tools_files.read_file(path=r"\\server\share\x.txt", request_id=rid)


def test_read_file_refuses_another_tool_request(world):
    found = _fill(world)
    rid = world.approvals.create("send_mail", {"to": EMAIL}, {"subject": "x"})
    with pytest.raises(ValueError, match="search_files"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_an_unknown_request(world):
    with pytest.raises(ValueError, match="does not exist"):
        tools_files.read_file(path=str(world.tree / "x.txt"), request_id="req_nothing")


def test_read_file_refuses_a_pending_request(world):
    found = _fill(world)
    rid = _ask()["request_id"]
    with pytest.raises(ValueError, match="approv"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_a_rejected_request(world):
    found = _fill(world)
    rid = _ask()["request_id"]
    world.approvals.reject(rid, by="console:mario")
    with pytest.raises(ValueError, match="rejected"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_an_approved_search_that_has_not_run(world):
    found = _fill(world)
    rid = _ask()["request_id"]
    _approve(world, rid, complete=False)
    with pytest.raises(ValueError, match="not run"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_after_15_minutes(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    searched_at = world.approvals.get(rid)["provider_result"]["searched_at"]
    monkeypatch.setattr(tools_files, "_now", lambda: searched_at + 900)
    assert MARKER in tools_files.read_file(path=found["content"], request_id=rid)["text"]
    monkeypatch.setattr(tools_files, "_now", lambda: searched_at + 901)
    with pytest.raises(ValueError, match="15 minutes"):
        tools_files.read_file(path=found["content"], request_id=rid)


@pytest.mark.skipif(not hasattr(__import__("_winapi") if os.name == "nt" else os,
                                "CreateJunction"), reason="Windows junctions")
def test_read_file_refuses_a_file_whose_folder_became_a_junction(world):
    import _winapi
    found = _fill(world)
    rid, _ = _searched(world)
    secret = world.tmp / ".secret"
    make(secret, "letter.txt", "secret text")
    notes = world.tree / "notes"
    os.rename(str(notes), str(world.tree / "notes_old"))
    _winapi.CreateJunction(str(secret), str(notes))
    with pytest.raises(ValueError, match="changed"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_a_file_replaced_by_a_symlink(world):
    found = _fill(world)
    rid, _ = _searched(world)
    secret = make(world.tmp / ".secret", "letter.txt", "secret text")
    os.remove(found["content"])
    try:
        os.symlink(secret, found["content"])
    except (OSError, NotImplementedError):
        pytest.skip("this user cannot create symlinks")
    with pytest.raises(ValueError, match="changed"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_judges_the_stored_resolved_path_with_the_exclusions(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    seen = []
    real_excluded = file_search.excluded

    def spy(path, **kw):
        seen.append((path, kw.get("is_dir")))
        return real_excluded(path, **kw)
    monkeypatch.setattr(file_search, "excluded", spy)
    tools_files.read_file(path=found["content"], request_id=rid)
    assert (os.path.realpath(found["content"]), False) in seen


@pytest.mark.skipif(os.name != "nt", reason="Windows file attributes")
def test_read_file_refuses_a_found_file_that_became_hidden(world):
    import ctypes
    found = _fill(world)
    rid, _ = _searched(world)
    assert ctypes.windll.kernel32.SetFileAttributesW(found["content"], 0x2)
    with pytest.raises(ValueError, match="hidden"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_an_online_only_file(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    monkeypatch.setattr(file_search, "is_online_only", lambda path, attrs=None: True)
    with pytest.raises(ValueError, match="OneDrive"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_an_unsupported_extension(world):
    found = _fill(world)
    rid, _ = _searched(world)
    with pytest.raises(ValueError, match="text"):
        tools_files.read_file(path=found["name_old"], request_id=rid)


def test_read_file_refuses_a_file_that_grew_too_big(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    monkeypatch.setattr(file_search, "MAX_CONTENT_BYTES", 5)
    with pytest.raises(ValueError, match="MB|big"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_waits_30_seconds_for_the_extraction():
    assert tools_files.READ_TIMEOUT_SECONDS == 30


def test_read_file_gives_up_when_the_extraction_is_slower_than_the_limit(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    release = threading.Event()

    def slow(path, original_filename="", max_pdf_pages=0):
        release.wait(5)
        return "late", "text"
    monkeypatch.setattr(tools_files.file_extractor, "extract_text", slow)
    monkeypatch.setattr(tools_files, "READ_TIMEOUT_SECONDS", 0.2)
    started = time.monotonic()
    try:
        with pytest.raises(ValueError, match="took more than 0.2 seconds"):
            tools_files.read_file(path=found["content"], request_id=rid)
        assert time.monotonic() - started < 3
    finally:
        release.set()


# --- the identity of a found file --------------------------------------------

def _hard_link_or_skip(target, link):
    try:
        os.link(target, link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hard links are not supported here")


def test_a_file_replaced_by_a_hard_link_is_refused_and_its_excerpt_withheld(world):
    found = _fill(world)
    rid, first = _searched(world)
    assert next(r for r in first["results"] if r["path"] == found["content"])["excerpt"]
    other = make(world.tmp / "elsewhere", "copy.txt",
                 f"the invoice for 2026, another file {MARKER}")
    os.remove(found["content"])
    _hard_link_or_skip(other, found["content"])
    with pytest.raises(ValueError, match="changed after the search"):
        tools_files.read_file(path=found["content"], request_id=rid)
    again = tools_files.search_files(request_id=rid)
    hit = next(r for r in again["results"] if r["path"] == found["content"])
    assert hit["excerpt"] == "" and hit["size"] is None


def test_a_file_replaced_by_another_file_is_refused(world):
    found = _fill(world)
    rid, _ = _searched(world)
    os.remove(found["content"])
    make(world.tree, "notes/filler.txt", "keeps the old file number from coming back")
    make(world.tree, "notes/letter.txt", "a new file with the same name")
    pair = world.approvals.get(rid)["provider_result"]["ids"][found["content"]]
    if tools_files._file_id(found["content"]) == pair:
        pytest.skip("the filesystem gave the new file the old number")
    with pytest.raises(ValueError, match="changed after the search"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_a_file_edited_in_place_is_still_readable(world):
    found = _fill(world)
    rid, _ = _searched(world)
    with open(found["content"], "a", encoding="utf-8") as fh:
        fh.write("\nadded later")
    out = tools_files.read_file(path=found["content"], request_id=rid)
    assert "added later" in out["text"]


def test_without_a_file_id_the_other_checks_still_apply(world, monkeypatch):
    found = _fill(world)
    monkeypatch.setattr(tools_files, "_file_id", lambda path: None)
    rid, _ = _searched(world)
    assert world.approvals.get(rid)["provider_result"]["ids"] == {}
    assert MARKER in tools_files.read_file(path=found["content"], request_id=rid)["text"]


# --- no disk access before a match -------------------------------------------

def test_a_path_that_matches_no_found_file_is_refused_without_touching_it(world,
                                                                         monkeypatch):
    _fill(world)
    rid, _ = _searched(world)
    probe = str(world.tree / "notes" / "other.txt")
    touched = []
    real_realpath, real_stat = os.path.realpath, os.stat

    def realpath(p, *a, **kw):
        if os.path.normcase(str(p)) == os.path.normcase(probe):
            touched.append(("realpath", p))
        return real_realpath(p, *a, **kw)

    def stat(p, *a, **kw):
        if os.path.normcase(str(p)) == os.path.normcase(probe):
            touched.append(("stat", p))
        return real_stat(p, *a, **kw)
    monkeypatch.setattr(os.path, "realpath", realpath)
    monkeypatch.setattr(os, "stat", stat)
    with pytest.raises(ValueError, match="not among"):
        tools_files.read_file(path=probe, request_id=rid)
    assert touched == []


# --- errors of the disk ------------------------------------------------------

def test_a_file_deleted_between_the_checks_and_the_read_is_refused_readably(world,
                                                                           monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    start = len(_audit_text())

    def vanish(path):
        os.remove(path)
        return False
    monkeypatch.setattr(file_search, "zip_too_big", vanish)
    with pytest.raises(ValueError, match="could not be read") as e:
        tools_files.read_file(path=found["content"], request_id=rid)
    assert found["content"] not in str(e.value)
    entries = [json.loads(line) for line in _audit_text(start).splitlines() if line]
    assert entries[-1]["tool"] == "read_file" and entries[-1]["outcome"] == "refused"


def test_an_os_error_on_the_size_is_a_readable_refusal(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)

    def broken(path):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(os.path, "getsize", broken)
    with pytest.raises(ValueError, match="could not be read .Access is denied."):
        tools_files.read_file(path=found["content"], request_id=rid)


# --- abandoned extractions ---------------------------------------------------

def test_slow_extractions_do_not_pile_up(world, monkeypatch):
    found = _fill(world)
    rid, _ = _searched(world)
    release = threading.Event()
    started = []

    def blocked(path, original_filename="", max_pdf_pages=0):
        started.append(path)
        release.wait(10)
        return "late", "text"
    monkeypatch.setattr(tools_files.file_extractor, "extract_text", blocked)
    monkeypatch.setattr(tools_files, "READ_TIMEOUT_SECONDS", 0.05)
    try:
        for _ in range(tools_files.MAX_ABANDONED_READS):
            with pytest.raises(ValueError, match="took more than"):
                tools_files.read_file(path=found["content"], request_id=rid)
        assert len(started) == tools_files.MAX_ABANDONED_READS
        with pytest.raises(ValueError, match="still busy"):
            tools_files.read_file(path=found["content"], request_id=rid)
        out = tools_files.search_files(request_id=rid)
        assert all(r["excerpt"] == "" for r in out["results"])
        assert "still busy" in out["note"]
        assert len(started) == tools_files.MAX_ABANDONED_READS
    finally:
        release.set()
        for worker in list(tools_files._abandoned):
            worker.join(5)
    # once they returned, reading works again
    assert tools_files.read_file(path=found["content"], request_id=rid)["text"] == "late"


# --- masking notes on excerpts -----------------------------------------------

def _fake_masking(monkeypatch, invented=False, unmatched=()):
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply", lambda aid, text: attachment_mask.Masked(
        text.replace("2026", "[DATE_1a2b3c4d]"), 1, invented, list(unmatched)))


def test_masked_excerpts_carry_the_notes_attachments_get(world, monkeypatch):
    make(world.tree, "notes/a.txt", "invoice 2026 first")
    make(world.tree, "notes/b.txt", "invoice 2026 second")
    _fake_masking(monkeypatch, invented=True, unmatched=["Tax code"])
    _, out = _searched(world)
    assert len(out["results"]) == 2
    assert all("[DATE_1a2b3c4d]" in r["excerpt"] for r in out["results"])
    assert attachment_mask.NOTE in out["note"]
    assert attachment_mask.NOTE_INVENTED in out["note"]
    assert out["fields_not_found"] == ["Tax code"]


def test_no_invented_note_and_no_missing_fields_when_none(world, monkeypatch):
    make(world.tree, "notes/a.txt", "invoice 2026 first")
    _fake_masking(monkeypatch)
    _, out = _searched(world)
    assert attachment_mask.NOTE in out["note"]
    assert attachment_mask.NOTE_INVENTED not in out["note"]
    assert "fields_not_found" not in out


def test_a_field_found_in_one_excerpt_is_not_listed_as_missing(world, monkeypatch):
    make(world.tree, "notes/a.txt", "invoice 2026 first")
    make(world.tree, "notes/b.txt", "invoice 2026 second")
    attachment_mask.set_enabled(1, True)
    monkeypatch.setattr(attachment_mask, "apply", lambda aid, text: attachment_mask.Masked(
        text, 1, False, ["Tax code"] if "first" in text else []))
    _, out = _searched(world)
    assert "fields_not_found" not in out


# --- the query on the second call --------------------------------------------

@pytest.mark.parametrize("query", [None, "", "   "])
def test_the_first_call_needs_a_query(world, query):
    with pytest.raises(ValueError, match="word"):
        tools_files.search_files(query=query)
    assert world.approvals.list_pending() == []


def test_the_second_call_ignores_query_and_folder(world):
    found = _fill(world)
    rid = _ask()["request_id"]
    _approve(world, rid)
    out = tools_files.search_files(query="something else", folder="relative",
                                   request_id=rid)
    assert out["query"] == "invoice 2026"
    assert {r["path"] for r in out["results"]} == set(found.values())


# --- more refusals of read_file ----------------------------------------------

def test_read_file_refuses_a_failed_search(world, monkeypatch):
    found = _fill(world)
    rid = _ask()["request_id"]
    monkeypatch.setattr(file_search, "search",
                        lambda *a, **kw: (_ for _ in ()).throw(ValueError("walk failed")))
    _approve(world, rid, complete=False)
    with pytest.raises(ValueError, match="walk failed"):
        server.execute_approved(rid)
    assert world.approvals.get(rid)["execution_outcome"] == "failed"
    with pytest.raises(ValueError, match="did not complete"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_a_dry_run(world, monkeypatch):
    found = _fill(world)
    rid = _ask()["request_id"]
    _approve(world, rid, complete=False)
    monkeypatch.setenv("ADE_MAIL_DRYRUN", "1")
    assert tools_files.search_files(request_id=rid).get("dryrun") is True
    with pytest.raises(ValueError, match="did not complete"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_read_file_refuses_an_expired_request(world):
    found = _fill(world)
    rid = world.approvals.create("search_files",
                                 {"query": "invoice 2026", "roots": [world.root]},
                                 {"subject": "x"}, ttl=-1)
    with pytest.raises(ValueError, match="expired"):
        tools_files.read_file(path=found["content"], request_id=rid)


def test_a_file_found_by_one_search_is_refused_with_another_search_id(world):
    found = _fill(world)
    make(world.tree, "march/report.txt", "nothing")
    rid_a, _ = _searched(world, "invoice 2026")
    rid_b, out_b = _searched(world, "report")
    assert [r["name"] for r in out_b["results"]] == ["report.txt"]
    assert MARKER in tools_files.read_file(path=found["content"], request_id=rid_a)["text"]
    with pytest.raises(ValueError, match="not among"):
        tools_files.read_file(path=found["content"], request_id=rid_b)


@pytest.mark.skipif(not hasattr(__import__("_winapi") if os.name == "nt" else os,
                                "CreateJunction"), reason="Windows junctions")
def test_the_excerpt_is_withheld_when_the_folder_became_a_junction(world):
    import _winapi
    found = _fill(world)
    rid, first = _searched(world)
    assert next(r for r in first["results"] if r["path"] == found["content"])["excerpt"]
    secret = world.tmp / ".secret"
    make(secret, "letter.txt", f"the invoice for 2026 in a secret place {MARKER}")
    notes = world.tree / "notes"
    os.rename(str(notes), str(world.tree / "notes_old"))
    _winapi.CreateJunction(str(secret), str(notes))
    again = tools_files.search_files(request_id=rid)
    hit = next(r for r in again["results"] if r["path"] == found["content"])
    assert hit["excerpt"] == "" and MARKER not in json.dumps(again)


# --- audit -------------------------------------------------------------------

def test_the_audit_keeps_the_query_and_the_read_path_only(world):
    start = len(_audit_text())
    found = _fill(world)
    rid, _ = _searched(world)
    tools_files.read_file(path=found["content"], request_id=rid)
    with pytest.raises(ValueError):
        tools_files.read_file(path=str(world.tree / "notes" / "other.txt"), request_id=rid)
    log = _audit_text(start)
    as_json = [json.loads(line) for line in log.splitlines() if line.strip()]
    assert "invoice 2026" in log
    for path in (found["name_new"], found["name_old"]):
        assert json.dumps(path)[1:-1] not in log
        assert os.path.basename(path) not in log
    assert MARKER not in log and "attached" not in log
    reads = [e for e in as_json if e["tool"] == "read_file"]
    assert [e["outcome"] for e in reads] == ["read", "refused"]
    assert reads[0]["args"] == {"request_id": rid, "path": found["content"]}
    executed = next(e for e in as_json if e["tool"] == "search_files"
                    and e["outcome"] == "executed")
    assert executed["args"] == {"query": "invoice 2026", "roots": [world.root]}
    assert executed["provider_result"]["paths_count"] == 3


# --- registration ------------------------------------------------------------

def _tools():
    return {t.name: t for t in asyncio.new_event_loop().run_until_complete(
        server.mcp.list_tools())}


def test_the_tools_are_registered_with_their_classes_and_executor():
    assert server.APPROVED_EXECUTORS["search_files"] is tools_files._exec_search_files
    tools = _tools()
    assert tools["search_files"].annotations == server.DANGEROUS
    assert tools["read_file"].annotations == server.READ_LOCAL
    search = tools["search_files"].description
    for part in ("Read-only", "search_knowledge", "list_knowledge_files",
                 "I did not find it in the account's documents. Shall I search the PC? "
                 "Approve the request below.",
                 "Non l'ho trovato tra i documenti dell'account. Vuoi che cerchi nel PC? "
                 "Approva la richiesta qui sotto.",
                 "AppData", "never from Telegram", "20", "15 minutes", "untrusted",
                 "a mail, a file or a web page"):
        assert part in search, part
    read = tools["read_file"].description
    for part in ("search_files", "15 minutes", "60000", "untrusted"):
        assert part in read, part


def test_the_tools_are_registered_after_the_identity_tool():
    names = list(_tools())
    assert names.index("update_identity") < names.index("search_files") < \
        names.index("read_file")


# --- what the other surfaces show ---------------------------------------------

def test_the_cli_prints_the_whole_search_request_before_asking(world, monkeypatch, capsys):
    """Words, folders and every line: what the user decides on, uncut (the
    list view cuts a long line at 300 characters)."""
    from gigamail import cli, consent
    out = _ask("invoice 2026")
    shown = []

    def require(reason):
        shown.append(capsys.readouterr().out)
        return False
    monkeypatch.setattr(consent, "require_human", require)
    assert cli.cmd_approvals_approve(SimpleNamespace(request_id=out["request_id"])) == 1
    body = out["preview"]["body"]
    assert shown and out["preview"]["subject"] in shown[0] and body in shown[0]
    assert world.approvals.get(out["request_id"])["status"] == policy.PENDING


def test_the_found_paths_reach_no_notification_and_no_channel_message(world, monkeypatch, capsys):
    """Nothing is sent when a search runs: the toast and Telegram message of
    the request carry the words and folders only. What the approval
    channels say after it (the completion report, Telegram's answer, the
    CLI's line) holds no path."""
    from gigamail import cli, completion, consent
    from gigamail.core import desktop_notify, telegram_channel
    from gigamail.watcher import telegram as tg_watcher
    found = _fill(world)
    out = _ask("invoice 2026")
    rid = out["request_id"]
    sent = []
    monkeypatch.setattr(desktop_notify, "notify", lambda *a, **kw: sent.append(("toast", a)) or True)
    monkeypatch.setattr(telegram_channel, "channel", lambda: sent.append(("telegram",)) or None)
    monkeypatch.setattr(consent, "require_human", lambda reason: True)
    assert cli.cmd_approvals_approve(SimpleNamespace(request_id=rid)) == 0
    assert not sent, "the execution of a search notifies nobody"
    cli_out = capsys.readouterr().out
    assert world.approvals.get(rid)["provider_result"]["paths"], "the search did run"
    report = completion.complete(rid)
    said = []
    tg = SimpleNamespace(send=lambda text, *a, **kw: said.append(text))
    tg_watcher._complete_agent_request(tg, rid)
    shown = cli_out + json.dumps(report, default=str) + "\n".join(said)
    for path in found.values():
        assert path not in shown and os.path.basename(path) not in shown
