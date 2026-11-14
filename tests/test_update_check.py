"""The notice of a newer GigaMail for installs that never update by
themselves (pip, or the desktop app used only through MCP)."""
import json

import pytest

from gigamail.core import update_check


@pytest.fixture()
def checks_on(monkeypatch, tmp_path):
    monkeypatch.delenv("GIGAMAIL_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update_check, "_cache_path", lambda: tmp_path / "update_check.json")
    calls = []

    def fake_fetch(kind):
        calls.append(kind)
        return fake_fetch.answer
    fake_fetch.answer = "0.6.8"
    monkeypatch.setattr(update_check, "fetch_latest", fake_fetch)
    fake_fetch.calls = calls
    return fake_fetch


@pytest.mark.parametrize("exe, kind", [
    (r"C:\Program Files\GigaMail\resources\python\python.exe", "desktop"),
    ("/Applications/GigaMail.app/Contents/Resources/python/bin/python3", "desktop"),
    ("/tmp/.mount_GigaMail/resources/python/bin/python3", "desktop"),
    ("/usr/bin/python3", "pip"),
    (r"C:\Users\mario\AppData\Local\Programs\Python\Python313\python.exe", "pip"),
])
def test_install_kind_from_the_python_that_runs(monkeypatch, exe, kind):
    monkeypatch.delenv("GIGAMAIL_INSTALL_KIND", raising=False)
    assert update_check.install_kind(exe) == kind


@pytest.mark.parametrize("latest, current, expected", [
    ("0.6.8", "0.6.7", True),
    ("0.6.10", "0.6.9", True),
    ("v0.7.0", "0.6.7", True),
    ("0.6.7", "0.6.7", False),
    ("0.6.6", "0.6.7", False),
    ("0.6.8", "0.0.0+unknown", False),
])
def test_newer(latest, current, expected):
    assert update_check.newer(latest, current) is expected


def test_pip_install_hears_of_the_new_version(checks_on, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    update_check.refresh(now=1000.0)
    assert checks_on.calls == ["pip"]
    note = update_check.agent_notice("0.6.7")
    assert "GigaMail 0.6.8 is available" in note
    assert "pip install -U gigamail" in note
    assert "Do not update anything yourself" in note
    assert update_check.user_line("0.6.7", "it") == (
        "È disponibile GigaMail 0.6.8 (questa installazione è la 0.6.7): "
        "aggiorna con: pip install -U gigamail.")


def test_desktop_install_is_told_to_open_the_app(checks_on, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "desktop")
    update_check.refresh(now=1000.0)
    assert checks_on.calls == ["desktop"]
    assert "opening the GigaMail desktop app once installs it" in update_check.agent_notice("0.6.7")
    assert update_check.user_line("0.6.7", "en").endswith("open the GigaMail app to install it.")


def test_up_to_date_says_nothing(checks_on, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    update_check.refresh(now=1000.0)
    assert update_check.agent_notice("0.6.8") == ""
    assert update_check.user_line("0.6.8") == ""


def test_looks_up_at_most_once_a_day(checks_on, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    update_check.refresh(now=1000.0)
    update_check.refresh(now=1000.0 + 3600)
    assert checks_on.calls == ["pip"]
    update_check.refresh(now=1000.0 + update_check.CHECK_EVERY + 1)
    assert checks_on.calls == ["pip", "pip"]


def test_no_network_keeps_what_was_known_and_waits_a_day(checks_on, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    update_check.refresh(now=1000.0)
    checks_on.answer = None
    update_check.refresh(now=1000.0 + update_check.CHECK_EVERY + 1)
    assert update_check.available("0.6.7") == "0.6.8"
    update_check.refresh(now=1000.0 + update_check.CHECK_EVERY + 60)
    assert len(checks_on.calls) == 2


def test_switched_off(checks_on, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    update_check.refresh(now=1000.0)
    monkeypatch.setenv("GIGAMAIL_NO_UPDATE_CHECK", "1")
    assert update_check.agent_notice("0.6.7") == ""
    update_check.refresh(now=10 ** 9)
    assert checks_on.calls == ["pip"]


def test_a_cache_from_the_other_kind_of_install_is_not_used(checks_on, monkeypatch, tmp_path):
    (tmp_path / "update_check.json").write_text(json.dumps(
        {"checked_at": 1000.0, "kind": "desktop", "latest": "0.6.8"}), encoding="utf-8")
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    assert update_check.agent_notice("0.6.7") == ""


def test_a_broken_cache_file_is_ignored(checks_on, monkeypatch, tmp_path):
    (tmp_path / "update_check.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    assert update_check.agent_notice("0.6.7") == ""
    update_check.refresh(now=1000.0)
    assert update_check.available("0.6.7") == "0.6.8"


def test_fetch_reads_pypi_and_github(monkeypatch):
    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    seen = []

    def get(url, timeout, headers=None):
        seen.append(url)
        if "pypi" in url:
            return Resp({"info": {"version": "0.6.8"}})
        return Resp({"tag_name": "v0.6.8"})
    import requests
    monkeypatch.setattr(requests, "get", get)
    assert update_check.fetch_latest("pip") == "0.6.8"
    assert update_check.fetch_latest("desktop") == "0.6.8"
    assert seen == [update_check.PYPI_URL, update_check.GITHUB_URL]

    def down(url, timeout, headers=None):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests, "get", down)
    assert update_check.fetch_latest("pip") is None


def test_server_adds_the_notice_to_its_instructions(checks_on, monkeypatch):
    from gigamail import server
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    update_check.refresh(now=1000.0)
    monkeypatch.setattr(server, "_version", lambda: "0.6.7")
    monkeypatch.setattr(update_check, "refresh_in_background", lambda: None)
    low = server.mcp._lowlevel_server
    before = low.instructions
    try:
        server._announce_update()
        assert low.instructions.startswith(before)
        assert "GigaMail 0.6.8 is available" in low.instructions
    finally:
        low.instructions = before


def test_cli_prints_one_line_on_stderr(checks_on, monkeypatch, capsys):
    from gigamail import cli
    monkeypatch.setenv("GIGAMAIL_INSTALL_KIND", "pip")
    monkeypatch.setenv("GIGAMAIL_LANG", "en")
    update_check.refresh(now=1000.0)
    monkeypatch.setattr("gigamail.__version__", "0.6.7")
    cli._say_update()
    assert capsys.readouterr().err.strip() == (
        "GigaMail 0.6.8 is available (this install runs 0.6.7): update with: pip install -U gigamail.")
