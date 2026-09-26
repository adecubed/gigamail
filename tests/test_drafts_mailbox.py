"""Bozze copiate nella cartella Bozze della casella.

La mail iniziata in GigaMail deve ritrovarsi su Outlook o sul telefono, e
sparire da li' quando parte. Qui: il giro completo (router finto), IMAP
con un server finto, Graph con risposte finte, la migrazione del DB.
"""

import email
import email.policy
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from ade_mail_agent.core import drafts, imap_client, mail_router
from ade_mail_agent.core import mail as ms_mail


@pytest.fixture()
def store(tmp_path):
    s = drafts.DraftStore(tmp_path / "drafts.db")
    drafts.set_store(s)
    yield s
    drafts.set_store(None)


@pytest.fixture()
def casella(monkeypatch):
    """Router finto: registra cosa arriva alla casella."""
    log = {"save": [], "delete": [], "fail": None}

    def _save(account_id=None, draft=None, remote_id=None):
        log["save"].append((account_id, dict(draft), remote_id))
        if log["fail"]:
            return {"success": False, "error": log["fail"]}
        return {"success": True, "remote_id": f"r{len(log['save'])}",
                "remote_folder": "Drafts"}

    def _delete(account_id=None, draft_id="", remote_id=None):
        log["delete"].append((account_id, draft_id, remote_id))
        return {"success": True}

    monkeypatch.setattr(mail_router, "save_draft", _save)
    monkeypatch.setattr(mail_router, "delete_draft", _delete)
    return log


# ── giro completo ────────────────────────────────────────────────────

def test_copia_poi_modifica_poi_nuova_copia_sostituisce(store, casella):
    d = store.save("d1", account_id=2, to="anna@example.com", body="v1")
    assert not d["in_mailbox"]
    assert drafts.sync("d1")["in_mailbox"]
    assert casella["save"][0][2] is None           # prima copia: niente da sostituire

    assert drafts.sync("d1")["in_mailbox"]
    assert len(casella["save"]) == 1               # gia' li': non si riscrive

    store.save("d1", account_id=2, to="anna@example.com", body="v2")
    assert not store.get("d1")["in_mailbox"]       # la casella ha la v1
    drafts.sync("d1")
    assert casella["save"][1][1]["body"] == "v2"
    assert casella["save"][1][2] == "r1"           # sostituisce la copia di prima


def test_errore_di_copia_resta_leggibile_e_si_riprova(store, casella):
    store.save("d1", account_id=2, body="x")
    casella["fail"] = "Cartella Bozze non trovata nella casella"
    d = drafts.sync("d1")
    assert not d["in_mailbox"] and "Bozze non trovata" in d["sync_error"]
    casella["fail"] = None
    d = drafts.sync("d1")
    assert d["in_mailbox"] and d["sync_error"] is None


def test_senza_account_non_si_copia(store, casella):
    store.save("d1", account_id=None, body="x")
    drafts.sync("d1")
    assert casella["save"] == []


def test_cancellare_toglie_anche_dalla_casella(store, casella):
    store.save("d1", account_id=2, body="x")
    drafts.sync("d1")
    d = drafts.discard("d1")
    drafts.remove_from_mailbox(d)
    assert store.get("d1") is None
    assert casella["delete"] == [(2, "d1", "r1")]


def test_mai_copiata_non_si_cerca_nella_casella(store, casella):
    store.save("d1", account_id=2, body="x")
    drafts.remove_from_mailbox(drafts.discard("d1"))
    assert casella["delete"] == []


def test_invio_durante_la_copia_non_lascia_la_bozza_nella_casella(store, monkeypatch):
    """La cancellazione aspetta la copia in volo e poi toglie proprio quella."""
    in_volo, via = threading.Event(), threading.Event()
    cancellate = []

    def _save_lenta(account_id=None, draft=None, remote_id=None):
        in_volo.set()
        via.wait(5)
        return {"success": True, "remote_id": "uid-77", "remote_folder": "Drafts"}

    monkeypatch.setattr(mail_router, "save_draft", _save_lenta)
    monkeypatch.setattr(mail_router, "delete_draft",
                        lambda account_id=None, draft_id="", remote_id=None:
                        cancellate.append(remote_id) or {"success": True})
    store.save("d1", account_id=2, body="x")
    t = threading.Thread(target=drafts.sync, args=("d1",))
    t.start()
    assert in_volo.wait(5)
    esito = {}
    t2 = threading.Thread(target=lambda: esito.setdefault("d", drafts.discard("d1")))
    t2.start()
    via.set()
    t.join(5)
    t2.join(5)
    drafts.remove_from_mailbox(esito["d"])
    assert cancellate == ["uid-77"]


def test_ripresa_da_outlook_ricorda_la_copia_da_sostituire(store, casella):
    store.save("d1", account_id=2, body="dal telefono",
               remote_id="4411", remote_folder="Drafts")
    drafts.sync("d1")
    assert casella["save"][0][2] == "4411"


