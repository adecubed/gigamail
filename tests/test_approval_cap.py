"""Cap sulle richieste di approvazione (promesso su r/mcp, 2026-08-18).

Senza cap un agente che insiste produce una raffica di richieste identiche
finche' una non trova un umano distratto: l'autopilota che il gate esiste
per evitare. Due regole: stesso payload con una pending viva → stessa
request_id; oltre N richieste per tool in un'ora → fase 1 rifiuta.
"""
import time

import pytest

from ade_mail_agent import policy


@pytest.fixture(autouse=True)
def store_isolato(tmp_path):
    policy.set_store(policy.ApprovalStore(tmp_path / "approvals.db"))
    yield
    policy.set_store(None)


ARGS = {"to": "a@b.it", "subject": "x", "body": "y", "account_id": None}


def _phase1(args=ARGS, tool="send_mail"):
    return policy.execute_dangerous(
        tool, dict(args), None,
        preview_fn=lambda: {"to": args.get("to")},
        execute_fn=lambda a: {"sent": True},
    )


def test_stesso_payload_stessa_request_id():
    r1 = _phase1()
    r2 = _phase1()
    assert r1["status"] == "approval_required"
    assert r2["status"] == "approval_required"
    assert r2["request_id"] == r1["request_id"]
    assert r2.get("deduplicated") is True
    # nello store c'e' UNA sola pending
    assert len(policy.store().list_pending()) == 1


def test_ordine_chiavi_diverso_e_lo_stesso_payload():
    a = {"to": "a@b.it", "subject": "x", "body": "y", "account_id": None}
    b = {"account_id": None, "body": "y", "subject": "x", "to": "a@b.it"}
    assert policy.ApprovalStore.fingerprint("send_mail", a) == \
        policy.ApprovalStore.fingerprint("send_mail", b)
    r1 = _phase1(a)
    r2 = _phase1(b)
    assert r1["request_id"] == r2["request_id"]


def test_payload_diverso_nuova_request_id():
    r1 = _phase1()
    r2 = _phase1({**ARGS, "subject": "altro"})
    assert r2["request_id"] != r1["request_id"]
    assert len(policy.store().list_pending()) == 2


def test_stesso_payload_tool_diverso_non_dedup():
    r1 = _phase1(tool="send_mail")
    r2 = _phase1(tool="reply_mail")
    assert r1["request_id"] != r2["request_id"]


def test_dopo_decisione_si_puo_richiedere_di_nuovo():
    """La dedup vale solo per le PENDING vive: rifiutata → nuova richiesta
    legittima (l'utente puo' aver cambiato idea)."""
    r1 = _phase1()
    policy.store().reject(r1["request_id"], by="test")
    r2 = _phase1()
    assert r2["request_id"] != r1["request_id"]
    assert r2.get("deduplicated") is None


def test_dopo_scadenza_si_puo_richiedere_di_nuovo(monkeypatch):
    r1 = _phase1()
    # fa scadere la prima
    with policy.store()._conn() as c:
        c.execute("UPDATE approvals SET expires_at=? WHERE request_id=?",
                  (time.time() - 1, r1["request_id"]))
    r2 = _phase1()
    assert r2["request_id"] != r1["request_id"]


def test_tetto_orario_per_tool(monkeypatch):
    monkeypatch.setattr(policy, "_APPROVAL_MAX_PER_HOUR", 3)
    ids = set()
    for i in range(3):
        r = _phase1({**ARGS, "subject": f"s{i}"})
        assert r["status"] == "approval_required"
        ids.add(r["request_id"])
    assert len(ids) == 3
    r = _phase1({**ARGS, "subject": "s-troppo"})
    assert r["status"] == "rate_limited"
    assert r["request_id"] is None
    assert len(policy.store().list_pending()) == 3  # niente creato oltre il tetto


def test_tetto_non_blocca_la_dedup():
    """Al tetto, ripetere un payload gia' pending restituisce comunque la sua
    request_id (la dedup viene prima del conteggio): l'agente puo' sempre
    ritrovare la richiesta che l'utente sta per approvare."""
    policy._APPROVAL_MAX_PER_HOUR_backup = policy._APPROVAL_MAX_PER_HOUR
    try:
        policy._APPROVAL_MAX_PER_HOUR = 2
        r1 = _phase1({**ARGS, "subject": "a"})
        _phase1({**ARGS, "subject": "b"})
        again = _phase1({**ARGS, "subject": "a"})
        assert again["request_id"] == r1["request_id"]
        assert again.get("deduplicated") is True
    finally:
        policy._APPROVAL_MAX_PER_HOUR = policy._APPROVAL_MAX_PER_HOUR_backup


def test_tetto_e_per_tool():
    policy._APPROVAL_MAX_PER_HOUR_backup = policy._APPROVAL_MAX_PER_HOUR
    try:
        policy._APPROVAL_MAX_PER_HOUR = 1
        assert _phase1(tool="send_mail")["status"] == "approval_required"
        assert _phase1({**ARGS, "subject": "z"}, tool="send_mail")["status"] == "rate_limited"
        # un altro tool ha il suo contatore
        assert _phase1(tool="delete_message")["status"] == "approval_required"
    finally:
        policy._APPROVAL_MAX_PER_HOUR = policy._APPROVAL_MAX_PER_HOUR_backup


def test_migrazione_db_senza_fingerprint(tmp_path):
    """Un approvals.db creato da una versione precedente (senza colonna
    fingerprint) viene migrato all'apertura e continua a funzionare."""
    import sqlite3
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE approvals (
            request_id TEXT PRIMARY KEY, tool TEXT NOT NULL, args_json TEXT NOT NULL,
            preview_json TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
            expires_at REAL NOT NULL, decided_at REAL, decided_by TEXT)""")
        c.execute("INSERT INTO approvals VALUES ('req_old','send_mail','{}','{}','pending',?,?,NULL,NULL)",
                  (time.time(), time.time() + 600))
    s = policy.ApprovalStore(db)
    cols = {r[1] for r in s._conn().execute("PRAGMA table_info(approvals)")}
    assert "fingerprint" in cols
    # la vecchia riga (fingerprint NULL) non va in dedup con niente, e si crea normalmente
    policy.set_store(s)
    assert _phase1()["status"] == "approval_required"
