"""The per-tick limit of the Graph archive sync counts downloads only.

Ids already in the archive are skipped without a download, but they used
to count toward the limit: with a few complete folders the limit was spent
on them before the folders listed last were ever reached.
"""
import re
from email.message import EmailMessage

import pytest

from gigamail.core import archivio, archivio_sync

GRAPH = "https://graph.microsoft.com/v1.0"


def _mime(message_id: str) -> bytes:
    m = EmailMessage()
    m["Message-ID"] = f"<{message_id}@example.com>"
    m["From"] = "mario.rossi@example.com"
    m["To"] = "info@example.com"
    m["Subject"] = f"Message {message_id}"
    m["Date"] = "Wed, 14 Oct 2026 10:00:00 +0200"
    m.set_content("Is the flat in Via Roma 10 still available?")
    return m.as_bytes()


class FakeGraph:
    """Folders of message ids, newest first, served in pages."""

    def __init__(self, folders, page=50):
        self.folders = folders          # folder id -> [message id, ...]
        self.page = page
        self.downloaded = []

    def add(self, folder, message_id):
        self.folders[folder].insert(0, message_id)

    def get(self, url):
        if "/mailFolders?" in url:
            return {"value": [{"id": f, "displayName": f.title()}
                              for f in self.folders]}
        folder = url.split("/mailFolders/")[1].split("/")[0]
        found = re.search(r"\$skip=(\d+)", url)
        skip = int(found.group(1)) if found else 0
        ids = self.folders[folder][skip:skip + self.page]
        out = {"value": [{"id": i} for i in ids]}
        if skip + self.page < len(self.folders[folder]):
            out["@odata.nextLink"] = (f"{GRAPH}/me/mailFolders/{folder}"
                                      f"/messages?$skip={skip + self.page}")
        return out

    def get_raw(self, url):
        message_id = url.split("/messages/")[1].split("/")[0]
        self.downloaded.append(message_id)
        return _mime(message_id)

    def sync(self, **kw):
        return archivio_sync.sincronizza_graph(5, get=self.get,
                                               get_raw=self.get_raw, **kw)


@pytest.fixture()
def st(tmp_path):
    s = archivio.ArchiveStore(tmp_path / "a.db", tmp_path / "mail")
    archivio.set_store(s)
    yield s
    archivio.set_store(None)


def test_archived_ids_do_not_spend_the_limit_of_the_last_folders(st):
    graph = FakeGraph({f"folder{n}": [f"f{n}m{i}" for i in range(50)]
                       for n in range(5)})
    graph.sync(limite=1000)
    assert all(st.stato(5, f)["complete"] == 1 for f in graph.folders)

    graph.add("folder4", "fresh")
    graph.downloaded.clear()
    out = graph.sync()

    assert graph.downloaded == ["fresh"]
    assert out["nuovi"] == 1 and out["restano"] == 0


def test_a_complete_folder_cut_by_the_limit_keeps_the_older_messages(st):
    graph = FakeGraph({"inbox": ["old"]}, page=1)
    graph.sync()
    assert st.stato(5, "inbox")["complete"] == 1

    for message_id in ("new1", "new2", "new3"):
        graph.add("inbox", message_id)
    out = graph.sync(limite=2)
    assert graph.downloaded[-2:] == ["new3", "new2"] and out["restano"] == 1

    graph.downloaded.clear()
    out = graph.sync(limite=2)
    assert graph.downloaded == ["new1"]
    assert st.stato(5, "inbox")["complete"] == 1
    assert st.stato(5, "inbox")["cursor"] == ""


def test_a_complete_folder_cut_by_the_deadline_keeps_the_older_messages(
        st, monkeypatch):
    graph = FakeGraph({"inbox": ["old"]}, page=1)
    graph.sync()
    for message_id in ("new1", "new2"):
        graph.add("inbox", message_id)

    late = {"late": False}
    monkeypatch.setattr(archivio_sync, "_expired",
                        lambda deadline: deadline is not None and late["late"])
    real_get_raw = graph.get_raw

    def get_raw_then_late(url):
        late["late"] = True
        return real_get_raw(url)

    graph.get_raw = get_raw_then_late
    out = graph.sync(deadline=0.0)
    assert out["timed_out"] == 1 and graph.downloaded[-1] == "new2"

    late["late"] = False
    graph.get_raw = real_get_raw
    graph.downloaded.clear()
    graph.sync()
    assert graph.downloaded == ["new1"]
    assert st.stato(5, "inbox")["complete"] == 1
