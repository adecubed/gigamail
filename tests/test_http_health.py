"""/health tells the console whether the backend it found is current.

The console leaves the backend running when its window closes. A backend
started before an update kept serving the old code to the new console: a
feature added on both sides stayed invisible until the process was killed
by hand.
"""
import os

import pytest
from fastapi.testclient import TestClient

from gigamail import http_api


@pytest.fixture()
def client():
    with TestClient(http_api.app) as c:
        yield c


def test_health_names_the_process_and_says_the_code_is_current(client):
    health = client.get("/health").json()
    assert health["service"] == "gigamail-console"
    assert health["pid"] == os.getpid()
    assert health["stale"] is False


def test_health_says_when_the_code_on_disk_changed(client, monkeypatch):
    monkeypatch.setattr(http_api, "code_stamp", lambda: "another-stamp")
    assert client.get("/health").json()["stale"] is True


def test_the_stamp_follows_the_sources(tmp_path, monkeypatch):
    import gigamail
    package = tmp_path / "gigamail"
    (package / "core").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "core" / "a.py").write_text("x = 1")
    monkeypatch.setattr(gigamail, "__file__", str(package / "__init__.py"))
    before = http_api.code_stamp()
    assert http_api.code_stamp() == before               # nothing changed
    (package / "core" / "b.py").write_text("y = 2")      # an update adds a file
    added = http_api.code_stamp()
    assert added != before
    target = package / "core" / "a.py"                   # ...or rewrites one
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert http_api.code_stamp() != added
    (package / "notes.txt").write_text("not code")       # other files don't count
    assert http_api.code_stamp() == http_api.code_stamp()