# ── HTTP ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client(store):
    from ade_mail_agent import http_api
    with TestClient(http_api.app) as c:
        yield c


def test_sync_true_parte_in_background(client, monkeypatch):
    partite = []
    monkeypatch.setattr(drafts, "sync_in_background", partite.append)
    r = client.post("/mail/draft/save", json={"body": "x", "account_id": 2})
    assert partite == [] and r.json()["in_mailbox"] is False
    r = client.post("/mail/draft/save",
                    json={"id": r.json()["id"], "body": "x", "account_id": 2, "sync": True})
    assert partite == [r.json()["id"]]


def test_delete_http_toglie_anche_dalla_casella(client, store, casella, monkeypatch):
    monkeypatch.setattr(drafts, "remove_from_mailbox_in_background",
                        drafts.remove_from_mailbox)
    store.save("d1", account_id=2, body="x")
    drafts.sync("d1")
    assert client.delete("/mail/draft/local/d1").json()["deleted"] is True
    assert casella["delete"] == [(2, "d1", "r1")]


# ── migrazione ───────────────────────────────────────────────────────

def test_db_della_versione_precedente_si_aggiorna(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE drafts (draft_id TEXT PRIMARY KEY, account_id INTEGER, '
                  '"to" TEXT NOT NULL DEFAULT \'\', cc TEXT NOT NULL DEFAULT \'\', '
                  'bcc TEXT NOT NULL DEFAULT \'\', subject TEXT NOT NULL DEFAULT \'\', '
                  'body TEXT NOT NULL DEFAULT \'\', reply_to_id TEXT, '
                  'created_at REAL NOT NULL, updated_at REAL NOT NULL)')
        c.execute("INSERT INTO drafts (draft_id, body, created_at, updated_at) "
                  "VALUES ('vecchia', 'testo', 1, 1)")
    c.close()
    d = drafts.DraftStore(db).get("vecchia")
    assert d["body"] == "testo" and d["in_mailbox"] is False and d["remote_id"] is None


# ── IMAP ─────────────────────────────────────────────────────────────

class FakeImap:
    def __init__(self, messages=None, uidplus=True, appenduid=True):
        self.messages = dict(messages or {})   # uid -> bytes
        self.next_uid = max([int(u) for u in self.messages] or [100]) + 1
        self.capabilities = ("IMAP4REV1", "UIDPLUS") if uidplus else ("IMAP4REV1",)
        self.appenduid = appenduid
        self.flagged, self.expunged, self.plain_expunge = set(), [], 0

    def append(self, mailbox, flags, date, data):
        uid = str(self.next_uid)
        self.next_uid += 1
        self.messages[uid] = data
        self.last_append = (mailbox, flags)
        text = f"[APPENDUID 9 {uid}] Append completed." if self.appenduid else "Append completed."
        return "OK", [text.encode()]

    def select(self, mailbox):
        return "OK", [b"1"]

    def uid(self, command, *args):
        command = command.lower()
        if command == "search":
            value = args[-1].strip('"')
            hits = [u for u, raw in self.messages.items()
                    if email.message_from_bytes(raw).get(imap_client.DRAFT_HEADER) == value]
            return "OK", [" ".join(hits).encode()]
        if command == "store":
            self.flagged.update(args[0].split(","))
            return "OK", []
        if command == "expunge":
            for u in args[0].split(","):
                self.messages.pop(u, None)
            self.expunged.append(args[0])
            return "OK", []
        raise AssertionError(command)

    def expunge(self):
        self.plain_expunge += 1
        for u in list(self.flagged):
            self.messages.pop(u, None)
        return "OK", []

    def logout(self):
        pass


def _mime(draft_id):
    return imap_client.build_draft_mime("me@example.com",
                                        {"draft_id": draft_id, "body": "vecchia"})


@pytest.fixture()
def fake_imap(monkeypatch):
    holder = {}

    def _use(conn):
        holder["conn"] = conn
        monkeypatch.setattr(imap_client, "_connect", lambda *a, **k: conn)
        monkeypatch.setattr(imap_client, "_resolve_folder_strict",
                            lambda c, f: "Drafts" if f == "drafts" else None)
        monkeypatch.setattr(imap_client, "_close_conn_safely", lambda c: None)
        return conn
    return _use


DRAFT = {"draft_id": "d1", "to": "anna@example.com, luca@example.com",
         "cc": "", "bcc": "capo@example.com", "subject": "Visita",
         "body": "Buongiorno Anna,\nconfermo sabato."}


def test_mime_della_bozza():
    msg = email.message_from_bytes(imap_client.build_draft_mime("me@example.com", DRAFT),
                                 policy=email.policy.default)
    assert msg["From"] == "me@example.com"
    assert msg["To"] == "anna@example.com, luca@example.com"
    assert msg["Bcc"] == "capo@example.com" and msg["Cc"] is None
    assert msg[imap_client.DRAFT_HEADER] == "d1"
    assert "confermo sabato" in msg.get_content()


def test_imap_nuova_versione_toglie_la_vecchia(fake_imap):
    conn = fake_imap(FakeImap({"50": _mime("d1"), "60": _mime("altra")}))
    r = imap_client.save_draft("h", 993, "me@example.com", "pw", DRAFT)
    assert r == {"success": True, "uid": "61", "folder": "Drafts"}
    assert conn.last_append == ('"Drafts"', "(\\Draft \\Seen)")
    assert set(conn.messages) == {"60", "61"}     # la bozza di un'altra resta
    assert conn.expunged == ["50"] and conn.plain_expunge == 0


def test_imap_sostituisce_la_bozza_ripresa_da_outlook(fake_imap):
    conn = fake_imap(FakeImap({"70": b"Subject: dal telefono\r\n\r\nciao"}))
    imap_client.save_draft("h", 993, "me@example.com", "pw", DRAFT, replace_uid="70")
    assert set(conn.messages) == {"71"}


def test_imap_senza_appenduid_ritrova_l_uid_dall_header(fake_imap):
    conn = fake_imap(FakeImap({"50": _mime("d1")}, appenduid=False))
    r = imap_client.save_draft("h", 993, "me@example.com", "pw", DRAFT)
    assert r["uid"] == "51" and set(conn.messages) == {"51"}


def test_imap_senza_uidplus_usa_expunge(fake_imap):
    conn = fake_imap(FakeImap({"50": _mime("d1")}, uidplus=False))
    imap_client.save_draft("h", 993, "me@example.com", "pw", DRAFT)
    assert conn.plain_expunge == 1 and set(conn.messages) == {"51"}


def test_imap_delete_toglie_solo_la_bozza(fake_imap):
    conn = fake_imap(FakeImap({"50": _mime("d1"), "60": _mime("altra")}))
    assert imap_client.delete_draft("h", 993, "me@example.com", "pw", "d1")["success"]
    assert set(conn.messages) == {"60"}


def test_imap_senza_cartella_bozze_errore_chiaro(monkeypatch):
    monkeypatch.setattr(imap_client, "_connect", lambda *a, **k: FakeImap())
    monkeypatch.setattr(imap_client, "_resolve_folder_strict", lambda c, f: None)
    r = imap_client.save_draft("h", 993, "me@example.com", "pw", DRAFT)
    assert r["success"] is False and "Bozze" in r["error"]


# ── Graph ────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.text = status, data or {}, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture()
def graph(monkeypatch):
    calls = []
    state = {"isDraft": True, "exists": True}

    def _get(url, headers=None, params=None):
        calls.append(("GET", url))
        if not state["exists"]:
            return _Res(404)
        return _Res(200, {"id": "g1", "isDraft": state["isDraft"]})

    def _post(url, headers=None, json=None):
        calls.append(("POST", url, json))
        return _Res(201, {"id": "nuova"})

    def _patch(url, headers=None, json=None):
        calls.append(("PATCH", url, json))
        return _Res(200, {"id": "g1"})

    def _delete(url, headers=None):
        calls.append(("DELETE", url))
        return _Res(204)

    monkeypatch.setattr(ms_mail, "_headers", lambda: {})
    for name, fn in (("get", _get), ("post", _post), ("patch", _patch), ("delete", _delete)):
        monkeypatch.setattr(ms_mail.requests, name, fn)
    return calls, state


def test_graph_crea_poi_aggiorna_sul_posto(graph):
    calls, _ = graph
    assert ms_mail.save_draft(DRAFT) == {"success": True, "id": "nuova"}
    payload = calls[0][2]
    assert [r["emailAddress"]["address"] for r in payload["toRecipients"]] == [
        "anna@example.com", "luca@example.com"]
    assert payload["body"] == {"contentType": "Text", "content": DRAFT["body"]}

    assert ms_mail.save_draft(DRAFT, remote_id="g1") == {"success": True, "id": "g1"}
    assert calls[-1][0] == "PATCH" and calls[-1][1].endswith("/me/messages/g1")


def test_graph_non_riscrive_una_mail_che_non_e_bozza(graph):
    calls, state = graph
    state["isDraft"] = False
    assert ms_mail.save_draft(DRAFT, remote_id="g1")["success"] is False
    assert ms_mail.delete_draft("g1")["success"] is False
    assert not [c for c in calls if c[0] in ("PATCH", "DELETE", "POST")]


def test_graph_bozza_sparita_se_ne_crea_una_nuova(graph):
    calls, state = graph
    state["exists"] = False
    assert ms_mail.save_draft(DRAFT, remote_id="g1") == {"success": True, "id": "nuova"}
    assert ms_mail.delete_draft("g1") == {"success": True}
    assert not [c for c in calls if c[0] == "DELETE"]
