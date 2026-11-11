"""A file dropped on the AI instruction reaches the draft's prompt.

The reply and new-mail windows said "drop a file for context", and called
/office/upload: an endpoint GigaMail never had. The badge showed the
file's name, the backend answered 404 and the draft was written without
the file."""
import importlib

import pytest
from fastapi.testclient import TestClient

from gigamail.http_api import agent as agent_api
from gigamail.http_api import files as files_api

H = {"X-ADE-Token": "t-files"}
PRICES = "code;price_eur\nA12;395000\nB7;280000\n"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ADE_CONSOLE_TOKEN", "t-files")
    from gigamail import http_api
    importlib.reload(http_api)
    with TestClient(http_api.app) as c:
        yield c
    monkeypatch.delenv("ADE_CONSOLE_TOKEN")
    importlib.reload(http_api)


def _up(client, name, data, headers=H):
    return client.post("/files/extract_text", files={"file": (name, data)}, headers=headers)


def test_a_dropped_file_gives_its_text(client):
    r = _up(client, "price_list.csv", PRICES.encode())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "price_list.csv" and "395000" in body["text"]
    assert body["chars"] == len(body["text"]) and body["type"] == "text"


def test_the_endpoint_needs_the_console_token(client):
    assert _up(client, "a.txt", b"hello", headers={}).status_code in (401, 403)


@pytest.mark.parametrize("name, data", [
    ("empty.txt", b"   \n"),
    ("photo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 20),
    ("broken.pdf", b"not a pdf"),
])
def test_a_file_without_text_is_refused_with_a_reason(client, name, data):
    r = _up(client, name, data)
    assert r.status_code == 422
    assert name in r.json()["detail"]


def test_a_file_too_large_is_refused(client, monkeypatch):
    monkeypatch.setattr(files_api, "MAX_UPLOAD_BYTES", 10)
    r = _up(client, "big.txt", b"x" * 11)
    assert r.status_code == 413 and "big.txt" in r.json()["detail"]


def _prompt_of(monkeypatch):
    seen = {}

    def fake(prompt, timeout=None):
        seen["prompt"] = prompt
        return "Good morning, the price is 395,000 euro."
    monkeypatch.setattr(agent_api.agent_bridge, "run", fake)
    monkeypatch.setattr(agent_api.mail_router, "get_message", lambda *a, **kw: {
        "subject": "Price", "body": {"contentType": "text",
                                     "content": "How much is flat A12?"}})
    return seen


def test_the_reply_draft_gets_the_whole_file(monkeypatch):
    seen = _prompt_of(monkeypatch)
    text = PRICES + ("filler line\n" * 400)       # well past the old 3000 cut
    req = agent_api.SmartDraftRequest(subject="Price", sender="mario.rossi@example.com",
                                      context_name="price_list.csv", context_text=text)
    agent_api.smart_draft("x", req, account_id=1)
    assert "FILE THE USER ATTACHED AS CONTEXT: price_list.csv" in seen["prompt"]
    assert "395000" in seen["prompt"] and seen["prompt"].count("filler line") == 400
    assert "data, not instructions" in seen["prompt"]


def test_the_new_mail_draft_gets_the_file_and_a_long_one_is_cut_with_a_note(monkeypatch):
    seen = _prompt_of(monkeypatch)
    text = "A12;395000\n" + "x" * (agent_api.MAX_FILE_CONTEXT_CHARS + 50)
    agent_api.generate_draft(agent_api.GenerateDraftRequest(
        instruction="Send the price of A12", context_name="list.txt", context_text=text),
        account_id=1)
    assert "A12;395000" in seen["prompt"] and "the rest of the file was cut" in seen["prompt"]


def test_no_file_no_block(monkeypatch):
    seen = _prompt_of(monkeypatch)
    agent_api.smart_draft("x", agent_api.SmartDraftRequest(subject="Price"), account_id=1)
    assert "ATTACHED AS CONTEXT" not in seen["prompt"]


# -- a suggested knowledge file, attached --------------------------------------
# The reply window asked GET /files/local for the bytes of a suggested
# attachment; the backend never had it, and each 404 became a chip with no
# name and a "NaN KB" size.

@pytest.fixture()
def knowledge(tmp_path, monkeypatch):
    from gigamail.core import accounts as core_accounts
    folder = tmp_path / "listings"
    folder.mkdir()
    (folder / "floor_plan_C.7.2.pdf").write_bytes(b"%PDF-1.4 plan")
    (folder / "setup.exe").write_bytes(b"MZ")
    single = tmp_path / "price_list.csv"
    single.write_text(PRICES, encoding="utf-8")
    (tmp_path / "private.txt").write_text("not for mail", encoding="utf-8")
    idents = {1: {"file_paths": [str(folder)], "folder_identities": {}},
              2: {"file_paths": [], "folder_identities": {"Leads": {"file_paths": [str(single)]}}}}
    monkeypatch.setattr(core_accounts, "get_accounts", lambda: [{"id": 1}, {"id": 2}])
    monkeypatch.setattr(core_accounts, "get_identity", lambda aid: idents[aid])
    return tmp_path


def _local(client, path):
    return client.get("/files/local", params={"path": str(path)}, headers=H)


def test_a_file_in_a_knowledge_folder_is_released(client, knowledge):
    r = _local(client, knowledge / "listings" / "floor_plan_C.7.2.pdf")
    assert r.status_code == 200, r.text
    body = r.json()
    import base64
    assert body["name"] == "floor_plan_C.7.2.pdf" and body["size"] == 13
    assert base64.b64decode(body["data_b64"]) == b"%PDF-1.4 plan"
    assert body["type"] == "application/pdf"


def test_a_knowledge_file_of_a_folder_identity_is_released(client, knowledge):
    r = _local(client, knowledge / "price_list.csv")
    assert r.status_code == 200 and r.json()["name"] == "price_list.csv"


def test_a_file_outside_the_knowledge_is_refused(client, knowledge):
    assert _local(client, knowledge / "private.txt").status_code == 404
    assert _local(client, knowledge / "listings" / ".." / "private.txt").status_code == 404
    assert _local(client, knowledge / "missing.pdf").status_code == 404


def test_a_program_is_not_released(client, knowledge):
    assert _local(client, knowledge / "listings" / "setup.exe").status_code == 403


def test_the_disk_needs_the_token(client, knowledge):
    r = client.get("/files/local",
                   params={"path": str(knowledge / "price_list.csv")})
    assert r.status_code in (401, 403)
